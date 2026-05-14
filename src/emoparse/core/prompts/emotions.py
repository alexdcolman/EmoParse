# ══════════════════════════════════════════════════════════════════════════════
#  emoparse.core.prompts.emotions
#
#  Wrapper Jinja2. Firma pública estable.
# ══════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

from emoparse.core.prompts._loader import render


def render_system(
    ontologia: str,
    heuristicas: str,
    titulo: str,
    tipo_discurso: str,
    enunciador: str,
) -> str:
    """SYSTEM del pase 1 de emotions con ontología, heurísticas y contexto."""
    return render(
        "emotions_system",
        ontologia=ontologia,
        heuristicas=heuristicas,
        titulo=titulo,
        tipo_discurso=tipo_discurso,
        enunciador=enunciador,
    )


def render_user(unidades_block: str) -> str:
    """USER del pase 1 de emotions."""
    return render("emotions_user", unidades=unidades_block)
