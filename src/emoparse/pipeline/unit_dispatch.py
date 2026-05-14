# ══════════════════════════════════════════════════════════════════════════════
#  emoparse.pipeline.unit_dispatch
#
#  Dispatch del chunker según genre.unit.
# ══════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

from emoparse.genres.base import ChunkUnit
from emoparse.pipeline.chunking import split_into_sentences


def split_into_paragraphs(
    text: str,
    *,
    min_chars: int = 30,
) -> list[str]:
    """Split por dobles newlines, descarta resultados muy cortos."""
    if not text or not text.strip():
        return []

    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
    if not paragraphs:
        return [text.strip()]

    filtered = [p for p in paragraphs if len(p) >= min_chars]
    if not filtered:
        return [paragraphs[0]]
    return filtered


def split_for(text: str, unit: ChunkUnit) -> list[str]:
    """Devuelve unidades textuales según unit."""
    if unit == "frase":
        return split_into_sentences(text)
    if unit == "parrafo":
        return split_into_paragraphs(text)
    if unit == "documento":
        stripped = text.strip()
        return [stripped] if stripped else []
    raise ValueError(
        f"unit desconocido: {unit!r}. Esperaba frase|parrafo|documento."
    )
