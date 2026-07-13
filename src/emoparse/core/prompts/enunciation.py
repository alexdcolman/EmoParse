# ══════════════════════════════════════════════════════════════════════════════
#  emoparse.core.prompts.enunciation
#
#  Wrapper Jinja2. Firma pública estable.
# ══════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

from emoparse.core.prompts._loader import render


def render_system(
    diccionario: str,
    heuristicas: str | None = None,
    colectivos: str | None = None,
    template: str = "enunciation_system",
) -> str:
    """SYSTEM de enunciation con el diccionario de tipos de discurso inyectado.

    `colectivos` es la ontología de colectivos de identificación formateada por
    tipo de discurso; si None, no se inyecta esa sección. `template` permite a
    los géneros sustituir el system prompt vía `Genre.prompt_overrides` (p. ej.
    'enunciation_system_tuit'); el alternativo debe aceptar las mismas variables.
    """
    return render(
        template,
        diccionario=diccionario,
        heuristicas=heuristicas,
        colectivos=colectivos,
    )


def render_user(codigo: str, resumen: str, fragmentos: str) -> str:
    """USER de enunciation con datos del discurso concreto."""
    return render(
        "enunciation_user",
        codigo=codigo,
        resumen=resumen,
        fragmentos=fragmentos,
    )
