# ══════════════════════════════════════════════════════════════════════════════
#  emoparse.core.prompts.tecno_usage
#
#  Wrapper Jinja2 de tecno_usage_system + tecno_usage_user.
# ══════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

from emoparse.core.prompts._loader import render


def render_system(heuristicas: str | None = None) -> str:
    """SYSTEM de tecno_usage. `heuristicas` es opcional."""
    return render("tecno_usage_system", heuristicas=heuristicas)


def render_user(unidades_block: str) -> str:
    """USER de tecno_usage con las unidades del batch."""
    return render("tecno_usage_user", unidades=unidades_block)
