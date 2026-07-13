# ══════════════════════════════════════════════════════════════════════════════
#  emoparse.core.prompts.emoji_affect
#
#  Wrapper Jinja2 de emoji_affect_system + emoji_affect_user.
# ══════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

from emoparse.core.prompts._loader import render


def render_system(heuristicas: str | None = None) -> str:
    """SYSTEM de emoji_affect. `heuristicas` es opcional."""
    return render("emoji_affect_system", heuristicas=heuristicas)


def render_user(unidades_block: str) -> str:
    """USER de emoji_affect con los usos del batch."""
    return render("emoji_affect_user", unidades=unidades_block)
