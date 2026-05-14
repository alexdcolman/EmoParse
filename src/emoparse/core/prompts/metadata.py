# ══════════════════════════════════════════════════════════════════════════════
#  emoparse.core.prompts.metadata
#
#  Wrapper Jinja2. Firma pública estable.
# ══════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

from emoparse.core.prompts._loader import render


def render_system(diccionario: str) -> str:
    """SYSTEM de metadata.
    
    `diccionario` es el dump JSON-stringificado de tipos de discurso.
    """
    return render("metadata_system", diccionario=diccionario)


def render_user(codigo: str, resumen: str, fragmentos: str) -> str:
    """USER de metadata. Datos variables del discurso concreto."""
    return render(
        "metadata_user",
        codigo=codigo,
        resumen=resumen,
        fragmentos=fragmentos,
    )
