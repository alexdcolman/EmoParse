# ══════════════════════════════════════════════════════════════════════════════
#  emoparse.knowledge.normalization
#
#  Helpers del catálogo de normalización emocional ex post.
#  Nunca se usan para construir prompts ni para cerrar la detección del LLM.
# ══════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

import unicodedata
from typing import Any


def strip_accents(s: str) -> str:
    """Elimina tildes para comparación tolerante."""
    return "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn")


def build_emotion_normalization_lookup(
    catalog: dict[str, Any],
    *,
    normalize_accents: bool = False,
) -> dict[str, str]:
    """Construye {alias_normalizado: canonical_id} desde el catálogo ex post.

    Normalización base: lowercase + strip.
    Con ``normalize_accents=True`` también elimina tildes.
    El nombre canónico tiene prioridad sobre aliases mediante setdefault.
    """

    def _norm(s: str) -> str:
        t = s.strip().lower()
        return strip_accents(t) if normalize_accents else t

    lookup: dict[str, str] = {}
    emociones = catalog.get("emociones", {})
    if not isinstance(emociones, dict):
        return lookup
    for canonical, entry in emociones.items():
        if not isinstance(entry, dict):
            continue
        lookup.setdefault(_norm(canonical), canonical)
        for alias in entry.get("aliases", []):
            if isinstance(alias, str):
                lookup.setdefault(_norm(alias), canonical)
    return lookup
