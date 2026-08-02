from __future__ import annotations

import pytest

from emoparse.pipeline.context_blocks import ContextBlockProvider
from emoparse.pipeline.genre_context import estimate_tokens
from emoparse.pipeline.post_context import (
    combine_context_providers,
    make_hilo_context_provider,
)


def test_context_block_enforces_budget() -> None:
    block = ContextBlockProvider(
        name="bloque_prueba",
        target_column="contexto",
        stages=("metadata",),
        token_budget=12,
        scope="discurso",
        render_fn=lambda _codigo, _unit_idx: "palabra " * 100,
    )

    rendered = block("doc_1")

    assert rendered is not None
    assert estimate_tokens(rendered) <= 12
    assert rendered.endswith("…")


def test_unit_context_requires_unit_idx() -> None:
    block = ContextBlockProvider(
        name="unidad_prueba",
        target_column="tecno",
        stages=("emotions",),
        token_budget=20,
        scope="unidad",
        render_fn=lambda codigo, unit_idx: f"{codigo}:{unit_idx}",
    )

    with pytest.raises(TypeError, match="requiere unit_idx"):
        block("doc_1")

    assert block("doc_1", 3) == "doc_1:3"


class _PostsRepo:
    def __init__(self) -> None:
        self.posts = {
            "actual": {
                "post_id": "actual",
                "autor_handle": "actual",
                "texto": "respuesta actual",
                "en_respuesta_a": "padre",
                "conversacion_id": "raiz",
                "cita_a": None,
            },
            "padre": {
                "post_id": "padre",
                "autor_handle": "padre",
                "texto": "contexto inmediato " * 80,
                "en_respuesta_a": "raiz",
                "conversacion_id": "raiz",
                "cita_a": None,
            },
            "raiz": {
                "post_id": "raiz",
                "autor_handle": "raiz",
                "texto": "inicio remoto " * 80,
                "en_respuesta_a": None,
                "conversacion_id": "raiz",
                "cita_a": None,
            },
        }

    def get_post(self, codigo: str):
        return self.posts.get(codigo)

    def list_by_conversacion(self, _conv_id: str):
        return list(self.posts.values())


class _HilosRepo:
    def get_hilo(self, _conv_id: str):
        return {"n_posts": 3}


def test_hilo_factory_returns_named_block_and_keeps_nearest_context() -> None:
    block = make_hilo_context_provider(
        _PostsRepo(),  # type: ignore[arg-type]
        _HilosRepo(),  # type: ignore[arg-type]
        max_parents=2,
        max_chars=180,
    )

    rendered = block("actual")

    assert block.name == "contexto_hilo"
    assert block.target_column == "contexto_hilo"
    assert block.scope == "discurso"
    assert "metadata" in block.stages
    assert rendered is not None
    assert estimate_tokens(rendered) <= block.token_budget
    assert "contexto inmediato" in rendered


def test_combined_blocks_preserve_callable_interface() -> None:
    one = ContextBlockProvider(
        name="uno",
        target_column="media_desc",
        stages=("emotions",),
        token_budget=20,
        scope="discurso",
        render_fn=lambda _codigo, _unit_idx: "primero",
    )
    two = ContextBlockProvider(
        name="dos",
        target_column="media_desc",
        stages=("emotions_pass2",),
        token_budget=20,
        scope="discurso",
        render_fn=lambda _codigo, _unit_idx: "segundo",
    )

    combined = combine_context_providers(
        one,
        two,
        target_column="contexto_compuesto",
        name="uno_y_dos",
    )

    assert combined is not None
    assert combined("doc_1") == "primero\nsegundo"
    assert combined.name == "uno_y_dos"
    assert combined.target_column == "contexto_compuesto"
    assert combined.token_budget == 40
    assert set(combined.stages) == {"emotions", "emotions_pass2"}
