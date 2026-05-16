# ══════════════════════════════════════════════════════════════════════════════
#  emoparse.core.prompts.emotions
#
#  Wrapper tipado del template emotions_system.jinja2 + emotions_user.jinja2.
# ══════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

from emoparse.core.prompts._loader import render


def render_system(
    ontologia: str,
    heuristicas: str,
    configuraciones: str,
    titulo: str,
    tipo_discurso: str,
    enunciador: str,
) -> str:
    """Renderiza el system prompt de EmotionsAgent.

    Args:
        ontologia: Texto formateado de la ontología de emociones.
        heuristicas: Texto con heurísticas de inferencia para el agente.
        configuraciones: Texto con ocho tipos de configuraciones de
            simulacro emocional.
        titulo: Título del discurso.
        tipo_discurso: Clasificación del discurso.
        enunciador: Identificación del enunciador.
    """
    return render(
        "emotions_system",
        ontologia=ontologia,
        heuristicas=heuristicas,
        configuraciones=configuraciones,
        titulo=titulo,
        tipo_discurso=tipo_discurso,
        enunciador=enunciador,
    )


def render_user(unidades_block: str) -> str:
    """Renderiza el user prompt de EmotionsAgent."""
    return render("emotions_user", unidades=unidades_block)
