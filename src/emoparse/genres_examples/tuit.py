# ══════════════════════════════════════════════════════════════════════════════
#  emoparse.genres_examples.tuit
#
#  Plugin de ejemplo: tuit / post de red social.
# ══════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

from emoparse.genres.base import Genre


def get_genre() -> Genre:
    """Factory del género 'tuit'."""
    return Genre(
        genre_id="tuit",
        display_name="Tuit / Post de red social",
        unit="documento",
        enunciation_roles=(
            "seguidor",
            "oponente",
            "audiencia_general",
        ),
        models={
        },
        batch_size={
            "actors": 10,
            "emotions": 10,
            "characterizer": 10,
        },
        summarizer=False,
        prompt_overrides={},
    )
