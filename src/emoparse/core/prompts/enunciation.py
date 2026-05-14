# ══════════════════════════════════════════════════════════════════════════════
#  emoparse.core.prompts.enunciation
#
#  Wrapper Jinja2. Firma pública estable.
# ══════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

from emoparse.core.prompts._loader import render


def render_system(diccionario: str) -> str:
    """SYSTEM de enunciation con el diccionario de tipos de discurso inyectado."""
    return render("enunciation_system", diccionario=diccionario)


def render_user(codigo: str, resumen: str, fragmentos: str) -> str:
    """USER de enunciation con datos del discurso concreto."""
    return render(
        "enunciation_user",
        codigo=codigo,
        resumen=resumen,
        fragmentos=fragmentos,
    )
