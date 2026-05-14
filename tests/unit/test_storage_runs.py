# ══════════════════════════════════════════════════════════════════════════════
#  tests.unit.test_storage_runs
#
#  Tests del RunsRepository: bootstrap idempotente, lectura, status updates,
#  invariante "una DB = un run".
# ══════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

from pathlib import Path

import pytest

from emoparse.storage.db import Database
from emoparse.storage.models import RunContext, Versions
from emoparse.storage.runs import RunsRepository


@pytest.fixture
def db(tmp_path: Path) -> Database:
    return Database(tmp_path / "test.sqlite")


@pytest.fixture
def ctx() -> RunContext:
    return RunContext(
        run_id="test_run_001",
        versions=Versions(knowledge="kv1", prompt="pv1", ontology="ov1", schema="sv1"),
        config={"modelo": "phi4-mini", "batch_size": 5},
        notes="test inicial",
    )


# ══════════════════════════════════════════════════════════════════════════════


class TestBootstrap:

    def test_creates_all_tables(self, db: Database, ctx: RunContext) -> None:
        repo = RunsRepository(db)
        repo.bootstrap(ctx)

        for table in ("runs", "discursos", "frases", "emociones", "llm_cache"):
            assert db.table_exists(table), f"Tabla {table} no creada"

    def test_inserts_run_row(self, db: Database, ctx: RunContext) -> None:
        repo = RunsRepository(db)
        repo.bootstrap(ctx)

        row = db.execute("SELECT * FROM runs").fetchone()
        assert row["run_id"] == "test_run_001"
        assert row["status"] == "running"
        assert row["knowledge_version"] == "kv1"
        assert row["prompt_version"] == "pv1"
        assert "modelo" in row["config"]

    def test_idempotent_for_same_run_id(self, db: Database, ctx: RunContext) -> None:
        """Re-bootstrap con el mismo run_id no duplica filas y no
        sobrescribe started_at original (resumability)."""
        repo = RunsRepository(db)
        repo.bootstrap(ctx)
        original_started = repo.get_run().started_at

        # Segundo bootstrap con el mismo ctx.
        repo.bootstrap(ctx)
        rows = db.execute("SELECT COUNT(*) AS n FROM runs").fetchone()
        assert rows["n"] == 1, "Bootstrap debería ser idempotente"

        # started_at no cambió.
        loaded = repo.get_run()
        assert loaded.started_at == original_started

    def test_rejects_different_run_id(self, db: Database, ctx: RunContext) -> None:
        """Una DB no puede contener dos runs distintos."""
        repo = RunsRepository(db)
        repo.bootstrap(ctx)

        other_ctx = RunContext(run_id="OTRO_RUN")
        with pytest.raises(RuntimeError, match="ya contiene"):
            repo.bootstrap(other_ctx)


class TestGetRun:

    def test_returns_none_if_no_run(self, db: Database) -> None:
        # DB sin bootstrap: no hay tabla runs todavía.
        repo = RunsRepository(db)
        # Crear tabla vacía manualmente (sin insertar fila).
        from emoparse.storage.schema import CREATE_RUNS
        db.execute(CREATE_RUNS)
        assert repo.get_run() is None

    def test_round_trip(self, db: Database, ctx: RunContext) -> None:
        repo = RunsRepository(db)
        repo.bootstrap(ctx)

        loaded = repo.get_run()
        assert loaded is not None
        assert loaded.run_id == ctx.run_id
        assert loaded.versions == ctx.versions
        assert loaded.config == ctx.config
        assert loaded.notes == ctx.notes


class TestStatus:

    def test_mark_completed(self, db: Database, ctx: RunContext) -> None:
        repo = RunsRepository(db)
        repo.bootstrap(ctx)
        repo.mark_completed()

        row = db.execute("SELECT status, finished_at FROM runs").fetchone()
        assert row["status"] == "completed"
        assert row["finished_at"] is not None

    def test_mark_failed_appends_to_notes(
        self, db: Database, ctx: RunContext
    ) -> None:
        repo = RunsRepository(db)
        repo.bootstrap(ctx)
        repo.mark_failed("simulated crash")

        row = db.execute("SELECT status, notes FROM runs").fetchone()
        assert row["status"] == "failed"
        assert "test inicial" in row["notes"]  # original
        assert "simulated crash" in row["notes"]  # appended


class TestVersions:

    def test_versions_with_some_none(self, db: Database) -> None:
        """Versions parciales (algunas None) deben round-trip correctamente."""
        repo = RunsRepository(db)
        ctx = RunContext(
            run_id="x",
            versions=Versions(knowledge="kv1", prompt=None, ontology="ov1", schema=None),
        )
        repo.bootstrap(ctx)

        loaded = repo.get_run()
        assert loaded.versions.knowledge == "kv1"
        assert loaded.versions.prompt is None
        assert loaded.versions.ontology == "ov1"
        assert loaded.versions.schema is None
