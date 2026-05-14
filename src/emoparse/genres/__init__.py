"""Plugin API de géneros.

Públicos:
    Genre, GenreFactory
    get_genre, all_genres, default_genre, register, reset_for_tests
    GenreRegistryError, DEFAULT_GENRE_ID
"""

from emoparse.genres.base import ChunkUnit, Genre, GenreFactory, StageName
from emoparse.genres.registry import (
    DEFAULT_GENRE_ID,
    GenreRegistryError,
    all_genres,
    default_genre,
    get_genre,
    register,
    reset_for_tests,
)

__all__ = [
    "ChunkUnit",
    "DEFAULT_GENRE_ID",
    "Genre",
    "GenreFactory",
    "GenreRegistryError",
    "StageName",
    "all_genres",
    "default_genre",
    "get_genre",
    "register",
    "reset_for_tests",
]
