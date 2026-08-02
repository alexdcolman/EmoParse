# ══════════════════════════════════════════════════════════════════════════════
#  emoparse.genres.presentation
#
#  Snapshot liviano de presentación de género persistido con cada run.
# ══════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from math import isnan
from typing import Any

from emoparse.genres.base import Genre

#: Sección reservada dentro de ``runs.config`` para metadata calculada por
#: EmoParse y no proveniente del archivo YAML del usuario.
RUNTIME_CONFIG_KEY = "_emoparse"


@dataclass(frozen=True, slots=True)
class InputMetadataField:
    """Campo de metadata de input que puede presentarse al usuario."""

    name: str
    label: str


@dataclass(frozen=True, slots=True)
class GenrePresentation:
    """Descriptor estable y mínimo para dashboard y exports.

    Se persiste como snapshot porque el plugin que produjo un run puede no
    estar disponible cuando ese run se consulta o exporta más adelante.
    """

    genre_id: str
    display_name: str
    input_metadata: tuple[InputMetadataField, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        """Serializa el descriptor a una estructura JSON-compatible."""
        return {
            "genre_id": self.genre_id,
            "display_name": self.display_name,
            "input_metadata": [
                {"name": field.name, "label": field.label} for field in self.input_metadata
            ],
        }


def presentation_from_genre(genre: Genre) -> GenrePresentation:
    """Construye el snapshot desde la declaración del género activo."""
    fields = tuple(
        InputMetadataField(name=name, label=label)
        for name, label in genre.input_metadata_display.items()
    )
    return GenrePresentation(
        genre_id=genre.genre_id,
        display_name=genre.display_name,
        input_metadata=fields,
    )


def attach_genre_presentation(
    config: Mapping[str, Any],
    genre: Genre,
) -> dict[str, Any]:
    """Devuelve una copia del config con el snapshot del género activo."""
    out = dict(config)
    runtime_raw = out.get(RUNTIME_CONFIG_KEY)
    runtime = dict(runtime_raw) if isinstance(runtime_raw, Mapping) else {}
    runtime["genre"] = presentation_from_genre(genre).to_dict()
    out[RUNTIME_CONFIG_KEY] = runtime
    return out


def presentation_from_config(
    config: Mapping[str, Any] | None,
) -> GenrePresentation | None:
    """Recupera un snapshot persistido y tolera runs previos o corruptos."""
    if not isinstance(config, Mapping):
        return None
    runtime = config.get(RUNTIME_CONFIG_KEY)
    if not isinstance(runtime, Mapping):
        return None
    raw = runtime.get("genre")
    if not isinstance(raw, Mapping):
        return None

    genre_id = raw.get("genre_id")
    display_name = raw.get("display_name")
    if not isinstance(genre_id, str) or not genre_id.strip():
        return None
    if not isinstance(display_name, str) or not display_name.strip():
        return None

    fields: list[InputMetadataField] = []
    seen: set[str] = set()
    raw_fields = raw.get("input_metadata", ())
    if isinstance(raw_fields, list):
        for item in raw_fields:
            if not isinstance(item, Mapping):
                continue
            name = item.get("name")
            label = item.get("label")
            if (
                not isinstance(name, str)
                or not name.strip()
                or not isinstance(label, str)
                or not label.strip()
                or name in seen
            ):
                continue
            seen.add(name)
            fields.append(InputMetadataField(name=name, label=label))

    return GenrePresentation(
        genre_id=genre_id,
        display_name=display_name,
        input_metadata=tuple(fields),
    )


def metadata_is_present(value: Any) -> bool:
    """Indica si un valor de metadata contiene información efectiva."""
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (list, tuple, set, dict)):
        return bool(value)
    if isinstance(value, float):
        try:
            return not isnan(value)
        except TypeError:
            return True
    return True


def presented_metadata(
    presentation: GenrePresentation | None,
    payload: Mapping[str, Any] | None,
    *,
    include_missing: bool = False,
) -> list[dict[str, Any]]:
    """Materializa campos declarados sin conocer géneros concretos.

    El orden y las etiquetas provienen del snapshot. Los valores ausentes se
    omiten en interfaz y pueden conservarse en exports para medir cobertura.
    """
    if presentation is None or not isinstance(payload, Mapping):
        return []

    records: list[dict[str, Any]] = []
    for field in presentation.input_metadata:
        value = payload.get(field.name)
        present = metadata_is_present(value)
        if not present and not include_missing:
            continue
        records.append(
            {
                "field": field.name,
                "label": field.label,
                "value": value,
                "present": present,
            }
        )
    return records
