from __future__ import annotations

import pandas as pd

from emoparse.agents.enunciation import EnunciationAgent, EnunciatorIdAgent
from emoparse.agents.metadata import MetadataAgent
from emoparse.agents.summarizer import SummarizerAgent
from emoparse.core.prompts import emotions as emotions_prompts
from emoparse.core.prompts import summarizer as summarizer_prompts
from emoparse.genres.articulo_periodistico import get_genre
from emoparse.pipeline.genre_context import GenreContextProvider
from emoparse.pipeline.stages import (
    EnunciationStage,
    MetadataStage,
    SummarizerStage,
)


class _DiscursosRepo:
    def __init__(self, payload: dict[str, object]) -> None:
        self.payload = payload

    def get_input(self, codigo: str):
        return dict(self.payload)

    def get_payload(self, codigo: str, stage: str):
        return None


ARTICLE_INPUT = {
    "contenido": "Primer párrafo.\n\nSegundo párrafo.",
    "titulo": "Una noticia de prueba",
    "fecha": "2026-08-02",
    "medio": "Página/12",
    "idioma": "es-AR",
    "seccion": "El País",
    "volanta": None,
    "subtitulo": "Una bajada informativa",
    "autoria": ["Ana Pérez"],
    "agencia": None,
    "epigrafe": "Una imagen de archivo.",
}


def test_discourse_stages_inject_same_generic_context_column() -> None:
    genre = get_genre()
    provider = GenreContextProvider(genre)
    repo = _DiscursosRepo(ARTICLE_INPUT)

    summarizer = SummarizerStage(
        agent=object(),
        discursos_repo=repo,  # type: ignore[arg-type]
        genre_context_provider=provider,
    )
    metadata = MetadataStage(
        agent=object(),
        discursos_repo=repo,  # type: ignore[arg-type]
        genre_context_provider=provider,
    )
    enunciation = EnunciationStage(
        agent=object(),
        discursos_repo=repo,  # type: ignore[arg-type]
        genre=genre,
        genre_context_provider=provider,
    )

    rows = {
        "summarizer": summarizer._prepare_row("art_1"),
        "metadata": metadata._prepare_row("art_1"),
        "enunciation": enunciation._prepare_row("art_1"),
    }

    for row in rows.values():
        assert row is not None
        assert "Contexto editorial del artículo" in row["contexto_genero"]
        assert "- Medio: Página/12" in row["contexto_genero"]


def test_summarizer_prompt_receives_genre_context() -> None:
    context = GenreContextProvider(get_genre()).render("summarizer", ARTICLE_INPUT)
    agent = SummarizerAgent(object())  # type: ignore[arg-type]

    prompt = agent._get_chunks(pd.Series(ARTICLE_INPUT))
    rendered = summarizer_prompts.render_user_fragmento(
        prompt[0],
        contexto_genero=context,
    )

    assert "CONTEXTO DE GÉNERO" in rendered
    assert "- Sección: El País" in rendered


def test_metadata_prompt_receives_genre_context_and_closed_types() -> None:
    genre = get_genre()
    context = GenreContextProvider(genre).render("metadata", ARTICLE_INPUT)
    agent = MetadataAgent(
        object(),  # type: ignore[arg-type]
        {"politico": "referencia que no debe usarse"},
        genre=genre,
    )
    row = pd.Series(
        {
            "codigo": "art_1",
            **ARTICLE_INPUT,
            "resumen_global": "Resumen de prueba.",
            "contexto_genero": context,
        }
    )

    user = agent._build_user(row)

    assert "CONTEXTO DE GÉNERO" in user
    assert "- Autoría: Ana Pérez" in user
    assert "TIPOS DE DISCURSO VÁLIDOS" in agent._system
    assert "- noticia:" in agent._system
    assert "discursos políticos" not in agent._system


def test_enunciation_main_and_id_prompts_receive_genre_context() -> None:
    genre = get_genre()
    context = GenreContextProvider(genre).render("enunciation", ARTICLE_INPUT)
    row = pd.Series(
        {
            "codigo": "art_1",
            **ARTICLE_INPUT,
            "resumen_global": "Resumen de prueba.",
            "contexto_genero": context,
            "tipo_discurso": "noticia",
        }
    )
    main = EnunciationAgent(object(), genre=genre)  # type: ignore[arg-type]
    identifier = EnunciatorIdAgent(object())  # type: ignore[arg-type]

    assert "- Autoría: Ana Pérez" in main._build_user(row)
    assert "- Autoría: Ana Pérez" in identifier._build_user(row)


def test_emotions_system_prompt_receives_genre_context() -> None:
    context = GenreContextProvider(get_genre()).render("emotions", ARTICLE_INPUT)

    rendered = emotions_prompts.render_system(
        ontologia="ontología",
        configuraciones="configuraciones",
        titulo="Una noticia de prueba",
        tipo_discurso="noticia",
        enunciador="Ana Pérez",
        contexto_genero=context or "",
    )

    assert "CONTEXTO DE GÉNERO" in rendered
    assert "- Medio: Página/12" in rendered
    assert "no es fuente autónoma" in rendered
