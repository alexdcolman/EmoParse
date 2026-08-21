"""Prompt mínimo para reparar contaminación de escritura en texto generado."""

from __future__ import annotations

from emoparse.core.prompts._loader import render


def render_system() -> str:
    """Renderiza la instrucción estable de reparación léxica."""
    return render("output_quality_system")


def render_user(*, contaminated: str, context: str) -> str:
    """Renderiza el span contaminado y su contexto local."""
    return render(
        "output_quality_user",
        contaminated=contaminated,
        context=context,
    )
