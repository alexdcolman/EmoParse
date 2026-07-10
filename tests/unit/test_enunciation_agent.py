# ══════════════════════════════════════════════════════════════════════════════
#  tests.unit.test_enunciation_agent
#
#  Tests del EnunciationAgent. La diferencia clave con MetadataAgent es
#  que el schema es anidado (Enunciador + List[Enunciatario]) y se
#  serializa a JSON al mapear a columnas. Este test cubre esa serialización.
# ══════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

import json
from typing import TypeVar

import pandas as pd
import pytest
from pydantic import BaseModel

from emoparse.agents.enunciation import EnunciationAgent
from emoparse.core.backend.base import LLMBackend, LLMResponse, TokenUsage
from emoparse.core.backend.exceptions import BackendTimeoutError
from emoparse.core.schemas import (
    EnunciacionSchema,
    EnunciadorSchema,
    EnunciatarioSchema,
)

T = TypeVar("T", bound=BaseModel)


# ══════════════════════════════════════════════════════════════════════════════
#  Fake backend
# ══════════════════════════════════════════════════════════════════════════════


class _FakeBackend(LLMBackend):

    def __init__(self, responses: list[BaseModel | Exception]) -> None:
        self.alias = "fake"
        self._responses = list(responses)
        self.calls: list[dict[str, object]] = []

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
        self.calls.append({"system": system, "user": user, "schema": schema})
        nxt = self._responses.pop(0)
        if isinstance(nxt, Exception):
            raise nxt
        return LLMResponse(
            parsed=nxt,
            raw="(fake)",
            usage=TokenUsage(prompt_tokens=10, completion_tokens=20),
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
def diccionario() -> dict[str, str]:
    return {"discurso_politico": "Discurso pronunciado en arena política."}


@pytest.fixture
def sample_df() -> pd.DataFrame:
    return pd.DataFrame([
        {
            "codigo": "DISC_001",
            "resumen_global": "Un discurso de campaña.",
            "contenido": "Compatriotas, vamos a transformar el país...",
        },
    ])


@pytest.fixture
def politico_response() -> EnunciacionSchema:
    return EnunciacionSchema(
        enunciador=EnunciadorSchema(
            actor="Candidato X",
            justificacion="Firma el discurso y se presenta como tal.",
        ),
        enunciatarios=[
            EnunciatarioSchema(
                actor="militantes propios",
                tipo="prodestinatario",
                justificacion="Apela a 'compatriotas' que ya comparten su visión.",
            ),
            EnunciatarioSchema(
                actor="electorado indeciso",
                tipo="paradestinatario",
                justificacion="Promete cambios para convencer a los dudosos.",
            ),
        ],
        auditorio=[],
        colectivos=[],
    )


# ══════════════════════════════════════════════════════════════════════════════
#  Tests
# ══════════════════════════════════════════════════════════════════════════════


class TestEnunciationOutputMapping:
    """Verifica que el schema anidado se mapea correctamente a columnas."""

    def test_columns_added(
        self,
        diccionario: dict[str, str],
        sample_df: pd.DataFrame,
        politico_response: EnunciacionSchema,
    ) -> None:
        backend = _FakeBackend([politico_response])
        agent = EnunciationAgent(backend, diccionario)
        out = agent.run(sample_df)

        for col in EnunciationAgent.OUTPUT_COLUMNS:
            assert col in out.columns

    def test_enunciador_extracted(
        self,
        diccionario: dict[str, str],
        sample_df: pd.DataFrame,
        politico_response: EnunciacionSchema,
    ) -> None:
        backend = _FakeBackend([politico_response])
        agent = EnunciationAgent(backend, diccionario)
        out = agent.run(sample_df)

        assert out.iloc[0]["enunciador"] == "Candidato X"
        assert "Firma" in out.iloc[0]["enunciador_justificacion"]

    def test_enunciatarios_serialized_as_json(
        self,
        diccionario: dict[str, str],
        sample_df: pd.DataFrame,
        politico_response: EnunciacionSchema,
    ) -> None:
        """La lista de enunciatarios se serializa a JSON parseable."""
        backend = _FakeBackend([politico_response])
        agent = EnunciationAgent(backend, diccionario)
        out = agent.run(sample_df)

        enunciatarios_str = out.iloc[0]["enunciatarios"]
        assert isinstance(enunciatarios_str, str)

        # Round-trip: el JSON debe parsear y tener la misma estructura.
        parsed = json.loads(enunciatarios_str)
        assert isinstance(parsed, list)
        assert len(parsed) == 2

        # Verificar contenido del primer enunciatario.
        assert parsed[0]["actor"] == "militantes propios"
        assert parsed[0]["tipo"] == "prodestinatario"
        assert "compatriotas" in parsed[0]["justificacion"].lower()


class TestEnunciationLiteralValidation:
    """El schema valida que `tipo` esté en el universo de TipoEnunciatario."""

    def test_invalid_tipo_raises_validation_error(self) -> None:
        """Construir EnunciatarioSchema con un `tipo` inválido falla
        en Pydantic. Esto es defensa en profundidad: la gramática GBNF
        ya lo prohibiría a nivel sampler, pero si por alguna razón
        llegara un valor inválido, Pydantic lo atrapa."""
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            EnunciatarioSchema(
                actor="X",
                tipo="invalido_inexistente",  # type: ignore[arg-type]
                justificacion="Y",
            )


class TestResumenFallbackTruncation:
    """Mismo fix que en MetadataAgent: cuando `resumen_global` falta o
    es None/NaN, el fallback al `contenido` se trunca para no inyectar
    el discurso entero al prompt. Evita la cascada cuando summarizer
    falla con ContextLengthExceeded."""

    def test_huge_contenido_truncated_when_resumen_missing(
        self,
        diccionario: dict[str, str],
        politico_response: EnunciacionSchema,
    ) -> None:
        huge = "Lorem ipsum dolor sit amet. " * 2000
        df = pd.DataFrame([{"codigo": "X", "contenido": huge}])
        backend = _FakeBackend([politico_response])
        agent = EnunciationAgent(backend, diccionario)
        agent.run(df)

        user = backend.calls[0]["user"]
        assert len(user) < 10000

    def test_resumen_global_none_falls_back(
        self,
        diccionario: dict[str, str],
        politico_response: EnunciacionSchema,
    ) -> None:
        df = pd.DataFrame([
            {
                "codigo": "X",
                "resumen_global": None,
                "contenido": "Texto del discurso original.",
            }
        ])
        backend = _FakeBackend([politico_response])
        agent = EnunciationAgent(backend, diccionario)
        agent.run(df)

        user = backend.calls[0]["user"]
        assert "Texto del discurso original." in user


class TestEnunciationErrorHandling:

    def test_backend_error_marks_row_with_none(
        self,
        diccionario: dict[str, str],
        sample_df: pd.DataFrame,
    ) -> None:
        backend = _FakeBackend([BackendTimeoutError("simulated")])
        agent = EnunciationAgent(backend, diccionario)
        out = agent.run(sample_df)

        assert pd.isna(out.iloc[0]["enunciador"])
        assert pd.isna(out.iloc[0]["enunciatarios"])
        # Original preservado.
        assert out.iloc[0]["codigo"] == "DISC_001"
