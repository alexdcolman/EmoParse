# ══════════════════════════════════════════════════════════════════════════════
#  tests.unit.test_cache_backend
#
#  Tests del CachedBackend (decorator).
#
#  Verifica el comportamiento end-to-end: lookup → hit/miss → delegate →
#  guardar → propagación de errores → invalidación por versions.
# ══════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

from pathlib import Path
from typing import TypeVar

import pytest
from pydantic import BaseModel, Field

from emoparse.core.backend.base import LLMBackend, LLMResponse, TokenUsage
from emoparse.core.backend.exceptions import (
    BackendTimeoutError,
    SchemaViolationError,
)
from emoparse.core.cache import CachedBackend, CacheRepository
from emoparse.storage.db import Database
from emoparse.storage.models import RunContext, Versions
from emoparse.storage.runs import RunsRepository

T = TypeVar("T", bound=BaseModel)


# ══════════════════════════════════════════════════════════════════════════════
#  Schema y backend de prueba
# ══════════════════════════════════════════════════════════════════════════════


class _Schema(BaseModel):
    valor: int = Field(description="Un número")


class _MockBackend(LLMBackend):
    """Backend que cuenta llamadas y permite respuestas configurables.

    `default_raw` se usa cuando no hay un raw específico configurado para
    el (system, user) de una llamada. Útil para tests "siempre devuelve lo
    mismo".
    """

    def __init__(
        self,
        default_raw: str = '{"valor": 42}',
        default_finish: str = "stop",
    ) -> None:
        self.alias = "mock"
        self.calls = 0
        self.default_raw = default_raw
        self.default_finish = default_finish
        self.errors_to_raise: list[Exception] = []

    def generate(
        self,
        system: str,
        user: str,
        *,
        schema: type[T] | None = None,
        max_tokens: int | None = None,
        max_items: int | None = None,
        temperature: float | None = None,
        seed: int | None = None,
        stop: list[str] | None = None,
        reset_before: bool = False,
    ) -> LLMResponse:
        self.calls += 1
        if self.errors_to_raise:
            raise self.errors_to_raise.pop(0)
        parsed = None
        if schema is not None:
            parsed = schema.model_validate_json(self.default_raw)
        return LLMResponse(
            parsed=parsed,
            raw=self.default_raw,
            usage=TokenUsage(prompt_tokens=10, completion_tokens=5),
            latency_ms=500.0,
            model_alias=self.alias,
            cache_hit=False,
            finish_reason=self.default_finish,  # type: ignore[arg-type]
        )

    def healthcheck(self) -> bool:
        return True

    def close(self) -> None:
        self.closed = True

    def reset_state(self) -> None:
        self.was_reset = True


# ══════════════════════════════════════════════════════════════════════════════
#  Fixtures
# ══════════════════════════════════════════════════════════════════════════════


@pytest.fixture
def db(tmp_path: Path) -> Database:
    db = Database(tmp_path / "test.sqlite")
    runs = RunsRepository(db)
    runs.bootstrap(RunContext(run_id="test", versions=Versions(prompt="v1")))
    return db


@pytest.fixture
def repo(db: Database) -> CacheRepository:
    return CacheRepository(db)


@pytest.fixture
def ctx() -> RunContext:
    return RunContext(run_id="test", versions=Versions(prompt="v1"))


@pytest.fixture
def mock() -> _MockBackend:
    return _MockBackend()


@pytest.fixture
def cached(
    mock: _MockBackend, repo: CacheRepository, ctx: RunContext
) -> CachedBackend:
    return CachedBackend(mock, repo, ctx)


# ══════════════════════════════════════════════════════════════════════════════
#  Hit / Miss flow
# ══════════════════════════════════════════════════════════════════════════════


class TestHitMissFlow:

    def test_first_call_misses_and_invokes_backend(
        self, cached: CachedBackend, mock: _MockBackend
    ) -> None:
        r = cached.generate(system="S", user="U")
        assert r.cache_hit is False
        assert mock.calls == 1

    def test_second_identical_call_hits_and_skips_backend(
        self, cached: CachedBackend, mock: _MockBackend
    ) -> None:
        cached.generate(system="S", user="U")
        r2 = cached.generate(system="S", user="U")
        assert r2.cache_hit is True
        assert mock.calls == 1, "Backend no debe ser llamado en hit"

    def test_hit_returns_same_raw(
        self, cached: CachedBackend
    ) -> None:
        r1 = cached.generate(system="S", user="U")
        r2 = cached.generate(system="S", user="U")
        assert r1.raw == r2.raw

    def test_different_user_misses(
        self, cached: CachedBackend, mock: _MockBackend
    ) -> None:
        cached.generate(system="S", user="U1")
        cached.generate(system="S", user="U2")
        assert mock.calls == 2

    def test_different_system_misses(
        self, cached: CachedBackend, mock: _MockBackend
    ) -> None:
        cached.generate(system="S1", user="U")
        cached.generate(system="S2", user="U")
        assert mock.calls == 2


# ══════════════════════════════════════════════════════════════════════════════
#  Schema-aware caching
# ══════════════════════════════════════════════════════════════════════════════


class TestSchemaInCache:

    def test_hit_reconstructs_parsed_from_raw(
        self, cached: CachedBackend
    ) -> None:
        """En hit, el `parsed` se reconstruye re-parseando el raw."""
        r1 = cached.generate(system="S", user="U", schema=_Schema)
        r2 = cached.generate(system="S", user="U", schema=_Schema)

        assert r1.parsed is not None
        assert r2.parsed is not None
        assert isinstance(r2.parsed, _Schema)
        assert r2.parsed.valor == 42

    def test_hit_without_schema_has_parsed_none(
        self, cached: CachedBackend
    ) -> None:
        cached.generate(system="S", user="U")  # sin schema
        r2 = cached.generate(system="S", user="U")
        assert r2.cache_hit is True
        assert r2.parsed is None

    def test_call_with_schema_distinct_from_without(
        self,
        cached: CachedBackend,
        mock: _MockBackend,
    ) -> None:
        """Mismo prompt, una llamada con schema y otra sin: keys distintas."""
        cached.generate(system="S", user="U", schema=_Schema)
        cached.generate(system="S", user="U")  # sin schema
        # Cada uno fue MISS independiente.
        assert mock.calls == 2


# ══════════════════════════════════════════════════════════════════════════════
#  Invalidación por versions
# ══════════════════════════════════════════════════════════════════════════════


class TestVersionInvalidation:

    def test_changing_prompt_version_misses(
        self,
        mock: _MockBackend,
        repo: CacheRepository,
    ) -> None:
        """Mismo prompt, prompt_version cambiada → MISS."""
        ctx_v1 = RunContext(run_id="r", versions=Versions(prompt="v1"))
        ctx_v2 = RunContext(run_id="r", versions=Versions(prompt="v2"))

        cb_v1 = CachedBackend(mock, repo, ctx_v1)
        cb_v2 = CachedBackend(mock, repo, ctx_v2)

        cb_v1.generate(system="S", user="U")
        cb_v2.generate(system="S", user="U")  # MISS aunque prompt sea igual

        assert mock.calls == 2

    def test_changing_ontology_version_misses(
        self,
        mock: _MockBackend,
        repo: CacheRepository,
    ) -> None:
        ctx_o1 = RunContext(run_id="r", versions=Versions(ontology="o1"))
        ctx_o2 = RunContext(run_id="r", versions=Versions(ontology="o2"))

        cb_o1 = CachedBackend(mock, repo, ctx_o1)
        cb_o2 = CachedBackend(mock, repo, ctx_o2)

        cb_o1.generate(system="S", user="U")
        cb_o2.generate(system="S", user="U")

        assert mock.calls == 2

    def test_unrelated_version_change_does_not_invalidate(
        self,
        mock: _MockBackend,
        repo: CacheRepository,
    ) -> None:
        """Bumpear schema_version no debería invalidar si el backend
        no usa schema. El hash incluye TODAS las versions, así que
        actualmente sí invalida — esto es over-conservative pero
        seguro. Documentamos el comportamiento."""
        ctx_a = RunContext(run_id="r", versions=Versions(schema="s1"))
        ctx_b = RunContext(run_id="r", versions=Versions(schema="s2"))

        cb_a = CachedBackend(mock, repo, ctx_a)
        cb_b = CachedBackend(mock, repo, ctx_b)

        cb_a.generate(system="S", user="U")
        cb_b.generate(system="S", user="U")

        # Sí invalida (hash sensible).
        assert mock.calls == 2


# ══════════════════════════════════════════════════════════════════════════════
#  Errores no se cachean
# ══════════════════════════════════════════════════════════════════════════════


class TestErrorsNotCached:

    def test_backend_error_propagates(
        self, cached: CachedBackend, mock: _MockBackend
    ) -> None:
        mock.errors_to_raise.append(BackendTimeoutError("simulated"))
        with pytest.raises(BackendTimeoutError):
            cached.generate(system="S", user="U")

    def test_error_does_not_persist_in_cache(
        self, cached: CachedBackend, mock: _MockBackend, repo: CacheRepository
    ) -> None:
        """Después de un error, una segunda llamada debe RE-LLAMAR al
        backend (no devolver cached error)."""
        mock.errors_to_raise.append(BackendTimeoutError("first try"))
        with pytest.raises(BackendTimeoutError):
            cached.generate(system="S", user="U")

        # Segunda llamada idéntica: debería ser otra MISS, no hit.
        cached.generate(system="S", user="U")  # ahora exitosa
        assert mock.calls == 2

        # Y la tercera sí debe ser HIT.
        r = cached.generate(system="S", user="U")
        assert r.cache_hit is True
        assert mock.calls == 2

    def test_truncated_response_not_cached(
        self,
        repo: CacheRepository,
        ctx: RunContext,
    ) -> None:
        """Si el backend devuelve finish_reason='length' (truncado), NO
        cacheamos: cachear truncados perpetuaría outputs incompletos."""
        truncated_mock = _MockBackend(default_finish="length")
        cached = CachedBackend(truncated_mock, repo, ctx)
        cached.generate(system="S", user="U")
        # Segunda llamada idéntica DEBE re-invocar el backend (no se cacheó).
        cached.generate(system="S", user="U")
        assert truncated_mock.calls == 2


# ══════════════════════════════════════════════════════════════════════════════
#  Schema migration: cache hit con schema cambiado
# ══════════════════════════════════════════════════════════════════════════════


class TestSchemaMigrationHit:

    def test_hit_with_incompatible_schema_raises(
        self,
        repo: CacheRepository,
        ctx: RunContext,
    ) -> None:
        """Si el cache tiene un raw que no parsea contra el schema
        actual, lanza SchemaViolationError. El caller debe bumpear
        schema_version para regenerar."""

        # Backend con un raw que parsea contra OldSchema pero no contra NewSchema.
        class OldSchema(BaseModel):
            x: int

        class NewSchema(BaseModel):
            x: int
            y: int  # required nuevo, las entradas viejas no lo tienen

        mock = _MockBackend(default_raw='{"x": 1}')
        cached = CachedBackend(mock, repo, ctx)

        # Primer llamada: cachea {"x": 1} con schema_qualname=OldSchema.
        cached.generate(system="S", user="U", schema=OldSchema)
        assert mock.calls == 1

        # Segunda llamada con NewSchema: clave distinta (schema_qualname
        # cambió), MISS.
        from emoparse.core.cache.keys import make_cache_key
        bad_key = make_cache_key(
            model_alias=mock.alias,
            system="S2",
            user="U2",
            schema_qualname=f"{NewSchema.__module__}.{NewSchema.__qualname__}",
            seed=None,
            versions=ctx.versions,
        )
        repo.set(bad_key, raw='{"x": 1}')  # falta "y"

        # Ahora generate con NewSchema, mismos prompts: HIT pero re-parse falla.
        with pytest.raises(SchemaViolationError, match="schema_version"):
            cached.generate(system="S2", user="U2", schema=NewSchema)


# ══════════════════════════════════════════════════════════════════════════════
#  Telemetría: latency_ms
# ══════════════════════════════════════════════════════════════════════════════


class TestLatencyMs:

    def test_latency_ms_persisted_on_miss(
        self, cached: CachedBackend, repo: CacheRepository
    ) -> None:
        """En MISS, la latency_ms del backend se guarda en el cache."""
        from emoparse.core.cache.keys import make_cache_key
        from emoparse.storage.models import Versions

        cached.generate(system="S", user="U")

        key = make_cache_key(
            model_alias="mock",
            system="S",
            user="U",
            schema_qualname=None,
            seed=None,
            versions=Versions(prompt="v1"),
        )
        entry = repo.get(key)
        assert entry is not None
        # El _MockBackend devuelve latency_ms=500.0.
        assert entry.latency_ms == pytest.approx(500.0)

    def test_latency_ms_from_cache_returned_on_hit(
        self, cached: CachedBackend
    ) -> None:
        """En HIT, el LLMResponse devuelve la latency_ms original del backend
        (cacheada), no la latencia del lookup (~0 ms)."""
        cached.generate(system="S", user="U")        # MISS: cachea 500.0 ms
        r2 = cached.generate(system="S", user="U")   # HIT
        assert r2.cache_hit is True
        # La latencia original era 500.0 ms. La del lookup sería <<1 ms.
        # Se verifica que se devuelve la cacheada.
        assert r2.latency_ms == pytest.approx(500.0)

    def test_latency_ms_none_in_pre_t13_entries_falls_back_to_lookup(
        self, repo: CacheRepository, ctx: RunContext
    ) -> None:
        """Entradas pre-T13 tienen latency_ms=None en DB.
        En ese caso devolvemos la latencia del lookup (no None).
        """
        from emoparse.core.cache.keys import make_cache_key

        # Insertar una entrada sin latency_ms (simula entry pre-T13).
        key = make_cache_key(
            model_alias="mock",
            system="S",
            user="U",
            schema_qualname=None,
            seed=None,
            versions=ctx.versions,
        )
        repo.set(key, raw='{"valor": 42}', finish_reason="stop")
        # Confirmar que está None en DB.
        assert repo.get(key).latency_ms is None  # type: ignore[union-attr]

        mock = _MockBackend()
        cached = CachedBackend(mock, repo, ctx)
        r = cached.generate(system="S", user="U")

        assert r.cache_hit is True
        # latency_ms debe ser un número (la del lookup), no None.
        assert r.latency_ms is not None
        assert r.latency_ms >= 0.0


# ══════════════════════════════════════════════════════════════════════════════
#  Lifecycle: close, reset, healthcheck delegan al wrapped
# ══════════════════════════════════════════════════════════════════════════════


class TestLifecycle:

    def test_close_delegates(
        self, cached: CachedBackend, mock: _MockBackend
    ) -> None:
        cached.close()
        assert getattr(mock, "closed", False) is True

    def test_reset_state_delegates(
        self, cached: CachedBackend, mock: _MockBackend
    ) -> None:
        cached.reset_state()
        assert getattr(mock, "was_reset", False) is True

    def test_healthcheck_delegates(
        self, cached: CachedBackend
    ) -> None:
        # _MockBackend.healthcheck() siempre True.
        assert cached.healthcheck() is True

    def test_alias_passes_through(
        self, cached: CachedBackend, mock: _MockBackend
    ) -> None:
        assert cached.alias == mock.alias
