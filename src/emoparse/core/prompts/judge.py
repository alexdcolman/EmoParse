# ══════════════════════════════════════════════════════════════════════════════
#  emoparse.core.prompts.judge
#
#  Wrapper Jinja2. Firma pública estable.
# ══════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

from emoparse.core.prompts._loader import render


def render_system(
    titulo: str,
    tipo_discurso: str,
    heuristicas: str | None = None,
    ontologia: str | None = None,
    resumen: str | None = None,
    enunciacion: str | None = None,
) -> str:
    """SYSTEM del juez.

    Si titulo/tipo_discurso vienen vacíos, los reemplaza por la convención
    del proyecto ('no identificado'). `ontologia` (opcional) inyecta las
    definiciones de emociones. `resumen` (resumen global del discurso) y
    `enunciacion` (bloque preformateado con enunciador, enunciatarios,
    auditorio y colectivos) aportan el contexto de discurso para juzgar los
    simulacros.
    """
    return render(
        "judge_system",
        titulo=titulo or "no identificado",
        tipo_discurso=tipo_discurso or "no identificado",
        heuristicas=heuristicas,
        ontologia=ontologia,
        resumen=resumen,
        enunciacion=enunciacion,
    )


def render_user(unidades_block: str) -> str:
    """USER del juez: las caracterizaciones a juzgar."""
    return render("judge_user", unidades_block=unidades_block)
