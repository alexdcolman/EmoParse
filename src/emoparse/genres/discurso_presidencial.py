# ══════════════════════════════════════════════════════════════════════════════
#  emoparse.genres.discurso_presidencial
#
#  Género built-in: discurso presidencial / discurso político clásico.
# ══════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

from emoparse.genres.base import Genre


def get_genre() -> Genre:
    """Factory expuesta como entry-point en pyproject.toml."""
    return Genre(
        genre_id="discurso_presidencial",
        display_name="Discurso presidencial",
        unit="frase",
        enunciation_roles=(
            "prodestinatario",
            "paradestinatario",
            "contradestinatario",
        ),
        models={},
        batch_size={
            "actors": 1,
            "normalize_actors": 7,
            "emotions": 1,
            "emotions_pass2": 1,
            "characterizer": 1,
            "actants": 1,
            "judge": 1,
        },
        summarizer=True,
        prompt_overrides={},
    )
