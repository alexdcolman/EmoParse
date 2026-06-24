# ══════════════════════════════════════════════════════════════════════════════
#  tests.unit.test_emociones_tipo_configuracion_migration
#
#  Verifica que:
#  - Una DB nueva crea la columna tipo_configuracion vía DDL canónico.
#  - Una DB pre-v0.3.0 sin la columna la obtiene vía _apply_additive_migrations.
#  - upsert_emocion(es) acepta y persiste tipo_configuracion.
# ══════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

import sqlite3
from pathlib import Path

from emoparse.storage.db import Database
from emoparse.storage.emociones import EmocionesRepository
from emoparse.storage.models import RunContext, Versions
from emoparse.storage.runs import RunsRepository


def _columns(db_path: Path, table: str) -> set[str]:
    con = sqlite3.connect(db_path)
    try:
        return {r[1] for r in con.execute(f"PRAGMA table_info({table})")}
    finally:
        con.close()


def _ctx(run_id: str = "test") -> RunContext:
    return RunContext(
        run_id=run_id,
        versions=Versions(knowledge="v1", prompt="v1", ontology="v1", schema="v1"),
        started_at="2026-01-01T00:00:00+00:00",  # type: ignore[arg-type]
        config={},
        notes="",
    )


def test_new_db_has_column(tmp_path: Path) -> None:
    db = Database(tmp_path / "run.sqlite")
    RunsRepository(db).bootstrap(_ctx())
    cols = _columns(tmp_path / "run.sqlite", "emociones")
    assert "tipo_configuracion" in cols


def test_pre_v03_db_gets_column_via_migration(tmp_path: Path) -> None:
    """Simula DB pre-v0.3.0: crea emociones SIN la columna, luego corre bootstrap."""
    db_path = tmp_path / "old.sqlite"
    con = sqlite3.connect(db_path)
    try:
        con.execute(
            """
            CREATE TABLE emociones (
                codigo TEXT NOT NULL,
                frase_idx INTEGER NOT NULL,
                emocion_idx INTEGER NOT NULL,
                experienciador TEXT NOT NULL,
                tipo_emocion TEXT NOT NULL,
                fuente_marca TEXT NOT NULL,
                fuente_inferencia TEXT NOT NULL,
                modo_existencia TEXT NOT NULL,
                created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (codigo, frase_idx, emocion_idx)
            )
            """
        )
        con.commit()
    finally:
        con.close()

    assert "tipo_configuracion" not in _columns(db_path, "emociones")

    db = Database(db_path)
    RunsRepository(db).bootstrap(_ctx())

    assert "tipo_configuracion" in _columns(db_path, "emociones")


def test_upsert_persists_tipo_configuracion(tmp_path: Path) -> None:
    db = Database(tmp_path / "run.sqlite")
    RunsRepository(db).bootstrap(_ctx())

    # discurso/frase mínimos para FK
    with db.transaction() as cur:
        cur.execute(
            "INSERT INTO discursos (codigo, input) VALUES (?, ?)",
            ("A", "{}"),
        )
        cur.execute(
            "INSERT INTO frases (codigo, unit_idx, frase) VALUES (?, ?, ?)",
            ("A", 0, "frase"),
        )

    repo = EmocionesRepository(db)
    repo.upsert_emocion(
        codigo="A", frase_idx=0, emocion_idx=0,
        experienciador="el pueblo",
        experienciador_marca="el pueblo",
        tipo_emocion="indignacion",
        modo_existencia="realizada",
        tipo_configuracion="sostenido_en_sustantivos",
        fuente_marca="el socialismo",
        fuente_inferencia="socialismo",
    )
    row = repo.get_emocion("A", 0, 0)
    assert row is not None
    assert row["tipo_configuracion"] == "sostenido_en_sustantivos"
