# ══════════════════════════════════════════════════════════════════════════════
#  emoparse.core.prompts.vision_describe
#
#  Wrapper Jinja2 de vision_describe_system + vision_describe_user.
# ══════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

from emoparse.core.prompts._loader import render


def render_system() -> str:
    """SYSTEM de vision_describe."""
    return render("vision_describe_system")


def render_user(texto_post: str, alt_text: str | None = None) -> str:
    """USER de vision_describe con el texto del post que acompaña la imagen."""
    return render(
        "vision_describe_user",
        texto_post=texto_post,
        alt_text=alt_text,
    )
