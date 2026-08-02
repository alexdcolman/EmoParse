"""Plugin API de géneros.

Públicos:
    Genre, GenreFactory
    get_genre, all_genres, default_genre, register, reset_for_tests
    GenreRegistryError, DEFAULT_GENRE_ID
"""

from emoparse.genres.base import (
    ChunkUnit,
    Genre,
    GenreContextBlock,
    GenreFactory,
    StageName,
)
from emoparse.genres.presentation import (
    GenrePresentation,
    InputMetadataField,
    attach_genre_presentation,
    metadata_is_present,
    presentation_from_config,
    presentation_from_genre,
    presented_metadata,
)
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
    "GenreContextBlock",
    "GenreFactory",
    "GenrePresentation",
    "GenreRegistryError",
    "InputMetadataField",
    "StageName",
    "all_genres",
    "attach_genre_presentation",
    "default_genre",
    "get_genre",
    "metadata_is_present",
    "presentation_from_config",
    "presentation_from_genre",
    "presented_metadata",
    "register",
    "reset_for_tests",
]
