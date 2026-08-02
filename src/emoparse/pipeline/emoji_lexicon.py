# ══════════════════════════════════════════════════════════════════════════════
#  emoparse.pipeline.emoji_lexicon
#
#  Aplicación determinista del léxico afectivo de emojis.
#
#  El léxico (knowledge/emoji_afecto.json) asigna a cada emoji candidatos de
#  tipo de emoción y foria, y marca los ambiguos. Este módulo resuelve sin
#  LLM los usos inequívocos; los ambiguos o no cubiertos devuelven None y
#  quedan para la desambiguación en contexto (EmojiAffectStage → agente).
# ══════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

from typing import Any

#: Modificadores que no alteran el valor afectivo del emoji base: tonos de
#: piel (Fitzpatrick) y el selector de variación de presentación. El léxico
#: registra la forma base, así que 💪🏽 debe resolver por 💪 antes de gastar
#: una inferencia en desambiguarlo.
_MODIFICADORES = frozenset([chr(c) for c in range(0x1F3FB, 0x1F400)] + ["\ufe0f", "\ufe0e"])


def _base(emoji: str) -> str:
    """Emoji sin modificadores de tono ni selectores de variación."""
    return "".join(c for c in emoji if c not in _MODIFICADORES)


def resolve_emoji_afecto(
    lexicon: dict[str, Any],
    emoji: str,
) -> dict[str, Any] | None:
    """Resolución determinista de un emoji inequívoco del léxico.

    Args:
        lexicon: El mapa `emojis` del léxico (emoji → entrada con
            `candidatos`, `foria`, `ambiguo`).
        emoji: El emoji tal como aparece en el texto.

    Returns:
        El afecto resuelto ({candidato, foria, origin='lexico'}) si el
        léxico cubre el emoji (o su forma base, sin modificadores de tono),
        no lo marca ambiguo y le asigna foria; None si requiere
        desambiguación en contexto.
    """
    entry = lexicon.get(emoji)
    if not isinstance(entry, dict):
        # El léxico puede registrar la forma con selector de variación (❤️):
        # por eso la búsqueda exacta va primero y la base, después.
        entry = lexicon.get(_base(emoji))
    if not isinstance(entry, dict):
        return None
    if entry.get("ambiguo") or not entry.get("foria"):
        return None
    candidatos = entry.get("candidatos") or []
    if not candidatos:
        return None
    return {
        "candidato": str(candidatos[0]),
        "foria": str(entry["foria"]),
        "origin": "lexico",
    }
