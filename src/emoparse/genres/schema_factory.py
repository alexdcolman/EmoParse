# ══════════════════════════════════════════════════════════════════════════════
#  emoparse.genres.schema_factory
#
#  Construye schemas Pydantic dinámicos según el género activo.
# ══════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

from functools import lru_cache
from typing import TYPE_CHECKING, Annotated, Literal

from pydantic import Field, RootModel, create_model

from emoparse.core.schemas import (
    EmocionesBatchItemSchema,
    EmocionSchema,
    EnunciacionSchema,
    EnunciadorSchema,
    EnunciatarioSchema,
    MetadatosSchema,
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


@lru_cache(maxsize=None)
def metadatos_schema_for(genre_id: str, tipos: tuple[str, ...]) -> type:
    """Subclase de MetadatosSchema con `tipo_discurso` restringido a tipos."""
    if not tipos:
        raise ValueError(
            "El género debe declarar al menos un tipo de discurso en "
            "`tipos_discurso` para restringir el schema de metadatos."
        )
    literal_type = Literal[tuple(tipos)]  # type: ignore[valid-type]
    base_field = MetadatosSchema.model_fields["tipo_discurso"]

    Model = create_model(
        f"MetadatosSchema_{genre_id}",
        __base__=MetadatosSchema,
        tipo_discurso=(
            literal_type,
            Field(description=base_field.description),
        ),
    )
    return Model


@lru_cache(maxsize=None)
def emociones_batch_schema_for(genre_id: str, max_emociones: int) -> type:
    """Batch de emociones con la lista por unidad acotada a `max_emociones`.

    El tope viaja a la gramática como `maxItems`, de modo que el sampler está
    obligado a cerrar la lista: acota el peor caso de generación y evita que
    una unidad consuma la ventana entera repitiendo entradas. El nombre del
    modelo es estable por género, así que no fragmenta el cache del backend.
    """
    item_cls = create_model(
        f"EmocionesBatchItemSchema_{genre_id}",
        __base__=EmocionesBatchItemSchema,
        emociones=(
            list[EmocionSchema],
            Field(
                max_length=max_emociones,
                description=EmocionesBatchItemSchema.model_fields[
                    "emociones"
                ].description,
            ),
        ),
    )
    model = RootModel[Annotated[list[item_cls], Field(min_length=1)]]  # type: ignore[valid-type]
    model.__name__ = f"ListaEmocionesBatchSchema_{genre_id}"
    model.__qualname__ = model.__name__
    return model


# ══════════════════════════════════════════════════════════════════════════════
#  Entrypoint conveniente desde un Genre
# ══════════════════════════════════════════════════════════════════════════════

def enunciacion_schema(genre: "Genre") -> type:
    """Devuelve EnunciacionSchema dinámico para un Genre."""
    return enunciacion_schema_for(genre.genre_id, genre.enunciation_roles)


def metadatos_schema(genre: "Genre") -> type | None:
    """Devuelve MetadatosSchema dinámico para un Genre.

    None si el género no declara `tipos_discurso` (campo libre)."""
    if not genre.tipos_discurso:
        return None
    return metadatos_schema_for(genre.genre_id, genre.tipos_discurso)


def emociones_batch_schema(genre: "Genre") -> type | None:
    """Devuelve el batch de emociones dinámico para un Genre.

    None si el género conserva el tope por defecto del schema base."""
    base_max = None
    for meta in EmocionesBatchItemSchema.model_fields["emociones"].metadata:
        base_max = getattr(meta, "max_length", None) or base_max
    if base_max is not None and genre.max_emociones_unidad == base_max:
        return None
    return emociones_batch_schema_for(
        genre.genre_id, genre.max_emociones_unidad
    )
