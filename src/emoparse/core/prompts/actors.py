# ══════════════════════════════════════════════════════════════════════════════
#  emoparse.core.prompts.actors
#
#  Wrapper Jinja2. Firma pública estable.
# ══════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

from emoparse.core.prompts._loader import render


def render_system(titulo: str, tipo_discurso: str, enunciador: str) -> str:
    """SYSTEM de actors con contexto del discurso."""
    return render(
        "actors_system",
        titulo=titulo,
        tipo_discurso=tipo_discurso,
        enunciador=enunciador,
    )


def render_user(unidades_block: str) -> str:
    """USER de actors con las unidades numeradas del batch."""
    return render("actors_user", unidades=unidades_block)
