# ══════════════════════════════════════════════════════════════════════════════
#  tests.unit.test_cache_repository
#
#  Tests del CacheRepository (lectura/escritura sobre llm_cache).
# ══════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

from pathlib import Path

import pytest

from emoparse.core.cache.keys import CacheKey, make_cache_key
from emoparse.core.cache.repository import CacheRepository
from emoparse.storage.db import Database
from emoparse.storage.models import RunContext, Versions
from emoparse.storage.runs import RunsRepository


@pytest.fixture
def db(tmp_path: Path) -> Database:
    db = Database(tmp_path / "test.sqlite")
    runs = RunsRepository(db)
    runs.bootstrap(RunContext(run_id="test"))
    return db


@pytest.fixture
def repo(db: Database) -> CacheRepository:
    return CacheRepository(db)


def _key(model: str = "m", system: str = "s", user: str = "u",
         versions: Versions = Versions()) -> CacheKey:
    return make_cache_key(
        model_alias=model,
        system=system,
        user=user,
        schema_qualname=None,
        seed=42,
        versions=versions,
    )


# ══════════════════════════════════════════════════════════════════════════════
#  Get / Set
# ══════════════════════════════════════════════════════════════════════════════


class TestGetSet:

    def test_get_missing_returns_none(self, repo: CacheRepository) -> None:
        key = _key()
        assert repo.get(key) is None

    def test_set_then_get_round_trip(self, repo: CacheRepository) -> None:
        key = _key()
        repo.set(
            key,
            raw='{"x": 1}',
            finish_reason="stop",
            prompt_tokens=10,
            completion_tokens=5,
            latency_ms=123.45,
        )
        loaded = repo.get(key)
        assert loaded is not None
        assert loaded.raw == '{"x": 1}'
        assert loaded.finish_reason == "stop"
        assert loaded.prompt_tokens == 10
        assert loaded.completion_tokens == 5
        assert loaded.latency_ms == pytest.approx(123.45)
        assert loaded.hit_count == 0  # no hit hecho todavía

    def test_latency_ms_none_when_not_set(self, repo: CacheRepository) -> None:
        """latency_ms es opcional: si no se pasa, se guarda NULL y se devuelve None."""
        key = _key()
        repo.set(key, raw="x")
        loaded = repo.get(key)
        assert loaded is not None
        assert loaded.latency_ms is None

    def test_set_does_not_overwrite_existing(self, repo: CacheRepository) -> None:
        """`INSERT OR IGNORE`: el segundo set con misma clave no pisa.

        Esto es defensa contra escrituras concurrentes. Si necesitás
        regenerar la respuesta, primero `purge_*` y después set.
        """
        key = _key()
        repo.set(key, raw="primero")
        repo.set(key, raw="segundo")  # debería ser ignorado

        loaded = repo.get(key)
        assert loaded is not None
        assert loaded.raw == "primero"

    def test_different_keys_independent(self, repo: CacheRepository) -> None:
        k1 = _key(user="A")
        k2 = _key(user="B")
        repo.set(k1, raw="a")
        repo.set(k2, raw="b")

        assert repo.get(k1).raw == "a"  # type: ignore[union-attr]
        assert repo.get(k2).raw == "b"  # type: ignore[union-attr]


# ══════════════════════════════════════════════════════════════════════════════
#  Hit recording
# ══════════════════════════════════════════════════════════════════════════════


class TestHitRecording:

    def test_record_hit_increments_count(self, repo: CacheRepository) -> None:
        key = _key()
        repo.set(key, raw="x")

        # Antes de hits.
        assert repo.get(key).hit_count == 0  # type: ignore[union-attr]

        repo.record_hit(key.digest)
        assert repo.get(key).hit_count == 1  # type: ignore[union-attr]

        repo.record_hit(key.digest)
        repo.record_hit(key.digest)
        assert repo.get(key).hit_count == 3  # type: ignore[union-attr]

    def test_record_hit_on_missing_key_silent(self, repo: CacheRepository) -> None:
        """record_hit sobre una clave inexistente: no-op silencioso.

        El UPDATE no afecta filas, no lanza. Es defensa contra race
        conditions: get() devolvió valor pero entre el get y el record
        alguien purgó esa entrada — preferimos no romper.
        """
        repo.record_hit("non_existent_digest")  # no debe lanzar


# ══════════════════════════════════════════════════════════════════════════════
#  Stats
# ══════════════════════════════════════════════════════════════════════════════


class TestStats:

    def test_session_counters_track_get_calls(self, repo: CacheRepository) -> None:
        key = _key()
        repo.get(key)              # miss
        repo.set(key, raw="x")
        repo.get(key)              # hit
        repo.get(_key(user="Z"))   # miss

        stats = repo.stats()
        assert stats["session_hits"] == 1
        assert stats["session_misses"] == 2
        assert stats["session_hit_rate"] == round(1 / 3, 3)

    def test_total_entries_counts_persistent_rows(
        self, repo: CacheRepository
    ) -> None:
        for i in range(5):
            repo.set(_key(user=f"u{i}"), raw=f"r{i}")
        stats = repo.stats()
        assert stats["total_entries"] == 5

    def test_by_model_groups_correctly(self, repo: CacheRepository) -> None:
        repo.set(_key(model="A", user="x"), raw="1")
        repo.set(_key(model="A", user="y"), raw="2")
        repo.set(_key(model="B", user="z"), raw="3")

        stats = repo.stats()
        assert stats["by_model"]["A"]["entries"] == 2
        assert stats["by_model"]["B"]["entries"] == 1

    def test_lifetime_hits_in_by_model(self, repo: CacheRepository) -> None:
        """`by_model.lifetime_hits` agrega hit_count de la tabla.

        Esto sobrevive entre sesiones, a diferencia de session_hits.
        """
        k = _key()
        repo.set(k, raw="x")
        repo.record_hit(k.digest)
        repo.record_hit(k.digest)

        stats = repo.stats()
        assert stats["by_model"]["m"]["lifetime_hits"] == 2


# ══════════════════════════════════════════════════════════════════════════════
#  Purge
# ══════════════════════════════════════════════════════════════════════════════


class TestPurge:

    def test_purge_by_model(self, repo: CacheRepository) -> None:
        repo.set(_key(model="A", user="x"), raw="1")
        repo.set(_key(model="A", user="y"), raw="2")
        repo.set(_key(model="B", user="z"), raw="3")

        n = repo.purge_by_model("A")
        assert n == 2
        assert repo.stats()["total_entries"] == 1

    def test_purge_by_versions_single_filter(
        self, repo: CacheRepository
    ) -> None:
        repo.set(_key(versions=Versions(prompt="v1")), raw="1")
        repo.set(_key(user="other", versions=Versions(prompt="v2")), raw="2")

        n = repo.purge_by_versions(prompt="v1")
        assert n == 1
        assert repo.stats()["total_entries"] == 1

    def test_purge_by_versions_combined_filters(
        self, repo: CacheRepository
    ) -> None:
        """Filtros combinados: AND. Solo borra entradas que matcheen TODOS."""
        repo.set(
            _key(versions=Versions(prompt="v1", ontology="o1")),
            raw="match",
        )
        repo.set(
            _key(user="b", versions=Versions(prompt="v1", ontology="o2")),
            raw="no_match_ont",
        )
        repo.set(
            _key(user="c", versions=Versions(prompt="v2", ontology="o1")),
            raw="no_match_pv",
        )

        n = repo.purge_by_versions(prompt="v1", ontology="o1")
        assert n == 1
        assert repo.stats()["total_entries"] == 2

    def test_purge_by_versions_requires_at_least_one_filter(
        self, repo: CacheRepository
    ) -> None:
        with pytest.raises(ValueError, match="al menos un filtro"):
            repo.purge_by_versions()

    def test_purge_all(self, repo: CacheRepository) -> None:
        for i in range(5):
            repo.set(_key(user=f"u{i}"), raw=f"r{i}")
        n = repo.purge_all()
        assert n == 5
        assert repo.stats()["total_entries"] == 0
