# ══════════════════════════════════════════════════════════════════════════════
#  emoparse.pipeline.context_blocks
#
#  Interfaz común para bloques de contexto dinámico del pipeline.
# ══════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

from emoparse.genres.base import StageName
from emoparse.pipeline.genre_context import (
    estimate_tokens,
    truncate_to_token_budget,
)


ContextScope = Literal["discurso", "unidad"]
ContextRender = Callable[[str, int | None], str | None]


@dataclass(frozen=True, slots=True)
class ContextBlockProvider:
    """Bloque dinámico, nombrado y acotado, listo para una o más stages.

    La interfaz uniforma providers respaldados por repositorios distintos sin
    borrar su especialización. Un bloque declara el nombre estable, la columna
    interna en la que se inyecta, el alcance de lectura y un presupuesto
    aproximado de tokens. El objeto es callable para conservar la interfaz que
    ya consumen las stages.
    """

    name: str
    target_column: str
    stages: tuple[StageName, ...]
    token_budget: int
    scope: ContextScope
    render_fn: ContextRender
    keep_tail: bool = False

    def __post_init__(self) -> None:
        if not self.name or not self.name.replace("_", "").isalnum():
            raise ValueError("name debe ser un identificador estable")
        if not self.target_column:
            raise ValueError("target_column no puede estar vacío")
        if not self.stages:
            raise ValueError("stages no puede estar vacío")
        if self.token_budget < 1:
            raise ValueError("token_budget debe ser mayor que cero")

    def render(
        self,
        codigo: str,
        unit_idx: int | None = None,
    ) -> str | None:
        """Renderiza y recorta el bloque para un discurso o una unidad."""
        if self.scope == "unidad" and unit_idx is None:
            raise TypeError(
                f"El bloque '{self.name}' requiere unit_idx porque su alcance "
                "es por unidad"
            )

        text = self.render_fn(codigo, unit_idx)
        if not text:
            return None
        text = str(text).strip()
        if not text:
            return None
        if estimate_tokens(text) <= self.token_budget:
            return text
        if self.keep_tail:
            return _truncate_tail(text, budget=self.token_budget)
        return truncate_to_token_budget(text, budget=self.token_budget)

    def __call__(
        self,
        codigo: str,
        unit_idx: int | None = None,
    ) -> str | None:
        """Compatibilidad callable con los providers históricos."""
        return self.render(codigo, unit_idx)


def _truncate_tail(text: str, *, budget: int) -> str:
    """Recorta desde el inicio y conserva el final más próximo a la unidad."""
    max_chars = budget * 3
    prefix = "(...)\n"
    if max_chars <= len(prefix) + 1:
        return "…"
    body = text[-(max_chars - len(prefix)):].lstrip()
    clipped = prefix + body
    while estimate_tokens(clipped) > budget and body:
        body = body[1:].lstrip()
        clipped = prefix + body
    return clipped or "…"


__all__ = [
    "ContextBlockProvider",
    "ContextRender",
    "ContextScope",
]
