# ══════════════════════════════════════════════════════════════════════════════
#  tests.unit.test_cli_export
#
#  Tests del subcomando `emoparse export`.
# ══════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

import pytest

from emoparse.cli import main
from emoparse.cli.commands.export_cmd import handle
from emoparse.storage.db import Database
from emoparse.storage.schema import ALL_TABLES_DDL


# ══════════════════════════════════════════════════════════════════════════════
#  Helpers
# ══════════════════════════════════════════════════════════════════════════════

def _init_db(path: Path) -> Database:
    db = Database(path)
    for ddl in ALL_TABLES_DDL:
        db.execute_script(ddl)
    return db


def _make_populated_db(tmp_path: Path) -> Path:
    """DB mínima con 1 discurso, 1 frase, 1 emoción."""
    db_path = tmp_path / "run.sqlite"
    db = _init_db(db_path)

    input_json = json.dumps(
        {"codigo": "D1", "contenido": "Hola compatriotas.", "titulo": "T1"},
        ensure_ascii=False,
    )
    with db.transaction() as cur:
        cur.execute(
            "INSERT INTO discursos (codigo, input) VALUES (?, ?)",
            ("D1", input_json),
        )
        cur.execute(
            "INSERT INTO frases (codigo, unit_idx, frase) VALUES (?, ?, ?)",
            ("D1", 0, "Hola compatriotas."),
        )
        cur.execute(
            """
            INSERT INTO emociones
                (codigo, frase_idx, emocion_idx, experienciador, tipo_emocion, modo_existencia)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            ("D1", 0, 0, "Pueblo", "alegria", "realizada"),
        )

    return db_path


# ══════════════════════════════════════════════════════════════════════════════
#  Tests vía main()
# ══════════════════════════════════════════════════════════════════════════════

class TestExportCLI:

    def test_export_creates_three_csvs(self, tmp_path: Path) -> None:
        db_path = _make_populated_db(tmp_path)
        out_dir = tmp_path / "csvs"
        rc = main(["export", "--db", str(db_path), "--output-dir", str(out_dir)])
        assert rc == 0
        assert (out_dir / "discursos.csv").is_file()
        assert (out_dir / "frases.csv").is_file()
        assert (out_dir / "emociones.csv").is_file()

    def test_export_db_not_found_returns_1(self, tmp_path: Path) -> None:
        rc = main([
            "export",
            "--db", str(tmp_path / "no_existe.sqlite"),
            "--output-dir", str(tmp_path / "out"),
        ])
        assert rc == 1

    def test_export_creates_output_dir_if_missing(self, tmp_path: Path) -> None:
        db_path = _make_populated_db(tmp_path)
        out_dir = tmp_path / "new" / "nested" / "dir"
        assert not out_dir.exists()
        rc = main(["export", "--db", str(db_path), "--output-dir", str(out_dir)])
        assert rc == 0
        assert out_dir.is_dir()

    def test_export_prints_row_counts(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        db_path = _make_populated_db(tmp_path)
        main(["export", "--db", str(db_path), "--output-dir", str(tmp_path / "out")])
        out = capsys.readouterr().out
        assert "discursos.csv" in out
        assert "frases.csv" in out
        assert "emociones.csv" in out
        assert "1 filas" in out  # cada tabla tiene 1 fila

    def test_export_missing_db_arg_exits_nonzero(self) -> None:
        with pytest.raises(SystemExit) as exc:
            main(["export", "--output-dir", "/tmp/x"])
        assert exc.value.code != 0

    def test_export_missing_output_dir_arg_exits_nonzero(self, tmp_path: Path) -> None:
        db_path = _make_populated_db(tmp_path)
        with pytest.raises(SystemExit) as exc:
            main(["export", "--db", str(db_path)])
        assert exc.value.code != 0


# ══════════════════════════════════════════════════════════════════════════════
#  Tests vía handle() directo
# ══════════════════════════════════════════════════════════════════════════════

class TestExportHandleDirect:

    def _make_args(self, db: str, output_dir: str) -> argparse.Namespace:
        return argparse.Namespace(db=db, output_dir=output_dir)

    def test_handle_returns_0_on_success(self, tmp_path: Path) -> None:
        db_path = _make_populated_db(tmp_path)
        args = self._make_args(str(db_path), str(tmp_path / "out"))
        assert handle(args) == 0

    def test_handle_returns_1_db_missing(self, tmp_path: Path) -> None:
        args = self._make_args(str(tmp_path / "nope.sqlite"), str(tmp_path / "out"))
        assert handle(args) == 1

    def test_handle_csv_content_correct(self, tmp_path: Path) -> None:
        db_path = _make_populated_db(tmp_path)
        out_dir = tmp_path / "out"
        args = self._make_args(str(db_path), str(out_dir))
        handle(args)

        # discursos.csv tiene el codigo correcto.
        with (out_dir / "discursos.csv").open(encoding="utf-8") as f:
            d_rows = list(csv.DictReader(f))

        assert len(d_rows) == 1
        assert d_rows[0]["codigo"] == "D1"

        # frases.csv tiene la frase correcta.
        with (out_dir / "frases.csv").open(encoding="utf-8") as f:
            f_rows = list(csv.DictReader(f))

        assert len(f_rows) == 1
        assert f_rows[0]["frase"] == "Hola compatriotas."

        # emociones.csv tiene el tipo correcto.
        with (out_dir / "emociones.csv").open(encoding="utf-8") as f:
            e_rows = list(csv.DictReader(f))

        assert len(e_rows) == 1
        assert e_rows[0]["tipo_emocion"] == "alegria"
