# ══════════════════════════════════════════════════════════════════════════════
#  emoparse.core.prompts.characterizer
#
#  Wrapper Jinja2. Firma pública estable.
# ══════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

from emoparse.core.prompts._loader import render


def render_system(
    titulo: str,
    tipo_discurso: str,
    heuristicas: str | None = None,
) -> str:
    """SYSTEM del characterizer con contexto del discurso."""
    return render(
        "characterizer_system",
        titulo=titulo,
        tipo_discurso=tipo_discurso,
        heuristicas=heuristicas,
    )


def render_user(unidades_block: str) -> str:
    """USER del characterizer: emociones a caracterizar, numeradas."""
    return render("characterizer_user", unidades=unidades_block)
