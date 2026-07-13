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


def render_user(unidades_block: str) -> str:
    """USER de hashtag_semiotics con los hashtags del batch."""
    return render("hashtag_semiotics_user", unidades=unidades_block)
