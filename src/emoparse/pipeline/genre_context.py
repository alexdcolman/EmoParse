# ══════════════════════════════════════════════════════════════════════════════
#  emoparse.pipeline.genre_context
#
#  Composición genérica de contexto declarado por cada género.
# ══════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

import json
import math
from collections.abc import Mapping, Sequence
from typing import Any

from pydantic import BaseModel, ValidationError

from emoparse.genres.base import Genre, GenreContextBlock, StageName

#: Aproximación conservadora e independiente del tokenizer. En español, usar
#: tres caracteres por token evita que el presupuesto declarado subestime de
#: forma sistemática el costo de palabras, signos y acentos.
_CHARS_PER_TOKEN = 3


class GenreContextError(ValueError):
    """La metadata persistida no cumple el contrato declarado por el género."""


class GenreContextProvider:
    """Renderiza bloques de metadata para una stage concreta.

    El provider solo conoce el descriptor :class:`Genre` y el payload de input.
    No contiene ramas por ``genre_id``: cada plugin declara campos, etiquetas y
    presupuestos en ``Genre.context_blocks``.
    """

    def __init__(self, genre: Genre) -> None:
        self._genre = genre

    def render(
        self,
        stage: StageName,
        input_payload: Mapping[str, Any],
    ) -> str | None:
        """Devuelve los bloques habilitados para ``stage``, o ``None``.

        La metadata se revalida al leerla desde la base para detectar runs
        antiguos o payloads modificados fuera de la ingesta normal. Cada bloque
        se recorta con su presupuesto antes de concatenarlo.
        """
        blocks = tuple(
            block for block in self._genre.context_blocks if stage in block.stage_token_budgets
        )
        if not blocks:
            return None

        metadata = self._validate_metadata(input_payload)
        rendered = [
            text for block in blocks if (text := self._render_block(block, metadata, stage))
        ]
        return "\n\n".join(rendered) or None

    def _validate_metadata(self, input_payload: Mapping[str, Any]) -> BaseModel:
        model = self._genre.input_metadata_model
        if model is None:
            raise GenreContextError(
                f"El género '{self._genre.genre_id}' declara contexto sin input_metadata_model"
            )
        payload = {field: input_payload.get(field) for field in model.model_fields}
        try:
            return model.model_validate(payload)
        except ValidationError as exc:
            raise GenreContextError(
                f"Metadata inválida para el género '{self._genre.genre_id}': {exc}"
            ) from exc

    def _render_block(
        self,
        block: GenreContextBlock,
        metadata: BaseModel,
        stage: StageName,
    ) -> str | None:
        lines: list[str] = []
        labels = self._genre.input_metadata_display

        for field in block.fields:
            value = _format_value(getattr(metadata, field, None))
            if value:
                lines.append(f"- {labels[field]}: {value}")

        if not lines:
            return None

        text = f"{block.title}:\n" + "\n".join(lines)
        return truncate_to_token_budget(
            text,
            budget=block.stage_token_budgets[stage],
        )


def render_genre_context(
    genre: Genre | None,
    stage: StageName,
    input_payload: Mapping[str, Any],
) -> str | None:
    """Atajo funcional para callers que no necesitan conservar el provider."""
    if genre is None or not genre.context_blocks:
        return None
    return GenreContextProvider(genre).render(stage, input_payload)


def estimate_tokens(text: str) -> int:
    """Estima tokens con una cota conservadora independiente del backend."""
    if not text:
        return 0
    return math.ceil(len(text) / _CHARS_PER_TOKEN)


def truncate_to_token_budget(text: str, *, budget: int) -> str:
    """Recorta ``text`` al presupuesto aproximado, preservando palabras."""
    if budget < 1:
        raise ValueError("budget debe ser mayor que cero")
    if estimate_tokens(text) <= budget:
        return text

    max_chars = budget * _CHARS_PER_TOKEN
    if max_chars <= 1:
        return "…"

    clipped = text[: max_chars - 1].rstrip()
    # Evitar cortar una palabra cuando hay un separador razonablemente cerca.
    boundary = max(clipped.rfind("\n"), clipped.rfind(" "))
    if boundary >= max_chars // 2:
        clipped = clipped[:boundary].rstrip()
    return clipped + "…"


def _format_value(value: Any) -> str:
    """Formatea un valor tipado de metadata de manera compacta."""
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, BaseModel):
        return json.dumps(
            value.model_dump(mode="json"),
            ensure_ascii=False,
            separators=(",", ":"),
        )
    if isinstance(value, Mapping):
        if not value:
            return ""
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    if isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray)):
        parts = [
            rendered for item in value if item is not None and (rendered := _format_value(item))
        ]
        return "; ".join(parts)
    return str(value).strip()


__all__ = [
    "GenreContextError",
    "GenreContextProvider",
    "estimate_tokens",
    "render_genre_context",
    "truncate_to_token_budget",
]
