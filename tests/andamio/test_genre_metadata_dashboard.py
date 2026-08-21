from __future__ import annotations

from datetime import UTC, datetime

from emoparse.app import data as data_layer
from emoparse.genres.articulo_periodistico import get_genre
from emoparse.genres.presentation import attach_genre_presentation
from emoparse.storage import Database, DiscursosRepository
from emoparse.storage.models import RunContext
from emoparse.storage.runs import RunsRepository


def _build_db(tmp_path):
    path = tmp_path / "run_dashboard.sqlite"
    db = Database(path)
    RunsRepository(db).bootstrap(
        RunContext(
            run_id="run_dashboard",
            started_at=datetime.now(UTC),
            config=attach_genre_presentation({}, get_genre()),
        )
    )
    DiscursosRepository(db).upsert_input(
        "art_1",
        {
            "titulo": "Nota de prueba",
            "fecha": "2026-08-02",
            "contenido": "Texto de prueba.",
            "medio": "Página/12",
            "seccion": "El País",
            "volanta": None,
            "subtitulo": "Una bajada",
            "autoria": ["Ana Pérez"],
            "agencia": None,
            "epigrafe": "Una imagen.",
            "idioma": "es-AR",
        },
    )
    db.close_thread_connection()
    return path


def test_header_exposes_only_present_declared_metadata(tmp_path) -> None:
    path = _build_db(tmp_path)

    header = data_layer.get_discurso_header(path, "art_1")

    assert header["genre_id"] == "articulo_periodistico"
    assert header["genre_display_name"] == "Artículo periodístico"
    assert [item["field"] for item in header["input_metadata"]] == [
        "medio",
        "seccion",
        "subtitulo",
        "autoria",
        "epigrafe",
        "idioma",
    ]
    assert all(item["field"] != "volanta" for item in header["input_metadata"])


def test_table_labels_are_derived_from_run_snapshot(tmp_path) -> None:
    path = _build_db(tmp_path)

    labels = data_layer.get_input_metadata_display(path)

    assert labels["input__medio"] == "Medio"
    assert labels["input__autoria"] == "Autoría"
    assert "input__contenido" not in labels


def test_run_stats_exposes_snapshot_genre_without_inferred_suffix(tmp_path) -> None:
    path = _build_db(tmp_path)

    stats = data_layer.get_run_stats(path)

    assert stats["genre_id"] == "articulo_periodistico"
    assert stats["genre_display_name"] == "Artículo periodístico"
    assert stats["genre_inferred"] is False
    assert data_layer.format_run_genre_label(stats) == "Artículo periodístico"


def test_run_stats_marks_legacy_inferred_genre(tmp_path) -> None:
    path = tmp_path / "run_dashboard_legacy.sqlite"
    db = Database(path)
    RunsRepository(db).bootstrap(
        RunContext(
            run_id="run_dashboard_legacy",
            started_at=datetime.now(UTC),
            config={},
        )
    )
    DiscursosRepository(db).upsert_input(
        "art_legacy",
        {
            "titulo": "Nota legacy",
            "contenido": "Texto de prueba.",
            "medio": "Página/12",
            "seccion": "El País",
        },
    )
    db.close_thread_connection()

    stats = data_layer.get_run_stats(path)

    assert stats["genre_id"] == "articulo_periodistico"
    assert stats["genre_inferred"] is True
    assert data_layer.format_run_genre_label(stats) == "articulo_periodistico (inferido)"
