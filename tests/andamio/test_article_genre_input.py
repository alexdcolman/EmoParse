from __future__ import annotations

import json
import tomllib
from pathlib import Path

from emoparse.genres.articulo_periodistico import (
    ArticuloPeriodisticoMetadata,
    get_genre,
)
from emoparse.inputs.loader import load_discursos


def test_article_genre_declares_paragraph_unit_and_charaudeau_roles() -> None:
    genre = get_genre()

    assert genre.genre_id == "articulo_periodistico"
    assert genre.unit == "parrafo"
    assert genre.input_metadata_model is ArticuloPeriodisticoMetadata
    assert genre.enunciation_roles == (
        "lector_ciudadano",
        "instancia_blanco",
        "fuente_referente",
    )
    assert set(genre.input_metadata_display) == set(
        ArticuloPeriodisticoMetadata.model_fields
    )


def test_loader_validates_and_normalizes_article_metadata(tmp_path) -> None:
    path = tmp_path / "piloto_articulos_fuente_20260802.csv"
    path.write_text(
        "codigo,contenido,seccion,autoria,agencia,medio,idioma\n"
        'art_1,"Primer párrafo.\\n\\nSegundo párrafo.",El País,'
        '"[""Ana Pérez"", ""Luis Gómez""]",,Página/12,es-AR\n',
        encoding="utf-8",
    )

    df = load_discursos(path, genre=get_genre())

    assert df.loc[0, "autoria"] == ("Ana Pérez", "Luis Gómez")
    assert df.loc[0, "agencia"] is None
    assert df.loc[0, "volanta"] is None
    assert df.loc[0, "seccion"] == "El País"
    assert set(ArticuloPeriodisticoMetadata.model_fields).issubset(df.columns)


def test_article_genre_is_declared_as_builtin_entry_point() -> None:
    root = Path(__file__).resolve().parents[2]
    with (root / "pyproject.toml").open("rb") as file:
        project = tomllib.load(file)

    entry_points = project["project"]["entry-points"]["emoparse.genres"]
    assert entry_points["articulo_periodistico"] == (
        "emoparse.genres.articulo_periodistico:get_genre"
    )


def test_authorship_accepts_json_and_explicit_delimiters() -> None:
    from_json = ArticuloPeriodisticoMetadata(
        autoria=json.dumps(["Ana Pérez", "Luis Gómez"])
    )
    from_text = ArticuloPeriodisticoMetadata(autoria="Ana Pérez; Luis Gómez")

    expected = ("Ana Pérez", "Luis Gómez")
    assert from_json.autoria == expected
    assert from_text.autoria == expected


def test_validated_article_metadata_is_preserved_in_discourse_input(tmp_path) -> None:
    from emoparse.storage import Database, DiscursosRepository
    from emoparse.storage.schema import CREATE_DISCURSOS

    input_path = tmp_path / "piloto_articulos_fuente_20260802.csv"
    input_path.write_text(
        "codigo,contenido,seccion,autoria,medio,idioma\n"
        'art_1,"Primer párrafo.\\n\\nSegundo párrafo.",El País,'
        '"[""Ana Pérez""]",Página/12,es-AR\n',
        encoding="utf-8",
    )
    frame = load_discursos(input_path, genre=get_genre())

    db = Database(tmp_path / "run.sqlite")
    db.execute(CREATE_DISCURSOS)
    repo = DiscursosRepository(db)
    row = frame.iloc[0].to_dict()
    repo.upsert_input("art_1", {key: value for key, value in row.items() if key != "codigo"})

    persisted = repo.get_input("art_1")

    assert persisted is not None
    assert persisted["seccion"] == "El País"
    assert persisted["autoria"] == ["Ana Pérez"]
    assert persisted["medio"] == "Página/12"
    assert persisted["volanta"] is None
    db.close_thread_connection()
