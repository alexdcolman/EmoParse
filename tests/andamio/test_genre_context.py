from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from emoparse.genres.articulo_periodistico import get_genre
from emoparse.genres.base import Genre, GenreContextBlock
from emoparse.pipeline.genre_context import (
    GenreContextProvider,
    estimate_tokens,
    truncate_to_token_budget,
)


def _article_payload(**overrides):
    payload = {
        "medio": "Página/12",
        "idioma": "es-AR",
        "seccion": "El País",
        "volanta": None,
        "subtitulo": "Una bajada informativa",
        "autoria": ["Ana Pérez", "Luis Gómez"],
        "agencia": None,
        "epigrafe": "Manifestantes frente al Congreso.",
    }
    payload.update(overrides)
    return payload


def test_article_declares_context_for_four_analysis_stages() -> None:
    genre = get_genre()

    assert len(genre.context_blocks) == 1
    block = genre.context_blocks[0]
    assert block.name == "contexto_editorial"
    assert set(block.stage_token_budgets) == {
        "summarizer",
        "metadata",
        "enunciation",
        "emotions",
    }
    assert all(value > 0 for value in block.stage_token_budgets.values())


def test_provider_renders_declared_fields_and_omits_empty_values() -> None:
    provider = GenreContextProvider(get_genre())

    rendered = provider.render("metadata", _article_payload())

    assert rendered is not None
    assert "Contexto editorial del artículo" in rendered
    assert "- Medio: Página/12" in rendered
    assert "- Autoría: Ana Pérez; Luis Gómez" in rendered
    assert "Volanta" not in rendered
    assert "Agencia" not in rendered


def test_provider_returns_none_for_stage_without_declared_block() -> None:
    provider = GenreContextProvider(get_genre())

    assert provider.render("actors", _article_payload()) is None


def test_each_stage_respects_its_declared_budget() -> None:
    genre = get_genre()
    provider = GenreContextProvider(genre)
    long_caption = "epígrafe " * 500

    for stage, budget in genre.context_blocks[0].stage_token_budgets.items():
        rendered = provider.render(stage, _article_payload(epigrafe=long_caption))
        assert rendered is not None
        assert estimate_tokens(rendered) <= budget
        assert rendered.endswith("…")


def test_truncation_preserves_short_text() -> None:
    text = "Contexto breve"

    assert truncate_to_token_budget(text, budget=20) == text


class PaperMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    disciplina: str | None = None
    tipo_articulo: str | None = None
    seccion_paper: str | None = None


def test_generic_provider_accepts_a_fourth_genre_without_core_branch() -> None:
    genre = Genre(
        genre_id="articulo_cientifico_prueba",
        display_name="Artículo científico de prueba",
        input_metadata_model=PaperMetadata,
        input_metadata_display={
            "disciplina": "Disciplina",
            "tipo_articulo": "Tipo de artículo",
            "seccion_paper": "Sección del paper",
        },
        context_blocks=(
            GenreContextBlock(
                name="contexto_academico",
                title="Contexto académico",
                fields=("disciplina", "tipo_articulo", "seccion_paper"),
                stage_token_budgets={"metadata": 80},
            ),
        ),
        enunciation_roles=("lector_especializado",),
    )

    rendered = GenreContextProvider(genre).render(
        "metadata",
        {
            "disciplina": "Lingüística",
            "tipo_articulo": "artículo de investigación",
            "seccion_paper": "Resultados",
        },
    )

    assert rendered == (
        "Contexto académico:\n"
        "- Disciplina: Lingüística\n"
        "- Tipo de artículo: artículo de investigación\n"
        "- Sección del paper: Resultados"
    )
