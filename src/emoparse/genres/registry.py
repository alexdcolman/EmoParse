# ══════════════════════════════════════════════════════════════════════════════
#  emoparse.genres.registry
#
#  Descubre géneros registrados vía entry-points.
# ══════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

from importlib.metadata import EntryPoint, entry_points
from typing import TYPE_CHECKING

from loguru import logger

if TYPE_CHECKING:
    from emoparse.genres.base import Genre, GenreFactory


#: Grupo bajo el cual se buscan entry-points.
_ENTRY_POINT_GROUP = "emoparse.genres"


class GenreRegistryError(LookupError):
    """Error al resolver o registrar un género."""


# ══════════════════════════════════════════════════════════════════════════════
#  Estado interno (singleton-like)
# ══════════════════════════════════════════════════════════════════════════════

class _State:
    discovered: dict[str, "Genre"] | None = None  # None = no escaneado aún.
    programmatic: dict[str, "Genre"] = {}

    @classmethod
    def clear(cls) -> None:
        """Resetea el estado interno (tests)."""
        cls.discovered = None
        cls.programmatic = {}


# ══════════════════════════════════════════════════════════════════════════════
#  Descubrimiento
# ══════════════════════════════════════════════════════════════════════════════

def _discover() -> dict[str, "Genre"]:
    """Escanea entry-points y construye mapa genre_id → Genre."""
    found: dict[str, "Genre"] = {}

    eps: tuple[EntryPoint, ...] = tuple(entry_points(group=_ENTRY_POINT_GROUP))

    for ep in eps:
        try:
            factory: "GenreFactory" = ep.load()
        except Exception as e:
            logger.warning(
                f"[genres] Entry-point '{ep.name}' falló al cargar: "
                f"{type(e).__name__}: {e}. Lo ignoro."
            )
            continue

        try:
            genre = factory()
        except Exception as e:
            logger.warning(
                f"[genres] Factory del entry-point '{ep.name}' lanzó "
                f"al invocarla: {type(e).__name__}: {e}. Lo ignoro."
            )
            continue

        from emoparse.genres.base import Genre

        if not isinstance(genre, Genre):
            logger.warning(
                f"[genres] Entry-point '{ep.name}' devolvió "
                f"{type(genre).__name__} en vez de Genre. Lo ignoro."
            )
            continue

        if genre.genre_id in found:
            raise GenreRegistryError(
                f"Dos entry-points declaran el mismo genre_id "
                f"'{genre.genre_id}'. Cambiar el id en uno de los plugins."
            )

        found[genre.genre_id] = genre
        logger.debug(f"[genres] Descubierto: {genre.genre_id} ({genre.display_name})")

    return found


# ══════════════════════════════════════════════════════════════════════════════
#  API pública
# ══════════════════════════════════════════════════════════════════════════════

def all_genres() -> dict[str, "Genre"]:
    """Devuelve géneros conocidos (descubiertos + programáticos)."""
    if _State.discovered is None:
        _State.discovered = _discover()
    return {**_State.discovered, **_State.programmatic}


def get_genre(genre_id: str) -> "Genre":
    """Resuelve un genre_id a su Genre."""
    genres = all_genres()
    if genre_id not in genres:
        raise GenreRegistryError(
            f"Género desconocido: '{genre_id}'. "
            f"Disponibles: {sorted(genres)}"
        )
    return genres[genre_id]


def register(genre: "Genre") -> None:
    """Registra un Genre programáticamente."""
    _State.programmatic[genre.genre_id] = genre


def reset_for_tests() -> None:
    """Limpia el cache de descubrimiento y registros programáticos."""
    _State.clear()


# ══════════════════════════════════════════════════════════════════════════════
#  Default genre
# ══════════════════════════════════════════════════════════════════════════════

DEFAULT_GENRE_ID = "discurso_presidencial"


def default_genre() -> "Genre":
    """Devuelve el género default ('discurso_presidencial')."""
    try:
        return get_genre(DEFAULT_GENRE_ID)
    except GenreRegistryError as e:
        raise GenreRegistryError(
            f"Género default '{DEFAULT_GENRE_ID}' no encontrado. "
            "Verificar instalación (entry-points en pyproject.toml) "
            f"o registrar programáticamente. Causa: {e}"
        ) from e
