"""Contratos de aislamiento de heurísticas específicas por género."""

from __future__ import annotations

from emoparse.genres.articulo_periodistico import get_genre as get_article_genre
from emoparse.genres.discurso_presidencial import (
    get_genre as get_presidential_speech_genre,
)
from emoparse.genres.tuit import get_genre as get_tuit_genre


def test_tuit_declares_its_own_emotion_heuristics() -> None:
    genre = get_tuit_genre()

    assert genre.heuristics_overrides["emotions"] == ("heuristicas/emotions_tuit.md")
    assert genre.heuristics_overrides["emotions_pass2"] == ("heuristicas/emotions_tuit.md")


def test_non_tuit_genres_never_declare_tuit_heuristics() -> None:
    genres = (
        get_article_genre(),
        get_presidential_speech_genre(),
    )

    for genre in genres:
        assert "emotions" not in genre.heuristics_overrides
        assert "emotions_pass2" not in genre.heuristics_overrides
        assert all("_tuit." not in filename for filename in genre.heuristics_overrides.values())
