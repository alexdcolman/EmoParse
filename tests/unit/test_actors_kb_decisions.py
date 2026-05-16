# ══════════════════════════════════════════════════════════════════════════════
#  tests.unit.test_actors_kb_decisions
#
#  Tests de las decisiones de triage sobre discoveries.
# ══════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

from pathlib import Path

import pytest

from emoparse.storage.actors_kb_discoveries import (
    ActorsKbDiscoveriesRepository,
)
from emoparse.storage.db import Database
from emoparse.storage.schema import (
    CREATE_ACTORS_KB_DECISIONS,
    CREATE_ACTORS_KB_DECISIONS_INDEX,
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
        cur.execute(CREATE_ACTORS_KB_DECISIONS)
        cur.execute(CREATE_ACTORS_KB_DECISIONS_INDEX)
    return ActorsKbDiscoveriesRepository(db)


def _seed_discovery(repo: ActorsKbDiscoveriesRepository, **kwargs) -> int:
    """Inserta un discovery y devuelve su id."""
    defaults = dict(
        codigo="A",
        unit_idx=0,
        actor_mencionado="Milei",
        confianza="alta",
        contexto="ctx",
        justificacion="just",
    )
    defaults.update(kwargs)
    repo.insert(**defaults)
    return repo.list_pending_review()[-1]["id"]


class TestUpsertDecision:

    def test_register_promote(
        self, repo: ActorsKbDiscoveriesRepository
    ) -> None:
        did = _seed_discovery(repo)
        repo.upsert_decision(
            discovery_id=did,
            decision="promote",
            canonical_id="javier_milei",
            display_name="Javier Milei",
            tipo="individuo",
        )
        d = repo.find_decision(did)
        assert d is not None
        assert d["decision"] == "promote"
        assert d["canonical_id"] == "javier_milei"
        assert d["display_name"] == "Javier Milei"
        assert d["status"] == "pending"
        assert d["origin"] == "cli"  # default

    def test_register_merge(
        self, repo: ActorsKbDiscoveriesRepository
    ) -> None:
        did = _seed_discovery(repo)
        repo.upsert_decision(
            discovery_id=did,
            decision="merge",
            canonical_id="gobierno_argentino",
        )
        d = repo.find_decision(did)
        assert d["decision"] == "merge"
        assert d["canonical_id"] == "gobierno_argentino"

    def test_register_discard_no_canonical_id(
        self, repo: ActorsKbDiscoveriesRepository
    ) -> None:
        did = _seed_discovery(repo)
        repo.upsert_decision(discovery_id=did, decision="discard")
        d = repo.find_decision(did)
        assert d["decision"] == "discard"
        assert d["canonical_id"] is None

    def test_promote_requires_canonical_id(
        self, repo: ActorsKbDiscoveriesRepository
    ) -> None:
        did = _seed_discovery(repo)
        with pytest.raises(ValueError, match="canonical_id"):
            repo.upsert_decision(
                discovery_id=did,
                decision="promote",
                display_name="X",
            )

    def test_promote_requires_display_name(
        self, repo: ActorsKbDiscoveriesRepository
    ) -> None:
        did = _seed_discovery(repo)
        with pytest.raises(ValueError, match="display_name"):
            repo.upsert_decision(
                discovery_id=did,
                decision="promote",
                canonical_id="x_canonico",
            )

    def test_merge_requires_canonical_id(
        self, repo: ActorsKbDiscoveriesRepository
    ) -> None:
        did = _seed_discovery(repo)
        with pytest.raises(ValueError, match="canonical_id"):
            repo.upsert_decision(discovery_id=did, decision="merge")

    def test_invalid_decision_kind(
        self, repo: ActorsKbDiscoveriesRepository
    ) -> None:
        did = _seed_discovery(repo)
        with pytest.raises(ValueError, match="inválida"):
            repo.upsert_decision(
                discovery_id=did, decision="nope",  # type: ignore[arg-type]
            )

    def test_upsert_overwrites_pending(
        self, repo: ActorsKbDiscoveriesRepository
    ) -> None:
        did = _seed_discovery(repo)
        repo.upsert_decision(
            discovery_id=did, decision="discard", origin="cli",
        )
        repo.upsert_decision(
            discovery_id=did,
            decision="promote",
            canonical_id="x_canonico",
            display_name="X",
            origin="dashboard",
        )
        d = repo.find_decision(did)
        assert d["decision"] == "promote"
        assert d["origin"] == "dashboard"

    def test_cannot_overwrite_applied(
        self, repo: ActorsKbDiscoveriesRepository
    ) -> None:
        did = _seed_discovery(repo)
        repo.upsert_decision(
            discovery_id=did, decision="discard",
        )
        repo.mark_decision_applied(did)
        with pytest.raises(ValueError, match="aplicada"):
            repo.upsert_decision(
                discovery_id=did, decision="discard",
            )


class TestListDecisions:

    def test_lists_pending_with_discovery_metadata(
        self, repo: ActorsKbDiscoveriesRepository
    ) -> None:
        d1 = _seed_discovery(repo, actor_mencionado="A")
        d2 = _seed_discovery(repo, actor_mencionado="B", unit_idx=1)
        repo.upsert_decision(
            discovery_id=d1, decision="discard",
        )
        repo.upsert_decision(
            discovery_id=d2, decision="merge", canonical_id="x_canonico",
        )
        lst = repo.list_decisions(status="pending")
        assert len(lst) == 2
        first = next(x for x in lst if x["discovery_id"] == d1)
        assert first["actor_mencionado"] == "A"
        assert first["decision"] == "discard"

    def test_filters_by_status(
        self, repo: ActorsKbDiscoveriesRepository
    ) -> None:
        d1 = _seed_discovery(repo)
        repo.upsert_decision(discovery_id=d1, decision="discard")
        assert len(repo.list_decisions(status="pending")) == 1
        assert len(repo.list_decisions(status="applied")) == 0
        repo.mark_decision_applied(d1)
        assert len(repo.list_decisions(status="pending")) == 0
        assert len(repo.list_decisions(status="applied")) == 1

    def test_count_decisions(
        self, repo: ActorsKbDiscoveriesRepository
    ) -> None:
        assert repo.count_decisions("pending") == 0
        d1 = _seed_discovery(repo)
        repo.upsert_decision(discovery_id=d1, decision="discard")
        assert repo.count_decisions("pending") == 1


class TestMarkAppliedAndFailed:

    def test_apply_marks_discovery_reviewed(
        self, repo: ActorsKbDiscoveriesRepository
    ) -> None:
        did = _seed_discovery(repo)
        repo.upsert_decision(discovery_id=did, decision="discard")
        repo.mark_decision_applied(did)
        discovery = repo.find_discovery(did)
        assert discovery is not None
        assert discovery["reviewed"] == 1
        d = repo.find_decision(did)
        assert d["status"] == "applied"
        assert d["applied_at"] is not None
        assert d["error_message"] is None

    def test_failed_does_not_mark_reviewed(
        self, repo: ActorsKbDiscoveriesRepository
    ) -> None:
        did = _seed_discovery(repo)
        repo.upsert_decision(discovery_id=did, decision="discard")
        repo.mark_decision_failed(did, "boom")
        discovery = repo.find_discovery(did)
        assert discovery["reviewed"] == 0
        d = repo.find_decision(did)
        assert d["status"] == "failed"
        assert d["error_message"] == "boom"


class TestDeleteDecision:

    def test_delete_pending(self, repo: ActorsKbDiscoveriesRepository) -> None:
        did = _seed_discovery(repo)
        repo.upsert_decision(discovery_id=did, decision="discard")
        repo.delete_decision(did)
        assert repo.find_decision(did) is None


class TestFiltersOnDiscoveries:

    def test_list_pending_by_confianza(
        self, repo: ActorsKbDiscoveriesRepository
    ) -> None:
        _seed_discovery(repo, actor_mencionado="A", confianza="alta")
        _seed_discovery(repo, actor_mencionado="B", confianza="baja", unit_idx=1)
        _seed_discovery(repo, actor_mencionado="C", confianza="alta", unit_idx=2)
        altas = repo.list_pending_review(confianza="alta")
        assert len(altas) == 2
        assert all(d["confianza"] == "alta" for d in altas)
