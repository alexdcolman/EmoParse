# ══════════════════════════════════════════════════════════════════════════════
#  emoparse.knowledge.normalization
#
#  Helper compartido para normalización y lookup de emociones canónicas.
#  Usado por V11_DesviacionOntologica y NormalizeEmotionsStage.
# ══════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

import unicodedata
from typing import Any


def strip_accents(s: str) -> str:
    """Elimina tildes para comparación tolerante."""
    return "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn")


def format_emotion_ontology_for_prompt(ontology: dict[str, Any]) -> str:
    """Formatea el vocabulario emocional cerrado para el prompt.

    Incluye cada nombre canónico y sus aliases. Las dimensiones de
    caracterización permanecen en la ontología cruda para validación y no se
    duplican en el prompt de detección.
    """
    emociones = ontology.get("emociones", {})
    if not isinstance(emociones, dict):
        return ""

    lines: list[str] = []
    for canonical, entry in emociones.items():
        if not isinstance(entry, dict):
            continue
        aliases = [
            alias.strip()
            for alias in entry.get("aliases", [])
            if isinstance(alias, str) and alias.strip()
        ]
        line = f"- {canonical}"
        if aliases:
            line += f" (aliases: {', '.join(aliases)})"
        lines.append(line)
    return "\n".join(lines)


def build_emotion_alias_lookup(
    ontology: dict[str, Any],
    *,
    normalize_accents: bool = False,
) -> dict[str, str]:
    """Construye {alias_normalizado: canonical_id} desde la ontología.

    Normalización base: lowercase + strip.
    Con ``normalize_accents=True`` también elimina tildes.
    El nombre canónico tiene prioridad sobre aliases mediante setdefault.
    """

    def _norm(s: str) -> str:
        t = s.strip().lower()
        return strip_accents(t) if normalize_accents else t

    lookup: dict[str, str] = {}
    emociones = ontology.get("emociones", {})
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
