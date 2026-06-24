# ══════════════════════════════════════════════════════════════════════════════
#  emoparse.core.prompts.semas
#
#  Wrapper Jinja2. Firma pública estable.
# ══════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

from emoparse.core.prompts._loader import render


def render_system(
    vocabulario: str,
    titulo: str = "",
    tipo_discurso: str = "",
) -> str:
    """SYSTEM del asignador de semas. `vocabulario` inyecta el vocabulario curado."""
    return render(
        "semas_system",
        vocabulario=vocabulario,
        titulo=titulo or "no identificado",
        tipo_discurso=tipo_discurso or "no identificado",
    )


def render_user(referentes_block: str) -> str:
    """USER del asignador: los referentes a analizar."""
    return render("semas_user", referentes=referentes_block)
