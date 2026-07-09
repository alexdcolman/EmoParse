# ══════════════════════════════════════════════════════════════════════════════
#  emoparse.core.prompts.modalidad
#
#  Wrapper Jinja2. Firma pública estable.
# ══════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

from emoparse.core.prompts._loader import render


def render_system() -> str:
    """SYSTEM de modalidad: reglas de clasificación de modalidad/naturaleza."""
    return render("modalidad_system")


def render_user(codigo: str, vinculos: str, resumen: str = "") -> str:
    """USER de modalidad con los vínculos (marca, referente, frase) a clasificar."""
    return render(
        "modalidad_user",
        codigo=codigo,
        vinculos=vinculos,
        resumen=resumen,
    )
