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
        léxico cubre el emoji, no lo marca ambiguo y le asigna foria;
        None si requiere desambiguación en contexto.
    """
    entry = lexicon.get(emoji)
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
