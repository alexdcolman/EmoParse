# ══════════════════════════════════════════════════════════════════════════════
#  emoparse.core.prompts.deixis
#
#  Wrapper Jinja2. Firma pública estable.
# ══════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

from emoparse.core.prompts._loader import render


def render_system() -> str:
    """SYSTEM de deixis: reglas de resolución de marcas deícticas."""
    return render("deixis_system")


def render_user(codigo: str, referentes: str, marcas: str, resumen: str = "") -> str:
    """USER de deixis con los referentes del discurso y las marcas a resolver."""
    return render(
        "deixis_user",
        codigo=codigo,
        referentes=referentes,
        marcas=marcas,
        resumen=resumen,
    )
