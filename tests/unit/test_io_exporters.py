# ══════════════════════════════════════════════════════════════════════════════
#  tests.unit.test_io_exporters
#
#  Tests de emoparse.io.exporters.
#
#  Estrategia: construir una DB mínima en memoria (tmp_path) poblada con
#  datos controlados, correr cada exporter, y verificar que el CSV tenga
#  las columnas esperadas y los valores correctos.
# ══════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

import pytest

from emoparse.io.exporters import (
    export_discursos_csv,
    export_emociones_csv,
    export_frases_csv,
    export_full_run,
)
from emoparse.storage.db import Database
from emoparse.storage.schema import ALL_TABLES_DDL


# ══════════════════════════════════════════════════════════════════════════════
#  Fixtures
# ══════════════════════════════════════════════════════════════════════════════

def _init_db(path: Path) -> Database:
    """Crea DB con schema completo."""
    db = Database(path)
    for ddl in ALL_TABLES_DDL:
        db.execute_script(ddl)
    return db


def _insert_discurso(
    db: Database,
    codigo: str,
    contenido: str = "texto de prueba",
    summarizer_payload: dict | None = None,
    metadata_payload: dict | None = None,
    enunciation_payload: dict | None = None,
    metadata_error: str | None = None,
) -> None:
    input_json = json.dumps(
        {"codigo": codigo, "contenido": contenido, "titulo": f"T_{codigo}", "fecha": "2024-01-01"},
        ensure_ascii=False,
    )
    with db.transaction() as cur:
        cur.execute(
            """
            INSERT INTO discursos (
                codigo, input,
                summarizer_payload, metadata_payload, enunciation_payload,
                metadata_error
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                codigo,
                input_json,
                json.dumps(summarizer_payload, ensure_ascii=False) if summarizer_payload else None,
                json.dumps(metadata_payload, ensure_ascii=False) if metadata_payload else None,
                json.dumps(enunciation_payload, ensure_ascii=False) if enunciation_payload else None,
                metadata_error,
            ),
        )


def _insert_frase(
    db: Database,
    codigo: str,
    unit_idx: int,
    frase: str,
    actores_payload: list | None = None,
    emociones_payload: list | None = None,
) -> None:
    with db.transaction() as cur:
        cur.execute(
            """
            INSERT INTO frases (codigo, unit_idx, frase, actores_payload, emociones_payload)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                codigo, unit_idx, frase,
                json.dumps(actores_payload, ensure_ascii=False) if actores_payload else None,
                json.dumps(emociones_payload, ensure_ascii=False) if emociones_payload else None,
            ),
        )


def _insert_emocion(
    db: Database,
    codigo: str,
    frase_idx: int,
    emocion_idx: int,
    experienciador: str = "Pueblo",
    tipo_emocion: str = "miedo",
    modo_existencia: str = "realizada",
    deteccion_justificacion: str | None = "justificacion de prueba",
    caracterizacion_payload: dict | None = None,
) -> None:
    with db.transaction() as cur:
        cur.execute(
            """
            INSERT INTO emociones (
                codigo, frase_idx, emocion_idx,
                experienciador, tipo_emocion, modo_existencia,
                deteccion_justificacion, caracterizacion_payload
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                codigo, frase_idx, emocion_idx,
                experienciador, tipo_emocion, modo_existencia,
                deteccion_justificacion,
                json.dumps(caracterizacion_payload, ensure_ascii=False) if caracterizacion_payload else None,
            ),
        )


@pytest.fixture
def empty_db(tmp_path: Path) -> Database:
    return _init_db(tmp_path / "test.sqlite")


@pytest.fixture
def populated_db(tmp_path: Path) -> Database:
    """DB con un discurso, dos frases y dos emociones pobladas."""
    db = _init_db(tmp_path / "test.sqlite")

    _insert_discurso(
        db, "D1",
        contenido="Compatriotas, hoy comienza una nueva etapa.",
        summarizer_payload={"resumen": "Resumen del discurso."},
        metadata_payload={
            "tipo_discurso": "asuncion",
            "tipo_discurso_justificacion": "es una asuncion",
            "ciudad": "Buenos Aires",
            "provincia": "Buenos Aires",
            "pais": "Argentina",
            "lugar_justificacion": "sede del gobierno",
        },
        enunciation_payload={
            "enunciador": {"actor": "Presidente", "justificacion": "habla en primera persona"},
            "enunciatarios": [{"actor": "Pueblo", "tipo": "prodestinatario", "justificacion": "j"}],
        },
    )

    _insert_frase(
        db, "D1", 0, "Compatriotas, hoy comienza una nueva etapa.",
        actores_payload=[{"actor": "Pueblo", "tipo": "colectivo", "modo": "explicito", "justificacion": "j"}],
        emociones_payload=[{"experienciador": "Pueblo", "tipo_emocion": "esperanza", "modo_existencia": "realizada", "justificacion": "j"}],
    )
    _insert_frase(
        db, "D1", 1, "Vamos a trabajar juntos.",
        actores_payload=[],
        emociones_payload=None,
    )

    _insert_emocion(
        db, "D1", 0, 0,
        experienciador="Pueblo",
        tipo_emocion="esperanza",
        modo_existencia="realizada",
        caracterizacion_payload={
            "foria": "euforico",
            "foria_justificacion": "positiva",
            "dominancia": "cognoscitiva",
            "dominancia_justificacion": "j",
            "intensidad": "alta",
            "intensidad_justificacion": "j",
            "fuente": "Presidente",
            "tipo_fuente": "actor",
            "fuente_justificacion": "j",
        },
    )
    _insert_emocion(
        db, "D1", 0, 1,
        experienciador="Presidente",
        tipo_emocion="orgullo",
        modo_existencia="virtualizada",
        caracterizacion_payload=None,  # sin caracterización aún
    )

    return db


# ══════════════════════════════════════════════════════════════════════════════
#  export_discursos_csv
# ══════════════════════════════════════════════════════════════════════════════


class TestExportDiscursosCsv:

    def test_produces_file(self, populated_db: Database, tmp_path: Path) -> None:
        out = tmp_path / "out" / "discursos.csv"
        n = export_discursos_csv(populated_db, out)
        assert out.is_file()
        assert n == 1

    def test_row_count_matches(self, populated_db: Database, tmp_path: Path) -> None:
        out = tmp_path / "discursos.csv"
        export_discursos_csv(populated_db, out)

        with out.open(encoding="utf-8") as f:
            rows = list(csv.DictReader(f))

        assert len(rows) == 1

    def test_base_input_columns_present(self, populated_db: Database, tmp_path: Path) -> None:
        out = tmp_path / "discursos.csv"
        export_discursos_csv(populated_db, out)

        with out.open(encoding="utf-8") as f:
            row = next(csv.DictReader(f))

        assert row["codigo"] == "D1"
        assert "Compatriotas" in row["contenido"]
        assert row["titulo"] == "T_D1"
        assert row["fecha"] == "2024-01-01"

    def test_metadata_payload_flattened(self, populated_db: Database, tmp_path: Path) -> None:
        out = tmp_path / "discursos.csv"
        export_discursos_csv(populated_db, out)

        with out.open(encoding="utf-8") as f:
            row = next(csv.DictReader(f))

        assert "metadata__tipo_discurso" in row
        assert row["metadata__tipo_discurso"] == "asuncion"
        assert row["metadata__ciudad"] == "Buenos Aires"

    def test_summarizer_payload_flattened(self, populated_db: Database, tmp_path: Path) -> None:
        out = tmp_path / "discursos.csv"
        export_discursos_csv(populated_db, out)

        with out.open(encoding="utf-8") as f:
            row = next(csv.DictReader(f))

        assert "summarizer__resumen" in row
        assert row["summarizer__resumen"] == "Resumen del discurso."

    def test_enunciation_nested_dict_as_json_string(self, populated_db: Database, tmp_path: Path) -> None:
        """El enunciador es un dict anidado: debe estar como JSON string."""
        out = tmp_path / "discursos.csv"
        export_discursos_csv(populated_db, out)

        with out.open(encoding="utf-8") as f:
            row = next(csv.DictReader(f))

        # El enunciador es un dict dentro de enunciation → queda como JSON.
        enunciador_str = row.get("enunciation__enunciador", "")
        parsed = json.loads(enunciador_str)

        assert parsed["actor"] == "Presidente"

    def test_error_column_present_and_empty_when_no_error(
        self, populated_db: Database, tmp_path: Path
    ) -> None:
        out = tmp_path / "discursos.csv"
        export_discursos_csv(populated_db, out)

        with out.open(encoding="utf-8") as f:
            row = next(csv.DictReader(f))

        assert "metadata__error" in row
        assert row["metadata__error"] == ""

    def test_error_column_populated_when_error(self, tmp_path: Path) -> None:
        db = _init_db(tmp_path / "err.sqlite")
        _insert_discurso(db, "D2", metadata_error="Timeout LLM")

        out = tmp_path / "discursos.csv"
        export_discursos_csv(db, out)

        with out.open(encoding="utf-8") as f:
            row = next(csv.DictReader(f))

        assert row["metadata__error"] == "Timeout LLM"

    def test_empty_db_produces_empty_file(self, empty_db: Database, tmp_path: Path) -> None:
        out = tmp_path / "discursos.csv"
        n = export_discursos_csv(empty_db, out)

        assert n == 0
        assert out.read_text(encoding="utf-8") == ""

    def test_creates_parent_dir_if_missing(self, populated_db: Database, tmp_path: Path) -> None:
        out = tmp_path / "deep" / "nested" / "discursos.csv"
        export_discursos_csv(populated_db, out)

        assert out.is_file()

    def test_multiple_discursos(self, tmp_path: Path) -> None:
        db = _init_db(tmp_path / "multi.sqlite")

        _insert_discurso(db, "D1")
        _insert_discurso(db, "D2")
        _insert_discurso(db, "D3")

        out = tmp_path / "d.csv"
        n = export_discursos_csv(db, out)

        assert n == 3

        with out.open(encoding="utf-8") as f:
            rows = list(csv.DictReader(f))

        codigos = {r["codigo"] for r in rows}

        assert codigos == {"D1", "D2", "D3"}


# ══════════════════════════════════════════════════════════════════════════════
#  export_frases_csv
# ══════════════════════════════════════════════════════════════════════════════


class TestExportFrasesCsv:

    def test_produces_file(self, populated_db: Database, tmp_path: Path) -> None:
        out = tmp_path / "frases.csv"
        n = export_frases_csv(populated_db, out)
        assert out.is_file()
        assert n == 2

    def test_row_count_matches(self, populated_db: Database, tmp_path: Path) -> None:
        out = tmp_path / "frases.csv"
        export_frases_csv(populated_db, out)

        with out.open(encoding="utf-8") as f:
            rows = list(csv.DictReader(f))

        assert len(rows) == 2

    def test_required_columns_present(self, populated_db: Database, tmp_path: Path) -> None:
        out = tmp_path / "frases.csv"
        export_frases_csv(populated_db, out)

        with out.open(encoding="utf-8") as f:
            rows = list(csv.DictReader(f))

        expected = {
            "codigo", "unit_idx", "frase",
            "actores_payload", "actores_version", "actores_error",
            "emociones_payload", "emociones_version", "emociones_error",
            "emociones_pass2_payload", "emociones_pass2_version", "emociones_pass2_error",
            "created_at", "updated_at",
        }

        assert expected.issubset(set(rows[0].keys()))

    def test_actores_payload_is_json_string(self, populated_db: Database, tmp_path: Path) -> None:
        out = tmp_path / "frases.csv"
        export_frases_csv(populated_db, out)

        with out.open(encoding="utf-8") as f:
            rows = list(csv.DictReader(f))

        frase0 = next(r for r in rows if r["unit_idx"] == "0")
        parsed = json.loads(frase0["actores_payload"])

        assert isinstance(parsed, list)
        assert parsed[0]["actor"] == "Pueblo"

    def test_null_payload_exported_as_empty_string(self, populated_db: Database, tmp_path: Path) -> None:
        out = tmp_path / "frases.csv"
        export_frases_csv(populated_db, out)

        with out.open(encoding="utf-8") as f:
            rows = list(csv.DictReader(f))

        frase1 = next(r for r in rows if r["unit_idx"] == "1")

        assert frase1["emociones_payload"] == ""

    def test_ordering_by_codigo_and_unit_idx(self, tmp_path: Path) -> None:
        db = _init_db(tmp_path / "ord.sqlite")

        _insert_discurso(db, "D1")
        _insert_frase(db, "D1", 2, "tercera")
        _insert_frase(db, "D1", 0, "primera")
        _insert_frase(db, "D1", 1, "segunda")

        out = tmp_path / "f.csv"
        export_frases_csv(db, out)

        with out.open(encoding="utf-8") as f:
            rows = list(csv.DictReader(f))

        assert [r["unit_idx"] for r in rows] == ["0", "1", "2"]

    def test_empty_db_produces_empty_file(self, empty_db: Database, tmp_path: Path) -> None:
        out = tmp_path / "frases.csv"
        n = export_frases_csv(empty_db, out)

        assert n == 0
        assert out.read_text(encoding="utf-8") == ""


# ══════════════════════════════════════════════════════════════════════════════
#  export_emociones_csv
# ══════════════════════════════════════════════════════════════════════════════


class TestExportEmocionesCsv:

    def test_produces_file(self, populated_db: Database, tmp_path: Path) -> None:
        out = tmp_path / "emociones.csv"
        n = export_emociones_csv(populated_db, out)

        assert out.is_file()
        assert n == 2

    def test_row_count_matches(self, populated_db: Database, tmp_path: Path) -> None:
        out = tmp_path / "emociones.csv"
        export_emociones_csv(populated_db, out)

        with out.open(encoding="utf-8") as f:
            rows = list(csv.DictReader(f))

        assert len(rows) == 2

    def test_base_columns_present(self, populated_db: Database, tmp_path: Path) -> None:
        out = tmp_path / "emociones.csv"
        export_emociones_csv(populated_db, out)

        with out.open(encoding="utf-8") as f:
            rows = list(csv.DictReader(f))

        base = {"codigo", "frase_idx", "emocion_idx", "experienciador", "tipo_emocion", "modo_existencia"}

        assert base.issubset(set(rows[0].keys()))

    def test_caracterizacion_flattened(self, populated_db: Database, tmp_path: Path) -> None:
        out = tmp_path / "emociones.csv"
        export_emociones_csv(populated_db, out)

        with out.open(encoding="utf-8") as f:
            rows = list(csv.DictReader(f))

        # La primera emoción tiene caracterización.
        em0 = next(r for r in rows if r["emocion_idx"] == "0")

        assert "caracterizacion__foria" in em0
        assert em0["caracterizacion__foria"] == "euforico"
        assert em0["caracterizacion__dominancia"] == "cognoscitiva"
        assert em0["caracterizacion__intensidad"] == "alta"
        assert em0["caracterizacion__fuente"] == "Presidente"

    def test_missing_caracterizacion_is_empty_string(self, populated_db: Database, tmp_path: Path) -> None:
        out = tmp_path / "emociones.csv"
        export_emociones_csv(populated_db, out)

        with out.open(encoding="utf-8") as f:
            rows = list(csv.DictReader(f))

        # La segunda emoción NO tiene caracterización.
        em1 = next(r for r in rows if r["emocion_idx"] == "1")

        # Las columnas de caracterizacion presentes en el header deben ser "".
        caract_cols = [k for k in em1 if k.startswith("caracterizacion__")]

        assert caract_cols  # hay columnas (detectadas de la primera fila)

        for col in caract_cols:
            assert em1[col] == ""

    def test_ordering(self, tmp_path: Path) -> None:
        db = _init_db(tmp_path / "ord.sqlite")

        _insert_discurso(db, "D1")
        _insert_frase(db, "D1", 0, "frase")
        _insert_emocion(db, "D1", 0, 2, tipo_emocion="ira")
        _insert_emocion(db, "D1", 0, 0, tipo_emocion="miedo")
        _insert_emocion(db, "D1", 0, 1, tipo_emocion="alegria")

        out = tmp_path / "e.csv"
        export_emociones_csv(db, out)

        with out.open(encoding="utf-8") as f:
            rows = list(csv.DictReader(f))

        assert [r["emocion_idx"] for r in rows] == ["0", "1", "2"]
        assert [r["tipo_emocion"] for r in rows] == ["miedo", "alegria", "ira"]

    def test_empty_db_produces_empty_file(self, empty_db: Database, tmp_path: Path) -> None:
        out = tmp_path / "emociones.csv"
        n = export_emociones_csv(empty_db, out)

        assert n == 0
        assert out.read_text(encoding="utf-8") == ""

    def test_deteccion_justificacion_present(self, populated_db: Database, tmp_path: Path) -> None:
        out = tmp_path / "emociones.csv"
        export_emociones_csv(populated_db, out)

        with out.open(encoding="utf-8") as f:
            rows = list(csv.DictReader(f))

        assert "deteccion_justificacion" in rows[0]
        assert rows[0]["deteccion_justificacion"] == "justificacion de prueba"


# ══════════════════════════════════════════════════════════════════════════════
#  export_full_run
# ══════════════════════════════════════════════════════════════════════════════


class TestExportFullRun:

    def test_creates_three_files(self, populated_db: Database, tmp_path: Path) -> None:
        out_dir = tmp_path / "csvs"
        counts = export_full_run(populated_db, out_dir)

        assert (out_dir / "discursos.csv").is_file()
        assert (out_dir / "frases.csv").is_file()
        assert (out_dir / "emociones.csv").is_file()

    def test_returns_correct_counts(self, populated_db: Database, tmp_path: Path) -> None:
        counts = export_full_run(populated_db, tmp_path / "out")

        assert counts == {"discursos": 1, "frases": 2, "emociones": 2}

    def test_creates_output_dir_if_missing(self, populated_db: Database, tmp_path: Path) -> None:
        out_dir = tmp_path / "does" / "not" / "exist"

        assert not out_dir.exists()

        export_full_run(populated_db, out_dir)

        assert out_dir.is_dir()

    def test_empty_db_still_produces_files(self, empty_db: Database, tmp_path: Path) -> None:
        counts = export_full_run(empty_db, tmp_path / "out")

        assert counts == {"discursos": 0, "frases": 0, "emociones": 0}
