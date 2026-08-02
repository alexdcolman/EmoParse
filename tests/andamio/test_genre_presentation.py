from __future__ import annotations

from emoparse.genres.articulo_periodistico import get_genre
from emoparse.genres.presentation import (
    RUNTIME_CONFIG_KEY,
    attach_genre_presentation,
    metadata_is_present,
    presentation_from_config,
    presentation_from_genre,
    presented_metadata,
)


def test_presentation_uses_declared_order_and_labels() -> None:
    presentation = presentation_from_genre(get_genre())

    assert presentation.genre_id == "articulo_periodistico"
    assert presentation.display_name == "Artículo periodístico"
    assert [field.name for field in presentation.input_metadata] == [
        "medio",
        "seccion",
        "volanta",
        "subtitulo",
        "autoria",
        "agencia",
        "epigrafe",
        "idioma",
    ]
    assert presentation.input_metadata[0].label == "Medio"


def test_snapshot_roundtrip_preserves_user_config() -> None:
    original = {"pipeline": {"parallel": 1}}

    stored = attach_genre_presentation(original, get_genre())
    restored = presentation_from_config(stored)

    assert original == {"pipeline": {"parallel": 1}}
    assert stored["pipeline"] == original["pipeline"]
    assert RUNTIME_CONFIG_KEY in stored
    assert restored == presentation_from_genre(get_genre())


def test_presented_metadata_omits_missing_values_in_dashboard_mode() -> None:
    presentation = presentation_from_genre(get_genre())

    records = presented_metadata(
        presentation,
        {
            "medio": "Página/12",
            "seccion": "El País",
            "volanta": None,
            "autoria": ["Ana Pérez", "Luis Gómez"],
            "agencia": "",
        },
    )

    assert [record["field"] for record in records] == [
        "medio",
        "seccion",
        "autoria",
    ]
    assert records[-1]["value"] == ["Ana Pérez", "Luis Gómez"]


def test_presented_metadata_keeps_missing_values_for_coverage_exports() -> None:
    presentation = presentation_from_genre(get_genre())

    records = presented_metadata(
        presentation,
        {"medio": "Página/12", "volanta": None},
        include_missing=True,
    )

    assert len(records) == len(presentation.input_metadata)
    volanta = next(record for record in records if record["field"] == "volanta")
    assert volanta["present"] is False
    assert volanta["value"] is None


def test_presence_handles_empty_containers_and_nan() -> None:
    assert metadata_is_present("dato") is True
    assert metadata_is_present(["dato"]) is True
    assert metadata_is_present(0) is True
    assert metadata_is_present("") is False
    assert metadata_is_present([]) is False
    assert metadata_is_present(float("nan")) is False


def test_malformed_or_old_config_has_no_presentation() -> None:
    assert presentation_from_config(None) is None
    assert presentation_from_config({}) is None
    assert presentation_from_config({RUNTIME_CONFIG_KEY: {"genre": {}}}) is None
