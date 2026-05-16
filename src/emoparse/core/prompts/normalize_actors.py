# ══════════════════════════════════════════════════════════════════════════════
#  emoparse.core.prompts.normalize_actors
#
#  Wrappers tipados para renderizar los prompts del NormalizeActorsAgent.
# ══════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

from emoparse.core.prompts._loader import render


def render_system(actors_kb: str) -> str:
    """Renderiza el system prompt con la KB serializada.

    Args:
        actors_kb: String con la KB ya formateada en formato compacto
            (`canonical_id: aliases`).
    """
    return render("normalize_actors_system", actors_kb=actors_kb)


def render_user(unidades_block: str) -> str:
    """Renderiza el user prompt con el bloque de unidades a linkear."""
    return render("normalize_actors_user", unidades_block=unidades_block)
