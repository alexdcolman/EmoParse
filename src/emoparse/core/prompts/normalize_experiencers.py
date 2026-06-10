# ══════════════════════════════════════════════════════════════════════════════
# emoparse.core.prompts.normalize_experiencers
#
# Wrappers tipados para renderizar los prompts del NormalizeExperiencersAgent.
# ══════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

from emoparse.core.prompts._loader import render


def render_system() -> str:
    """System prompt de NormalizeExperiencersAgent."""
    return render("normalize_experiencers_system")


def render_user(unidades_block: str) -> str:
    """User prompt con el bloque de discursos y sus experienciadores."""
    return render("normalize_experiencers_user", unidades=unidades_block)
