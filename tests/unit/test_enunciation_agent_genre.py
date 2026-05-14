# ══════════════════════════════════════════════════════════════════════════════
#  tests.unit.test_enunciation_agent_genre
#
#  El EnunciationAgent debe usar un SCHEMA dinámico cuando se le
#  pasa un Genre, y mantener el SCHEMA histórico cuando no:
#  - Sin genre → SCHEMA == EnunciacionSchema (histórico).
#  - Con genre político → SCHEMA es subclase dinámica con roles políticos.
#  - Con genre tuit    → SCHEMA es subclase dinámica con roles de redes.
#  - SCHEMAs de géneros distintos son CLASES distintas.
# ══════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

from typing import TypeVar

import pandas as pd
import pytest
from pydantic import BaseModel

from emoparse.agents.enunciation import EnunciationAgent
from emoparse.core.backend.base import LLMBackend, LLMResponse, TokenUsage
from emoparse.core.schemas import EnunciacionSchema
from emoparse.genres.base import Genre

T = TypeVar("T", bound=BaseModel)


def _first_valid_enunciatario_role(schema: type) -> str:
    """Devuelve un rol válido para `enunciatarios[].tipo` según el schema.

    Inspecciona el campo anidado del modelo:
        schema.enunciatarios -> list[EnunciatarioSchema_<x>]
        EnunciatarioSchema_<x>.tipo -> Literal["..."]

    Si no se puede inferir (schema histórico abierto a str), devolvemos
    un rol que el histórico acepta ('prodestinatario' está en el
    Literal global).
    """
    import typing

    enunciatarios_field = schema.model_fields["enunciatarios"]
    # `annotation` es `list[EnunciatarioSchema_xxx]`.
    item_type = typing.get_args(enunciatarios_field.annotation)[0]
    tipo_field = item_type.model_fields["tipo"]
    args = typing.get_args(tipo_field.annotation)
    if args:
        return str(args[0])
    return "prodestinatario"


# ══════════════════════════════════════════════════════════════════════════════
#  Fake backend ligero
# ══════════════════════════════════════════════════════════════════════════════

class _FakeBackend(LLMBackend):
    def __init__(self) -> None:
        self.alias = "fake"
        self.last_schema: type | None = None
        self.calls = 0

    def generate(
        self,
        system: str,
        user: str,
        *,
        schema: type[T] | None = None,
        max_tokens: int | None = None,
        temperature: float | None = None,
        seed: int | None = None,
        stop: list[str] | None = None,
        reset_before: bool = False,
    ) -> LLMResponse:
        self.last_schema = schema
        self.calls += 1
        assert schema is not None
        rol = _first_valid_enunciatario_role(schema)
        payload = schema.model_validate({
            "enunciador": {"actor": "X", "justificacion": "Y"},
            "enunciatarios": [
                {"actor": "A", "tipo": rol, "justificacion": "Z"},
            ],
        })
        return LLMResponse(
            parsed=payload,
            raw="(fake)",
            usage=TokenUsage(prompt_tokens=1, completion_tokens=1),
            latency_ms=1.0,
            model_alias=self.alias,
            cache_hit=False,
            finish_reason="stop",
        )

    def healthcheck(self) -> bool:
        return True


# ══════════════════════════════════════════════════════════════════════════════
#  Fixtures
# ══════════════════════════════════════════════════════════════════════════════

@pytest.fixture
def diccionario_tipos() -> dict[str, str]:
    return {"asuncion": "Toma de posesión.", "anuncio_medida": "Anuncio."}


@pytest.fixture
def sample_df() -> pd.DataFrame:
    return pd.DataFrame([{
        "codigo": "D001",
        "contenido": "Discurso de prueba para enunciación.",
    }])


@pytest.fixture
def politico() -> Genre:
    return Genre(
        genre_id="politico_t",
        display_name="Político (t)",
        unit="frase",
        enunciation_roles=("prodestinatario", "paradestinatario", "contradestinatario"),
    )


@pytest.fixture
def tuit() -> Genre:
    return Genre(
        genre_id="tuit_t",
        display_name="Tuit (t)",
        unit="documento",
        enunciation_roles=("seguidor", "oponente", "audiencia_general"),
    )


# ══════════════════════════════════════════════════════════════════════════════
#  Tests
# ══════════════════════════════════════════════════════════════════════════════

class TestSchemaDispatch:
    def test_no_genre_uses_historic_schema(
        self,
        diccionario_tipos: dict[str, str],
        sample_df: pd.DataFrame,
    ) -> None:
        backend = _FakeBackend()
        agent = EnunciationAgent(backend, diccionario_tipos)
        agent.run(sample_df)

        assert backend.last_schema is EnunciacionSchema

    def test_genre_uses_dynamic_schema(
        self,
        diccionario_tipos: dict[str, str],
        sample_df: pd.DataFrame,
        politico: Genre,
    ) -> None:
        backend = _FakeBackend()
        agent = EnunciationAgent(backend, diccionario_tipos, genre=politico)
        agent.run(sample_df)

        # El SCHEMA usado debe ser una subclase de EnunciacionSchema,
        # no la base misma, y su nombre debe incluir el genre_id.
        assert backend.last_schema is not EnunciacionSchema
        assert backend.last_schema is not None
        assert issubclass(backend.last_schema, EnunciacionSchema)
        assert "politico_t" in backend.last_schema.__name__

    def test_different_genres_get_different_schemas(
        self,
        diccionario_tipos: dict[str, str],
        sample_df: pd.DataFrame,
        politico: Genre,
        tuit: Genre,
    ) -> None:
        b1 = _FakeBackend()
        EnunciationAgent(b1, diccionario_tipos, genre=politico).run(sample_df)
        b2 = _FakeBackend()
        EnunciationAgent(b2, diccionario_tipos, genre=tuit).run(sample_df)

        assert b1.last_schema is not b2.last_schema

    def test_same_genre_reuses_schema_class(
        self,
        diccionario_tipos: dict[str, str],
        sample_df: pd.DataFrame,
        politico: Genre,
    ) -> None:
        # Crítico: el cache LLM key incluye el qualname del schema.
        # Dos agentes con el mismo género deben recibir el mismo objeto
        # clase de schema (no copias) para que el cache funcione.
        b1 = _FakeBackend()
        EnunciationAgent(b1, diccionario_tipos, genre=politico).run(sample_df)
        b2 = _FakeBackend()
        EnunciationAgent(b2, diccionario_tipos, genre=politico).run(sample_df)

        assert b1.last_schema is b2.last_schema


class TestBackwardsCompat:
    """Los tests existentes (sin genre) deben seguir funcionando."""

    def test_init_signature_accepts_only_legacy_args(
        self,
        diccionario_tipos: dict[str, str],
    ) -> None:
        agent = EnunciationAgent(
            _FakeBackend(),
            diccionario_tipos,
            retry_config=None,
        )
        assert agent.SCHEMA is EnunciacionSchema
