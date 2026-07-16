# ══════════════════════════════════════════════════════════════════════════════
#  emoparse.genres.tuit
#
#  Género built-in: tuit / post de red social (discurso nativo digital).
# ══════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

from emoparse.genres.base import Genre


def get_genre() -> Genre:
    """Factory expuesta como entry-point en pyproject.toml.

    Roles enunciativos: la tríada de destinatarios de Verón, vigente en el
    discurso político en redes, más dos posiciones propias del dispositivo:
    el destinatario mencionado (la cuenta interpelada vía @, destinación
    técnica directa) y la audiencia ambiente (el público indeterminado del
    archivo buscable, ante el cual todo post también se enuncia).
    """
    return Genre(
        genre_id="tuit",
        display_name="Tuit / Post de red social",
        unit="documento",
        context_unit="hilo",
        technoparse=True,
        enunciation_roles=(
            "prodestinatario",
            "paradestinatario",
            "contradestinatario",
            "destinatario_mencionado",
            "audiencia_ambiente",
        ),
        models={},
        batch_size={
            "actors": 2,
            "emotions": 1,
            "emotions_pass2": 1,
            "characterizer": 1,
            "actants": 1,
            "judge": 1,
            "reframing": 2,
            "emoji_affect": 6,
            "hashtag_semiotics": 2,
        },
        summarizer=False,
        prompt_overrides={
            "emotions": "emotions_system_tuit",
            "enunciation": "enunciation_system_tuit",
        },
    )
