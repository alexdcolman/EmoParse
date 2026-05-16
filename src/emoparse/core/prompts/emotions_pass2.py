# ══════════════════════════════════════════════════════════════════════════════
#  emoparse.core.prompts.emotions_pass2
#
#  Wrapper Jinja2. Firma pública estable.
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
    """SYSTEM del pase 2.

    Incluye instrucciones de uso del rolling/full summary, reglas
    anti-alucinación y los ocho tipos de configuraciones de simulacro
    emocional que el agente debe asignar a cada emoción detectada.
    """
    return render(
        "emotions_pass2_system",
        ontologia=ontologia,
        heuristicas=heuristicas,
        configuraciones=configuraciones,
        titulo=titulo,
        tipo_discurso=tipo_discurso,
        enunciador=enunciador,
    )


def render_user(unidades_block: str) -> str:
    """USER del pase 2.

    Cada unidad ya viene con su CONTEXTO ANTERIOR formateado por el agente."""
    return render("emotions_pass2_user", unidades=unidades_block)
