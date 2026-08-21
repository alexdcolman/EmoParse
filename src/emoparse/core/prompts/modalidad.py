# ══════════════════════════════════════════════════════════════════════════════
#  emoparse.core.prompts.modalidad
# ══════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

from emoparse.core.prompts._loader import render


def render_system(*, heuristicas: str = "") -> str:
    """SYSTEM de modalidad con contrato estable + heurística transversal."""
    return render("modalidad_system", heuristicas=heuristicas)


def render_user(codigo: str, vinculos: str, resumen: str = "") -> str:
    """USER de modalidad con aristas numeradas y contexto mínimo."""
    return render(
        "modalidad_user",
        codigo=codigo,
        vinculos=vinculos,
        resumen=resumen,
    )
