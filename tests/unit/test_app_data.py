# ══════════════════════════════════════════════════════════════════════════════
#  tests/unit/test_app_data.py
#
#  Tests de la capa de acceso a datos `emoparse.app.data`.
# ══════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd
import pytest

from emoparse.app import data as data_layer
from emoparse.storage.schema import ALL_TABLES_DDL


# ══════════════════════════════════════════════════════════════════════════════
#  Fixtures
# ══════════════════════════════════════════════════════════════════════════════

@pytest.fixture
def empty_db(tmp_path: Path) -> Path:
    """Una DB vacía con el schema completo aplicado."""
    db_path = tmp_path / "empty.sqlite"
    conn = sqlite3.connect(db_path)
    try:
        for ddl in ALL_TABLES_DDL:
            conn.execute(ddl)
        # Pase 2 — additive migration aplicada en bootstrap real.
        for col, type_def in [
            ("emociones_pass2_payload", "TEXT"),
            ("emociones_pass2_version", "TEXT"),
            ("emociones_pass2_error",   "TEXT"),
        ]:
            existing = {
                r[1] for r in conn.execute("PRAGMA table_info(frases)").fetchall()
            }
            if col not in existing:
                conn.execute(f"ALTER TABLE frases ADD COLUMN {col} {type_def}")
        conn.commit()
    finally:
        conn.close()
    return db_path


@pytest.fixture
def populated_db(empty_db: Path) -> Path:
    """DB poblada con 2 discursos, 4 frases, 5 emociones; varios estados."""
    now = datetime(2025, 1, 15, 10, 30, tzinfo=timezone.utc).isoformat()

    conn = sqlite3.connect(empty_db)
    try:
        # ── runs ──────────────────────────────────────────────────────────
        conn.execute(
            """INSERT INTO runs (
                run_id, started_at, finished_at, status,
                knowledge_version, prompt_version, ontology_version, schema_version,
                config, notes
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                "run_test_2025_01_15", now, now, "completed",
                "k-v1", "p-v3", "o-v2", "s-v1",
                json.dumps({"foo": "bar"}), "test run",
            ),
        )

        # ── discursos ─────────────────────────────────────────────────────
        # D1: completo en las 3 stages.
        conn.execute(
            """INSERT INTO discursos (
                codigo, input,
                summarizer_payload, summarizer_version,
                metadata_payload, metadata_version,
                enunciation_payload, enunciation_version
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                "D1",
                json.dumps({"contenido": "Texto del discurso 1.",
                            "titulo": "Discurso uno",
                            "fecha": "2024-12-15"}),
                json.dumps({"resumen_global": "Resumen 1",
                            "resumen_fragmentos": ["frag a", "frag b"]}),
                "p-v3",
                json.dumps({"tipo_discurso": "discurso_presidencial",
                            "ciudad": "Buenos Aires"}),
                "p-v3",
                json.dumps({"enunciador": "presidente",
                            "enunciatarios": ["pueblo"]}),
                "p-v3",
            ),
        )
        # D2: error en metadata, completo en summarizer, pending en enunciation.
        conn.execute(
            """INSERT INTO discursos (
                codigo, input,
                summarizer_payload, summarizer_version,
                metadata_error
            ) VALUES (?, ?, ?, ?, ?)""",
            (
                "D2",
                json.dumps({"contenido": "Texto 2.", "titulo": "Discurso dos"}),
                json.dumps({"resumen_global": "Resumen 2"}),
                "p-v3",
                "Backend timeout después de 3 reintentos.",
            ),
        )

        # ── frases ────────────────────────────────────────────────────────
        # D1: 2 frases con actors+emotions completos.
        conn.execute(
            """INSERT INTO frases (
                codigo, unit_idx, frase,
                actores_payload, actores_version,
                emociones_payload, emociones_version
            ) VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                "D1", 0, "Es una vergüenza lo que hicieron.",
                json.dumps([{"nombre": "ellos", "tipo": "humano"}]),
                "p-v3",
                json.dumps([
                    {"experienciador": "yo",
                     "tipo_emocion": "indignación",
                     "modo_existencia": "actualizado"},
                ]),
                "p-v3",
            ),
        )
        conn.execute(
            """INSERT INTO frases (
                codigo, unit_idx, frase,
                actores_payload, actores_version,
                emociones_payload, emociones_version
            ) VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                "D1", 1, "Tengo esperanza en el futuro.",
                json.dumps([{"nombre": "yo", "tipo": "humano"}]),
                "p-v3",
                json.dumps([
                    {"experienciador": "yo",
                     "tipo_emocion": "esperanza",
                     "modo_existencia": "virtualizado"},
                ]),
                "p-v3",
            ),
        )
        # D2: una frase con error en emociones, otra pending.
        conn.execute(
            """INSERT INTO frases (
                codigo, unit_idx, frase,
                actores_payload, actores_version,
                emociones_error
            ) VALUES (?, ?, ?, ?, ?, ?)""",
            (
                "D2", 0, "Frase del segundo discurso.",
                json.dumps([{"nombre": "alguien", "tipo": "humano"}]),
                "p-v3",
                "Parser falló: respuesta vacía",
            ),
        )
        conn.execute(
            """INSERT INTO frases (codigo, unit_idx, frase) VALUES (?, ?, ?)""",
            ("D2", 1, "Otra frase de D2 sin procesar."),
        )

        # ── emociones (post-explode) ──────────────────────────────────────
        # D1 emoción 0: caracterizada.
        conn.execute(
            """INSERT INTO emociones (
                codigo, frase_idx, emocion_idx,
                experienciador, tipo_emocion, modo_existencia,
                deteccion_justificacion,
                caracterizacion_payload, caracterizacion_version
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                "D1", 0, 0,
                "yo", "indignación", "actualizado",
                "primera persona expresando indignación",
                json.dumps({"foria": "disfórico",
                            "dominancia": "alta",
                            "intensidad": "alta",
                            "fuente": "moral"}),
                "p-v3",
            ),
        )
        # D1 emoción 1: caracterizada.
        conn.execute(
            """INSERT INTO emociones (
                codigo, frase_idx, emocion_idx,
                experienciador, tipo_emocion, modo_existencia,
                caracterizacion_payload, caracterizacion_version
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                "D1", 1, 0,
                "yo", "esperanza", "virtualizado",
                json.dumps({"foria": "eufórico",
                            "dominancia": "media",
                            "intensidad": "media",
                            "fuente": "personal"}),
                "p-v3",
            ),
        )
        # D1 emoción 2: con error de caracterización.
        conn.execute(
            """INSERT INTO emociones (
                codigo, frase_idx, emocion_idx,
                experienciador, tipo_emocion, modo_existencia,
                caracterizacion_error
            ) VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                "D1", 1, 1,
                "ellos", "miedo", "potencializado",
                "GBNF rechazó respuesta",
            ),
        )
        # D1 emoción 3: pending caracterización.
        conn.execute(
            """INSERT INTO emociones (
                codigo, frase_idx, emocion_idx,
                experienciador, tipo_emocion, modo_existencia
            ) VALUES (?, ?, ?, ?, ?, ?)""",
            ("D1", 0, 1, "ellos", "ira", "actualizado"),
        )
        # D2 emoción 0: caracterizada (aunque la frase tuvo error,
        # podemos tener emociones pre-existentes de un run parcial).
        conn.execute(
            """INSERT INTO emociones (
                codigo, frase_idx, emocion_idx,
                experienciador, tipo_emocion, modo_existencia,
                caracterizacion_payload, caracterizacion_version
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                "D2", 0, 0,
                "yo", "tristeza", "actualizado",
                json.dumps({"foria": "disfórico",
                            "dominancia": "baja",
                            "intensidad": "baja",
                            "fuente": "personal"}),
                "p-v3",
            ),
        )

        conn.commit()
    finally:
        conn.close()

    return empty_db


# ══════════════════════════════════════════════════════════════════════════════
#  list_runs / _inspect_run
# ══════════════════════════════════════════════════════════════════════════════

def test_list_runs_empty_dir(tmp_path: Path) -> None:
    """Si runs_dir no existe → lista vacía, no excepción."""
    nonexistent = tmp_path / "no_existe"
    assert data_layer.list_runs(nonexistent) == []


def test_list_runs_dir_without_sqlites(tmp_path: Path) -> None:
    """Directorio con archivos no-.sqlite → lista vacía."""
    (tmp_path / "no_es_sqlite.txt").write_text("nope")
    assert data_layer.list_runs(tmp_path) == []


def test_list_runs_finds_run(tmp_path: Path, populated_db: Path) -> None:
    """Un .sqlite poblado se lista con metadata correcta."""
    target = tmp_path / "runs"
    target.mkdir()
    # Mover el populated_db al directorio "runs/".
    new_path = target / populated_db.name
    populated_db.rename(new_path)

    runs = data_layer.list_runs(target)
    assert len(runs) == 1
    info = runs[0]
    assert info.path == new_path
    assert info.run_id == "run_test_2025_01_15"
    assert info.status == "completed"
    assert info.n_discursos == 2
    assert info.n_frases == 4


def test_list_runs_handles_corrupt_sqlite(tmp_path: Path) -> None:
    """Un .sqlite corrupto se incluye con metadata vacía, no crashea."""
    bad_path = tmp_path / "bad.sqlite"
    bad_path.write_bytes(b"not a sqlite file")

    runs = data_layer.list_runs(tmp_path)
    assert len(runs) == 1
    assert runs[0].run_id is None
    assert runs[0].status is None
    assert runs[0].n_discursos == 0


# ══════════════════════════════════════════════════════════════════════════════
#  get_run_stats
# ══════════════════════════════════════════════════════════════════════════════

def test_get_run_stats(populated_db: Path) -> None:
    stats = data_layer.get_run_stats(populated_db)
    assert stats["run_id"] == "run_test_2025_01_15"
    assert stats["status"] == "completed"
    assert stats["knowledge_version"] == "k-v1"
    assert stats["prompt_version"] == "p-v3"
    assert stats["ontology_version"] == "o-v2"
    assert stats["schema_version"] == "s-v1"
    assert stats["n_discursos"] == 2
    assert stats["n_frases"] == 4
    assert stats["n_emociones"] == 5
    assert stats["notes"] == "test run"


def test_get_run_stats_empty_db(empty_db: Path) -> None:
    """DB sin run row: campos None pero conteos válidos."""
    stats = data_layer.get_run_stats(empty_db)
    assert stats["run_id"] is None
    assert stats["status"] is None
    assert stats["n_discursos"] == 0
    assert stats["n_frases"] == 0
    assert stats["n_emociones"] == 0
    assert stats["notes"] == ""


# ══════════════════════════════════════════════════════════════════════════════
#  get_discursos
# ══════════════════════════════════════════════════════════════════════════════

def test_get_discursos_returns_dataframe(populated_db: Path) -> None:
    df = data_layer.get_discursos(populated_db)
    assert isinstance(df, pd.DataFrame)
    assert len(df) == 2
    assert set(df["codigo"]) == {"D1", "D2"}


def test_get_discursos_unpacks_input(populated_db: Path) -> None:
    """Las claves del input JSON aparecen como columnas con prefijo."""
    df = data_layer.get_discursos(populated_db)
    d1 = df[df["codigo"] == "D1"].iloc[0]
    assert d1["input__titulo"] == "Discurso uno"
    assert d1["input__fecha"] == "2024-12-15"


def test_get_discursos_unpacks_payloads(populated_db: Path) -> None:
    """Los payloads de stages se desempacan a columnas."""
    df = data_layer.get_discursos(populated_db)
    d1 = df[df["codigo"] == "D1"].iloc[0]
    assert d1["metadata__tipo_discurso"] == "discurso_presidencial"
    assert d1["metadata__ciudad"] == "Buenos Aires"
    # Lista anidada → JSON string en celda (no expansión).
    assert isinstance(d1["enunciation__enunciatarios"], str)
    assert "pueblo" in d1["enunciation__enunciatarios"]


def test_get_discursos_status_columns(populated_db: Path) -> None:
    """Cada stage tiene su columna __status con completed/failed/pending."""
    df = data_layer.get_discursos(populated_db)
    d1 = df[df["codigo"] == "D1"].iloc[0]
    d2 = df[df["codigo"] == "D2"].iloc[0]
    assert d1["summarizer__status"] == "completed"
    assert d1["metadata__status"] == "completed"
    assert d2["metadata__status"] == "failed"
    assert d2["enunciation__status"] == "pending"


def test_get_discursos_empty(empty_db: Path) -> None:
    df = data_layer.get_discursos(empty_db)
    assert df.empty


# ══════════════════════════════════════════════════════════════════════════════
#  get_frases
# ══════════════════════════════════════════════════════════════════════════════

def test_get_frases_all(populated_db: Path) -> None:
    df = data_layer.get_frases(populated_db)
    assert len(df) == 4
    assert set(df["codigo"]) == {"D1", "D2"}


def test_get_frases_filtered(populated_db: Path) -> None:
    df = data_layer.get_frases(populated_db, codigos=["D1"])
    assert len(df) == 2
    assert all(df["codigo"] == "D1")


def test_get_frases_empty_filter(populated_db: Path) -> None:
    """Filtro vacío → mismo comportamiento que None (todas las frases)."""
    df = data_layer.get_frases(populated_db, codigos=[])
    assert len(df) == 4


def test_get_frases_filter_no_match(populated_db: Path) -> None:
    df = data_layer.get_frases(populated_db, codigos=["D9999"])
    assert df.empty


def test_get_frases_parses_payloads(populated_db: Path) -> None:
    """Los payloads JSON vienen ya parseados a list/dict, no como strings."""
    df = data_layer.get_frases(populated_db, codigos=["D1"])
    f0 = df[df["unit_idx"] == 0].iloc[0]
    assert isinstance(f0["actores"], list)
    assert isinstance(f0["emociones"], list)
    assert f0["emociones"][0]["tipo_emocion"] == "indignación"


def test_get_frases_pending_returns_none(populated_db: Path) -> None:
    """Una frase pending tiene actores=None y emociones=None."""
    df = data_layer.get_frases(populated_db, codigos=["D2"])
    pending = df[df["unit_idx"] == 1].iloc[0]
    assert pending["actores"] is None
    assert pending["emociones"] is None


def test_get_frases_error_preserved(populated_db: Path) -> None:
    """El campo emociones_error se preserva en la columna."""
    df = data_layer.get_frases(populated_db, codigos=["D2"])
    failed = df[df["unit_idx"] == 0].iloc[0]
    assert failed["emociones"] is None
    assert "Parser falló" in failed["emociones_error"]


# ══════════════════════════════════════════════════════════════════════════════
#  get_emociones
# ══════════════════════════════════════════════════════════════════════════════

def test_get_emociones_all(populated_db: Path) -> None:
    df = data_layer.get_emociones(populated_db)
    assert len(df) == 5


def test_get_emociones_columns(populated_db: Path) -> None:
    """Caracterización flat: foria, dominancia, intensidad, fuente."""
    df = data_layer.get_emociones(populated_db)
    em = df[(df["codigo"] == "D1") & (df["frase_idx"] == 0) & (df["emocion_idx"] == 0)].iloc[0]
    assert em["foria"] == "disfórico"
    assert em["dominancia"] == "alta"
    assert em["intensidad"] == "alta"
    assert em["fuente"] == "moral"


def test_get_emociones_join_frase(populated_db: Path) -> None:
    """El texto de la frase se trae por join."""
    df = data_layer.get_emociones(populated_db)
    em = df[(df["codigo"] == "D1") & (df["frase_idx"] == 0) & (df["emocion_idx"] == 0)].iloc[0]
    assert "vergüenza" in em["frase"]


def test_get_emociones_join_discurso_metadata(populated_db: Path) -> None:
    """Título y fecha del discurso vienen por join con discursos.input."""
    df = data_layer.get_emociones(populated_db)
    em = df[df["codigo"] == "D1"].iloc[0]
    assert em["discurso__titulo"] == "Discurso uno"
    assert em["discurso__fecha"] == "2024-12-15"


def test_get_emociones_pending_caracterizacion(populated_db: Path) -> None:
    """Emoción sin caracterización: campos foria/etc no aparecen, pero
    los campos del nivel emoción (experienciador, tipo) sí."""
    df = data_layer.get_emociones(populated_db)
    em = df[(df["codigo"] == "D1") & (df["frase_idx"] == 0) & (df["emocion_idx"] == 1)].iloc[0]
    assert em["tipo_emocion"] == "ira"
    # foria es NaN (la columna existe porque pandas la creó por otras filas
    # pero esta fila no tenía caracterizacion_payload).
    assert pd.isna(em.get("foria"))


def test_get_emociones_filtered_by_codigo(populated_db: Path) -> None:
    df = data_layer.get_emociones(populated_db, codigos=["D2"])
    assert len(df) == 1
    assert df.iloc[0]["tipo_emocion"] == "tristeza"


def test_get_emociones_empty(empty_db: Path) -> None:
    assert data_layer.get_emociones(empty_db).empty


# ══════════════════════════════════════════════════════════════════════════════
#  get_stage_statuses
# ══════════════════════════════════════════════════════════════════════════════

def test_get_stage_statuses_returns_all_stages(populated_db: Path) -> None:
    """Devuelve un StageStatus por cada stage de STAGE_ORDER."""
    from emoparse.pipeline.runner import STAGE_ORDER
    statuses = data_layer.get_stage_statuses(populated_db)
    assert [s.stage for s in statuses] == list(STAGE_ORDER)


def test_get_stage_statuses_summarizer(populated_db: Path) -> None:
    """summarizer está en discursos, ambos D1 y D2 tienen payload → 2 completed."""
    statuses = data_layer.get_stage_statuses(populated_db)
    s = next(x for x in statuses if x.stage == "summarizer")
    assert s.completed == 2
    assert s.pending == 0
    assert s.failed == 0


def test_get_stage_statuses_metadata(populated_db: Path) -> None:
    """metadata: D1 ok, D2 failed → 1 completed, 1 failed."""
    statuses = data_layer.get_stage_statuses(populated_db)
    s = next(x for x in statuses if x.stage == "metadata")
    assert s.completed == 1
    assert s.failed == 1
    assert "D2" in s.failed_codigos


def test_get_stage_statuses_enunciation(populated_db: Path) -> None:
    """enunciation: D1 ok, D2 pending → 1 completed, 1 pending."""
    statuses = data_layer.get_stage_statuses(populated_db)
    s = next(x for x in statuses if x.stage == "enunciation")
    assert s.completed == 1
    assert s.pending == 1
    assert s.failed == 0


def test_get_stage_statuses_emotions(populated_db: Path) -> None:
    """emotions a nivel frase: D1 (2 ok) + D2 (1 failed, 1 pending)."""
    statuses = data_layer.get_stage_statuses(populated_db)
    s = next(x for x in statuses if x.stage == "emotions")
    assert s.completed == 2
    assert s.failed == 1
    assert s.pending == 1
    assert s.failed_codigos == ["D2"]  # agrupado por discurso, no por frase


def test_get_stage_statuses_characterizer(populated_db: Path) -> None:
    """characterizer en `emociones`: 3 caracterizadas, 1 con error, 1 pending."""
    statuses = data_layer.get_stage_statuses(populated_db)
    s = next(x for x in statuses if x.stage == "characterizer")
    assert s.completed == 3
    assert s.failed == 1
    assert s.pending == 1


def test_get_stage_statuses_empty_db(empty_db: Path) -> None:
    """Con DB vacía, todas las stages cuentan 0 en todos los buckets."""
    statuses = data_layer.get_stage_statuses(empty_db)
    for s in statuses:
        assert s.completed == 0
        assert s.failed == 0
        assert s.pending == 0


# ══════════════════════════════════════════════════════════════════════════════
#  Helpers internos (smoke tests)
# ══════════════════════════════════════════════════════════════════════════════

def test_unpack_json_dict_handles_none() -> None:
    assert data_layer._unpack_json_dict(None, "x__") == {}


def test_unpack_json_dict_handles_invalid_json() -> None:
    assert data_layer._unpack_json_dict("{not json}", "x__") == {}


def test_unpack_json_dict_serializes_nested() -> None:
    """Listas y dicts anidados se serializan a JSON string en su columna."""
    result = data_layer._unpack_json_dict(
        json.dumps({"a": 1, "b": [1, 2], "c": {"x": "y"}}),
        prefix="p__",
    )
    assert result["p__a"] == 1
    assert result["p__b"] == "[1, 2]"
    assert isinstance(result["p__c"], str)
    assert "x" in result["p__c"]


def test_stage_status_from_helper() -> None:
    assert data_layer._stage_status_from(None, None) == "pending"
    assert data_layer._stage_status_from(None, "err") == "failed"
    assert data_layer._stage_status_from('{"x":1}', None) == "completed"


def test_build_filter_sql_no_values() -> None:
    sql, params = data_layer._build_filter_sql("SELECT *", "codigo", None, "codigo")
    assert "WHERE" not in sql
    assert params == ()


def test_build_filter_sql_with_values() -> None:
    sql, params = data_layer._build_filter_sql(
        "SELECT *", "codigo", ["A", "B"], "codigo"
    )
    assert "WHERE codigo IN (?,?)" in sql
    assert params == ("A", "B")


def test_ro_connect_is_readonly(populated_db: Path) -> None:
    """Mode=ro debe rechazar escrituras."""
    with data_layer._ro_connect(populated_db) as conn:
        with pytest.raises(sqlite3.OperationalError):
            conn.execute("INSERT INTO discursos (codigo, input) VALUES ('X', '{}')")


# ══════════════════════════════════════════════════════════════════════════════
#  Filtros y argumentos defensivos
# ══════════════════════════════════════════════════════════════════════════════

def test_get_emociones_with_many_codigos(populated_db: Path) -> None:
    """Filtro con varios códigos: IN clause con múltiples placeholders."""
    df = data_layer.get_emociones(populated_db, codigos=["D1", "D2", "Dnoexiste"])
    assert len(df) == 5  # D1 + D2 = todas
