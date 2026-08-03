# ══════════════════════════════════════════════════════════════════════════════
#  emoparse.genres.articulo_periodistico
#
#  Género built-in: artículo periodístico en español.
# ══════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel, ConfigDict, field_validator

from emoparse.genres.base import Genre, GenreContextBlock


class ArticuloPeriodisticoMetadata(BaseModel):
    """Metadata de entrada propia de un artículo periodístico."""

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    medio: str | None = None
    idioma: str | None = None
    seccion: str | None = None
    volanta: str | None = None
    subtitulo: str | None = None
    autoria: tuple[str, ...] = ()
    agencia: str | None = None
    epigrafe: str | None = None

    @field_validator(
        "medio",
        "idioma",
        "seccion",
        "volanta",
        "subtitulo",
        "agencia",
        "epigrafe",
        mode="before",
    )
    @classmethod
    def normalize_optional_text(cls, value: Any) -> str | None:
        """Convierte valores vacíos o NaN en ausencia explícita."""
        if _is_missing(value):
            return None
        text = str(value).strip()
        return text or None

    @field_validator("autoria", mode="before")
    @classmethod
    def normalize_authors(cls, value: Any) -> tuple[str, ...]:
        """Acepta lista, JSON o texto separado por punto y coma o barra."""
        if _is_missing(value):
            return ()
        if isinstance(value, str):
            raw = value.strip()
            if not raw:
                return ()
            if raw.startswith("["):
                try:
                    value = json.loads(raw)
                except json.JSONDecodeError:
                    value = raw
            if isinstance(value, str):
                parts = [part.strip() for part in raw.replace("|", ";").split(";")]
                return tuple(dict.fromkeys(part for part in parts if part))
        if isinstance(value, (list, tuple, set)):
            authors = (str(item).strip() for item in value if not _is_missing(item))
            return tuple(dict.fromkeys(author for author in authors if author))
        text = str(value).strip()
        return (text,) if text else ()


def _is_missing(value: Any) -> bool:
    if value is None:
        return True
    try:
        return bool(value != value)
    except (TypeError, ValueError):
        return False


_ROLES_PERIODISTICOS: tuple[str, ...] = (
    "lector_ciudadano",
    "instancia_blanco",
    "fuente_referente",
)


def get_genre() -> Genre:
    """Factory expuesta como entry-point en pyproject.toml."""
    return Genre(
        genre_id="articulo_periodistico",
        display_name="Artículo periodístico",
        unit="parrafo",
        context_unit="discurso",
        technoparse=False,
        input_metadata_model=ArticuloPeriodisticoMetadata,
        input_metadata_display={
            "medio": "Medio",
            "seccion": "Sección",
            "volanta": "Volanta",
            "subtitulo": "Subtítulo",
            "autoria": "Autoría",
            "agencia": "Agencia",
            "epigrafe": "Epígrafe",
            "idioma": "Idioma",
        },
        enunciador_from_input_field="autoria",
        context_blocks=(
            GenreContextBlock(
                name="contexto_editorial",
                title="Contexto editorial del artículo",
                fields=(
                    "medio",
                    "seccion",
                    "volanta",
                    "subtitulo",
                    "autoria",
                    "agencia",
                    "epigrafe",
                    "idioma",
                ),
                stage_token_budgets={
                    "summarizer": 220,
                    "metadata": 180,
                    "enunciation": 180,
                    "emotions": 140,
                },
            ),
        ),
        enunciation_roles=_ROLES_PERIODISTICOS,
        enunciatarios_por_tipo={
            "periodistico": _ROLES_PERIODISTICOS,
        },
        roles_descripciones={
            "lector_ciudadano": (
                "el público ciudadano amplio al que informa la nota "
                "(instancia-público), sin vocativo, en registro informativo."
            ),
            "instancia_blanco": (
                "el destinatario calculado por la estrategia editorial del medio; "
                "se reconoce por el ángulo de la nota más que por marcas."
            ),
            "fuente_referente": (
                "el actor citado o etiquetado como fuente o protagonista de la "
                "noticia, interpelado o mencionado."
            ),
        },
        tipos_discurso=(
            "noticia",
            "cronica",
            "entrevista",
            "analisis",
            "opinion",
            "otro_periodistico",
        ),
        tipos_discurso_descripciones={
            "noticia": "presentación informativa de un acontecimiento de actualidad",
            "cronica": "relato temporal y situado de acontecimientos observados o reconstruidos",
            "entrevista": (
                "organización centrada en preguntas, respuestas o declaraciones de una fuente"
            ),
            "analisis": (
                "interpretación explicativa apoyada en antecedentes, datos o voces expertas"
            ),
            "opinion": "toma de posición argumentada y atribuida a una firma o al medio",
            "otro_periodistico": "pieza periodística que no se ajusta a los tipos anteriores",
        },
        batch_size={
            "actors": 1,
            "emotions": 1,
            "emotions_pass2": 1,
            "deixis": 4,
            "semas": 2,
            "characterizer": 1,
            "actants": 1,
            "judge": 1,
        },
        summarizer=True,
        max_emociones_unidad=10,
    )


__all__ = ["ArticuloPeriodisticoMetadata", "get_genre"]
