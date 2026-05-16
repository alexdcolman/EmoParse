# ══════════════════════════════════════════════════════════════════════════════
#  tests.unit.test_actors_kb_discoveries_repo
#
#  Tests del repositorio `ActorsKbDiscoveriesRepository`: insert, listado de
#  pendientes, marcado como revisado, filtrado por codigo.
# ══════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

from pathlib import Path

import pytest

from emoparse.storage.actors_kb_discoveries import ActorsKbDiscoveriesRepository
from emoparse.storage.db import Database
from emoparse.storage.schema import (
    CREATE_ACTORS_KB_DISCOVERIES,
    CREATE_ACTORS_KB_DISCOVERIES_INDEX,
)


@pytest.fixture
def repo(tmp_path: Path) -> ActorsKbDiscoveriesRepository:
    db_path = tmp_path / "test.sqlite"
    db = Database(db_path)
    with db.transaction() as cur:
        cur.execute(CREATE_ACTORS_KB_DISCOVERIES)
        cur.execute(CREATE_ACTORS_KB_DISCOVERIES_INDEX)
    return ActorsKbDiscoveriesRepository(db)


class TestInsert:

    def test_inserts_basic_discovery(
        self,
        repo: ActorsKbDiscoveriesRepository,
    ) -> None:
        repo.insert(
            codigo="DISC_001",
            unit_idx=3,
            actor_mencionado="el Macri",
            confianza="alta",
            contexto="dijo el Macri.",
            justificacion="No coincide con la KB.",
        )
        pending = repo.list_pending_review()
        assert len(pending) == 1
        d = pending[0]
        assert d["codigo"] == "DISC_001"
        assert d["unit_idx"] == 3
        assert d["actor_mencionado"] == "el Macri"
        assert d["confianza"] == "alta"

    def test_minimal_fields_optional(
        self,
        repo: ActorsKbDiscoveriesRepository,
    ) -> None:
        """contexto y justificacion son opcionales."""
        repo.insert(
            codigo="DISC_001",
            unit_idx=0,
            actor_mencionado="X",
            confianza="baja",
        )
        pending = repo.list_pending_review()
        assert len(pending) == 1
        assert pending[0]["contexto"] is None
        assert pending[0]["justificacion"] is None


class TestListing:

    def test_filter_by_codigo(
        self,
        repo: ActorsKbDiscoveriesRepository,
    ) -> None:
        repo.insert("A", 0, "actor1", "alta")
        repo.insert("A", 1, "actor2", "media")
        repo.insert("B", 0, "actor3", "baja")

        only_a = repo.list_pending_review(codigo="A")
        only_b = repo.list_pending_review(codigo="B")
        assert len(only_a) == 2
        assert len(only_b) == 1
        assert only_b[0]["actor_mencionado"] == "actor3"

    def test_ordering_by_discovery_time(
        self,
        repo: ActorsKbDiscoveriesRepository,
    ) -> None:
        repo.insert("A", 0, "primero", "alta")
        repo.insert("A", 1, "segundo", "alta")
        repo.insert("A", 2, "tercero", "alta")

        pending = repo.list_pending_review()
        names = [d["actor_mencionado"] for d in pending]
        assert names == ["primero", "segundo", "tercero"]

    def test_count_pending_review(
        self,
        repo: ActorsKbDiscoveriesRepository,
    ) -> None:
        assert repo.count_pending_review() == 0
        repo.insert("A", 0, "x", "alta")
        repo.insert("B", 1, "y", "media")
        assert repo.count_pending_review() == 2
        assert repo.count_pending_review(codigo="A") == 1


class TestMarkReviewed:

    def test_mark_reviewed_excludes_from_pending(
        self,
        repo: ActorsKbDiscoveriesRepository,
    ) -> None:
        repo.insert("A", 0, "x", "alta")
        repo.insert("A", 1, "y", "media")

        pending = repo.list_pending_review()
        assert len(pending) == 2

        target_id = pending[0]["id"]
        repo.mark_reviewed(target_id)

        pending_after = repo.list_pending_review()
        assert len(pending_after) == 1
        assert pending_after[0]["id"] != target_id

    def test_mark_reviewed_idempotent(
        self,
        repo: ActorsKbDiscoveriesRepository,
    ) -> None:
        repo.insert("A", 0, "x", "alta")
        target_id = repo.list_pending_review()[0]["id"]
        repo.mark_reviewed(target_id)
        # Segundo call: no falla, no afecta count.
        repo.mark_reviewed(target_id)
        assert repo.count_pending_review() == 0
