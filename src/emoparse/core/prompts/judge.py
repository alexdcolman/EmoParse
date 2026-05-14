# ══════════════════════════════════════════════════════════════════════════════
#  emoparse.core.prompts.judge
#
#  Wrapper Jinja2. Firma pública estable.
# ══════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

from emoparse.core.prompts._loader import render


def render_system(titulo: str, tipo_discurso: str) -> str:
    """SYSTEM del juez.
    
    Si titulo/tipo_discurso vienen vacíos, los reemplaza por la convención
    del proyecto ('no identificado').
    """
    return render(
        "judge_system",
        titulo=titulo or "no identificado",
        tipo_discurso=tipo_discurso or "no identificado",
    )


def render_user(unidades_block: str) -> str:
    """USER del juez: las caracterizaciones a juzgar."""
    return render("judge_user", unidades_block=unidades_block)
