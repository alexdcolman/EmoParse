# ══════════════════════════════════════════════════════════════════════════════
#  emoparse.core.prompts.actants
#
#  Wrappers tipados de los templates Jinja2 del agente de actantes.
# ══════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

from collections.abc import Iterable

from emoparse.core.prompts._loader import render


def render_system(
    *,
    titulo: str = "",
    tipo_discurso: str = "",
    enabled_components: Iterable[str] = (),
    heuristicas: str | None = None,
) -> str:
    """Renderiza el system prompt del agente de actantes.

    Args:
        titulo: Título del discurso.
        tipo_discurso: Clasificación del discurso.
        enabled_components: Componentes actanciales habilitados para este
            run. Los componentes ausentes de esta colección se piden al
            modelo como deshabilitados (presente=false, tipo='ausente').
        heuristicas: Reglas heurísticas opcionales para el dominio.
    """
    return render(
        "actants_system",
        titulo=titulo,
        tipo_discurso=tipo_discurso,
        enabled_components=list(enabled_components),
        heuristicas=heuristicas,
    )


def render_user(*, unidades_block: str) -> str:
    """Renderiza el user prompt del agente con el bloque de emociones."""
    return render("actants_user", unidades_block=unidades_block)
