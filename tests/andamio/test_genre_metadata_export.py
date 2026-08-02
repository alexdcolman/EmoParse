from __future__ import annotations

import csv
import json
from datetime import datetime, timezone

from emoparse.genres.articulo_periodistico import get_genre
from emoparse.genres.presentation import attach_genre_presentation
from emoparse.io.exporters import (
    export_discursos_csv,
    export_full_run,
    export_metadata_genero_csv,
)
from emoparse.storage import Database, DiscursosRepository
from emoparse.storage.models import RunContext
from emoparse.storage.runs import RunsRepository


def _build_db(tmp_path, *, with_presentation: bool = True) -> Database:
    db = Database(tmp_path / "run_metadata.sqlite")
    config = {"pipeline": {"parallel": 1}}
    if with_presentation:
        config = attach_genre_presentation(config, get_genre())
    RunsRepository(db).bootstrap(
        RunContext(
            run_id="run_metadata",
            started_at=datetime.now(timezone.utc),
            config=config,
        )
    )
    DiscursosRepository(db).upsert_input(
        "art_1",
        {
            "titulo": "Nota de prueba",
            "contenido": "Primer párrafo. Segundo párrafo.",
            "medio": "Página/12",
            "seccion": "El País",
            "volanta": None,
            "subtitulo": "Una bajada",
            "autoria": ["Ana Pérez", "Luis Gómez"],
            "agencia": None,
            "epigrafe": "Una imagen.",
            "idioma": "es-AR",
        },
    )
    return db


def test_metadata_export_is_long_form_and_keeps_absences(tmp_path) -> None:
    db = _build_db(tmp_path)
    output = tmp_path / "metadata_genero.csv"

    count = export_metadata_genero_csv(db, output)

    with output.open(encoding="utf-8", newline="") as file:
        rows = list(csv.DictReader(file))

    assert count == 8
    assert len(rows) == 8
    assert {row["genero"] for row in rows} == {"articulo_periodistico"}
    assert [row["campo"] for row in rows][:3] == [
        "medio",
        "seccion",
        "volanta",
    ]

    volanta = next(row for row in rows if row["campo"] == "volanta")
    assert volanta["etiqueta"] == "Volanta"
    assert volanta["valor"] == ""
    assert volanta["presente"] == "0"

    autoria = next(row for row in rows if row["campo"] == "autoria")
    assert json.loads(autoria["valor"]) == ["Ana Pérez", "Luis Gómez"]
    assert autoria["presente"] == "1"
    db.close_thread_connection()


def test_discourse_export_serializes_input_containers_as_json(tmp_path) -> None:
    db = _build_db(tmp_path)
    output = tmp_path / "discursos.csv"

    assert export_discursos_csv(db, output) == 1

    with output.open(encoding="utf-8", newline="") as file:
        row = next(csv.DictReader(file))
    assert json.loads(row["input__autoria"]) == ["Ana Pérez", "Luis Gómez"]
    db.close_thread_connection()


def test_full_export_adds_metadata_file_and_count(tmp_path) -> None:
    db = _build_db(tmp_path)
    output_dir = tmp_path / "export"

    counts = export_full_run(db, output_dir)

    assert counts["metadata_genero"] == 8
    assert (output_dir / "metadata_genero.csv").is_file()
    assert set(counts) == {
        "discursos",
        "metadata_genero",
        "frases",
        "emociones",
    }
    db.close_thread_connection()


def test_old_run_exports_header_without_guessing_genre(tmp_path) -> None:
    db = _build_db(tmp_path, with_presentation=False)
    output = tmp_path / "metadata_genero.csv"

    assert export_metadata_genero_csv(db, output) == 0

    with output.open(encoding="utf-8", newline="") as file:
        rows = list(csv.DictReader(file))
    assert rows == []
    db.close_thread_connection()


def test_resume_adds_snapshot_without_overwriting_user_config(tmp_path) -> None:
    db = _build_db(tmp_path, with_presentation=False)
    repo = RunsRepository(db)
    repo.bootstrap(
        RunContext(
            run_id="run_metadata",
            started_at=datetime.now(timezone.utc),
            config=attach_genre_presentation(
                {"pipeline": {"parallel": 99}},
                get_genre(),
            ),
        )
    )

    run = repo.get_run()

    assert run is not None
    assert run.config["pipeline"] == {"parallel": 1}
    assert run.config["_emoparse"]["genre"]["genre_id"] == (
        "articulo_periodistico"
    )
    db.close_thread_connection()
