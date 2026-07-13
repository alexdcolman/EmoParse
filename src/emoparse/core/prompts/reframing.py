# ══════════════════════════════════════════════════════════════════════════════
#  emoparse.core.prompts.reframing
#
#  Wrapper Jinja2 de reframing_system + reframing_user.
# ══════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

from emoparse.core.prompts._loader import render


def render_system(heuristicas: str | None = None) -> str:
    """SYSTEM de reframing. `heuristicas` es opcional."""
    return render("reframing_system", heuristicas=heuristicas)


def render_user(unidades_block: str) -> str:
    """USER de reframing con los pares citador/citado del batch."""
    return render("reframing_user", unidades=unidades_block)
