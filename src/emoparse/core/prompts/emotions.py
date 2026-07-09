# ══════════════════════════════════════════════════════════════════════════════
#  emoparse.core.prompts.emotions
#
#  Wrapper tipado del template emotions_system.jinja2 + emotions_user.jinja2.
# ══════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

from emoparse.core.prompts._loader import render


def render_system(
    ontologia: str,
    configuraciones: str,
    titulo: str,
    tipo_discurso: str,
    enunciador: str,
    enunciatarios: str = "",
    auditorio: str = "",
    alcance: str = "",
    heuristicas: str = "",
    resumen: str = "",
) -> str:
    """Renderiza el system prompt de EmotionsAgent.

    Args:
        ontologia: Texto formateado de la ontología de emociones.
        configuraciones: Texto con las ocho configuraciones de simulacro
            emocional, ya fusionadas con sus heurísticas de detección y
            ejemplos (ver KnowledgeLoader.load_emotion_configurations).
        titulo: Título del discurso.
        tipo_discurso: Clasificación del discurso.
        enunciador: Identificación del enunciador.
        enunciatarios: Enunciatarios del discurso, ya formateados como texto.
            Vacío si no se conocen.
        auditorio: Auditorio del discurso, ya formateado como texto. Vacío
            si no se conoce.
        alcance: Frase que restringe los experienciadores a analizar. Vacío
            para analizar emociones de cualquier actor.
        heuristicas: Deprecado. El template ya no lo usa: las heurísticas
            de inferencia quedaron fusionadas dentro de `configuraciones`
            para evitar la duplicación de las 8 categorías en el prompt.
            Se mantiene el parámetro solo por compatibilidad con callers
            existentes; cualquier valor pasado acá se ignora.
    """
    return render(
        "emotions_system",
        ontologia=ontologia,
        configuraciones=configuraciones,
        titulo=titulo,
        tipo_discurso=tipo_discurso,
        enunciador=enunciador,
        enunciatarios=enunciatarios,
        auditorio=auditorio,
        alcance=alcance,
        resumen=resumen,
    )


def render_user(unidades_block: str) -> str:
    """Renderiza el user prompt de EmotionsAgent."""
    return render("emotions_user", unidades=unidades_block)
