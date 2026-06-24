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
    enunciatarios: str = "",
    auditorio: str = "",
    alcance: str = "",
) -> str:
    """Renderiza el system prompt de EmotionsAgent.

    Args:
        ontologia: Texto formateado de la ontología de emociones.
        heuristicas: Texto con heurísticas de inferencia para el agente.
        configuraciones: Texto con las ocho configuraciones de simulacro
            emocional.
        titulo: Título del discurso.
        tipo_discurso: Clasificación del discurso.
        enunciador: Identificación del enunciador.
        enunciatarios: Enunciatarios del discurso, ya formateados como texto.
            Vacío si no se conocen.
        auditorio: Auditorio del discurso, ya formateado como texto. Vacío
            si no se conoce.
        alcance: Frase que restringe los experienciadores a analizar. Vacío
            para analizar emociones de cualquier actor.
    """
    return render(
        "emotions_system",
        ontologia=ontologia,
        heuristicas=heuristicas,
        configuraciones=configuraciones,
        titulo=titulo,
        tipo_discurso=tipo_discurso,
        enunciador=enunciador,
        enunciatarios=enunciatarios,
        auditorio=auditorio,
        alcance=alcance,
    )


def render_user(unidades_block: str) -> str:
    """Renderiza el user prompt de EmotionsAgent."""
    return render("emotions_user", unidades=unidades_block)
