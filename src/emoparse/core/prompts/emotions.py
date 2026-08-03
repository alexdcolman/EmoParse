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
    contexto_genero: str = "",
    modos_existencia: str = "",
    template: str = "emotions_system",
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
        heuristicas: Reglas de inferencia emocional, ya compuestas por el
            runner (base común más los agregados del género y del pase).
            El template las inyecta como bloque propio; si es cadena vacía,
            la sección se omite.
        resumen: Contexto global del discurso, no evidencia autónoma.
        contexto_genero: Metadata tipada declarada por el género, acotada
            por el presupuesto de la stage.
        modos_existencia: Texto formateado del catálogo de modos de existencia.
        template: Nombre del template Jinja2 del system prompt. Los géneros
            pueden sustituirlo vía `Genre.prompt_overrides` (p. ej.
            'emotions_system_tuit'). El template alternativo debe aceptar
            las mismas variables que el default.
    """
    return render(
        template,
        ontologia=ontologia,
        configuraciones=configuraciones,
        heuristicas=heuristicas,
        titulo=titulo,
        tipo_discurso=tipo_discurso,
        enunciador=enunciador,
        enunciatarios=enunciatarios,
        auditorio=auditorio,
        alcance=alcance,
        resumen=resumen,
        contexto_genero=contexto_genero,
        modos_existencia=modos_existencia,
    )


def render_user(unidades_block: str) -> str:
    """Renderiza el user prompt de EmotionsAgent."""
    return render("emotions_user", unidades=unidades_block)
