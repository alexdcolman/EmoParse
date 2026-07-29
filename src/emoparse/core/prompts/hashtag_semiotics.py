# ══════════════════════════════════════════════════════════════════════════════
#  emoparse.core.prompts.hashtag_semiotics
#
#  Wrapper Jinja2 de hashtag_semiotics_system + hashtag_semiotics_user.
# ══════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

from emoparse.core.prompts._loader import render


def render_system(heuristicas: str | None = None) -> str:
    """SYSTEM de hashtag_semiotics. `heuristicas` es opcional."""
    return render("hashtag_semiotics_system", heuristicas=heuristicas)


def render_user(
    hashtag: str,
    n_usos: int,
    unidades_block: str,
    funciones_previas: str | None = None,
) -> str:
    """USER de hashtag_semiotics con un batch de usos de un hashtag.

    `funciones_previas` es el texto formateado de las funciones ya
    identificadas para ese hashtag en el corpus (contexto creciente que
    economiza la re-derivación de la tipología en cada uso); si None, no se
    inyecta esa sección.
    """
    return render(
        "hashtag_semiotics_user",
        hashtag=hashtag,
        n_usos=n_usos,
        unidades=unidades_block,
        funciones_previas=funciones_previas,
    )
