# ══════════════════════════════════════════════════════════════════════════════
#  emoparse.genres.schema_factory
#
#  Construye schemas Pydantic dinámicos según el género activo.
# ══════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

from functools import lru_cache
from typing import TYPE_CHECKING, Literal

from pydantic import Field, create_model

from emoparse.core.schemas import (
    EnunciacionSchema,
    EnunciadorSchema,
    EnunciatarioSchema,
)

if TYPE_CHECKING:
    from emoparse.genres.base import Genre


def _literal_from_roles(roles: tuple[str, ...]) -> type:
    """Construye un `Literal[*roles]` runtime."""
    if not roles:
        raise ValueError(
            "El género debe declarar al menos un rol enunciativo en "
            "`enunciation_roles`."
        )
    return Literal[tuple(roles)]  # type: ignore[valid-type]


# ══════════════════════════════════════════════════════════════════════════════
#  Schemas dinámicos por género
# ══════════════════════════════════════════════════════════════════════════════

@lru_cache(maxsize=None)
def enunciatario_schema_for(genre_id: str, roles: tuple[str, ...]) -> type:
    """Subclase de EnunciatarioSchema con tipo restringido a roles."""
    literal_type = _literal_from_roles(roles)

    base_field = EnunciatarioSchema.model_fields["tipo"]

    Model = create_model(
        f"EnunciatarioSchema_{genre_id}",
        __base__=EnunciatarioSchema,
        tipo=(
            literal_type,
            Field(description=base_field.description),
        ),
    )
    return Model


@lru_cache(maxsize=None)
def enunciacion_schema_for(genre_id: str, roles: tuple[str, ...]) -> type:
    """Subclase de EnunciacionSchema con enunciatarios restringidos a roles."""
    enunciatario_cls = enunciatario_schema_for(genre_id, roles)
    base_enunciatarios_field = EnunciacionSchema.model_fields["enunciatarios"]
    base_enunciador_field = EnunciacionSchema.model_fields["enunciador"]

    Model = create_model(
        f"EnunciacionSchema_{genre_id}",
        __base__=EnunciacionSchema,
        enunciador=(
            EnunciadorSchema,
            Field(description=base_enunciador_field.description),
        ),
        enunciatarios=(
            list[enunciatario_cls],  # type: ignore[valid-type]
            Field(description=base_enunciatarios_field.description),
        ),
    )
    return Model


# ══════════════════════════════════════════════════════════════════════════════
#  Entrypoint conveniente desde un Genre
# ══════════════════════════════════════════════════════════════════════════════

def enunciacion_schema(genre: "Genre") -> type:
    """Devuelve EnunciacionSchema dinámico para un Genre."""
    return enunciacion_schema_for(genre.genre_id, genre.enunciation_roles)
