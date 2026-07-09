# ══════════════════════════════════════════════════════════════════════════════
#  emoparse.core.prompts.emotions_pass2
#
#  Wrapper Jinja2. Firma pública estable.
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
    """SYSTEM del pase 2.

    Incluye instrucciones de uso del rolling/full summary, reglas
    anti-alucinación y las ocho configuraciones de simulacro emocional
    (ya fusionadas con sus heurísticas de detección y ejemplos). El
    parámetro `alcance` restringe los experienciadores a analizar, con la
    misma semántica que en el pase 1.

    `heuristicas` es deprecado: se mantiene por compatibilidad pero el
    template ya no lo referencia, así que cualquier valor pasado se ignora.
    """
    return render(
        "emotions_pass2_system",
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
    """USER del pase 2.

    Cada unidad ya viene con su CONTEXTO ANTERIOR formateado por el agente.
    """
    return render("emotions_pass2_user", unidades=unidades_block)
