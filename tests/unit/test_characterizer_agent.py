# ══════════════════════════════════════════════════════════════════════════════
#  tests.unit.test_characterizer_agent
#
#  Específicos: el batch itera sobre emociones (no frases). El user
#  prompt formatea cada emoción con su contexto (frase de origen,
#  experienciador, tipo, modo). El output agrega 9 columnas.
# ══════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

from typing import TypeVar

import pandas as pd
from pydantic import BaseModel

from emoparse.agents.characterizer import CharacterizerAgent
from emoparse.core.backend.base import LLMBackend, LLMResponse, TokenUsage
from emoparse.core.schemas import (
    CaracterizacionBatchItemSchema,
    CaracterizacionEmocionSchema,
    ListaCaracterizacionBatchSchema,
)

T = TypeVar("T", bound=BaseModel)


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
        self.calls.append({"system": system, "user": user})
        nxt = self._responses.pop(0)
        if isinstance(nxt, Exception):
            raise nxt
        return LLMResponse(
            parsed=nxt, raw="(fake)",
            usage=TokenUsage(prompt_tokens=10, completion_tokens=20),
            latency_ms=1.0, model_alias=self.alias,
            cache_hit=False, finish_reason="stop",
        )

    def healthcheck(self) -> bool:
        return True


def _make_caracterizacion(**overrides: str) -> CaracterizacionEmocionSchema:
    """Helper para construir una caracterización con defaults."""
    base: dict[str, str] = {
        # originales
        "foria": "disforico",
        "foria_justificacion": "tono negativo claro",
        "dominancia": "cognoscitiva",
        "dominancia_justificacion": "registro evaluativo",
        "intensidad": "alta",
        "intensidad_justificacion": "manifiesta y dominante",
        "fuente": "el adversario político",
        "tipo_fuente": "actor",
        "fuente_justificacion": "se nombra explícitamente como causa",
        # nuevas — valores dentro del Literal del schema
        "duracion": "instantanea",
        "duracion_justificacion": "sin marcas de persistencia",
        "modo_semiotizacion": "dicha",
        "modo_semiotizacion_justificacion": "nombre de emoción explícito",
        "modo_identificacion": "directa",
        "modo_identificacion_justificacion": "el hablante se nombra a sí mismo",
        "tipo_atribucion": "auto_atribucion",
        "tipo_atribucion_justificacion": "el hablante se atribuye la emoción en primera persona",
    }
    base.update(overrides)
    return CaracterizacionEmocionSchema(**base)  # type: ignore[arg-type]


# ══════════════════════════════════════════════════════════════════════════════


class TestUserPrompt:

    def test_emotion_context_in_each_unit(self) -> None:
        """Cada unidad del prompt incluye experienciador + tipo + modo + frase."""
        backend = _FakeBackend([
            ListaCaracterizacionBatchSchema(root=[
                CaracterizacionBatchItemSchema(
                    unit_idx=0,
                    caracterizacion=_make_caracterizacion(),
                ),
            ]),
        ])
        agent = CharacterizerAgent(backend)
        df = pd.DataFrame([
            {
                "codigo": "DISC_A",
                "frase": "Tengo miedo del futuro.",
                "experienciador": "el orador",
                "tipo_emocion": "miedo",
                "modo_existencia": "realizada",
            },
        ])
        agent.run(df)

        user = backend.calls[0]["user"]
        # Verifica que toda la información contextual de la emoción
        # esté presente.
        assert "DISC_A" in user
        assert "el orador" in user
        assert "miedo" in user
        assert "realizada" in user
        assert "Tengo miedo del futuro." in user

    def test_unit_indexed_zero_based(self) -> None:
        backend = _FakeBackend([
            ListaCaracterizacionBatchSchema(root=[
                CaracterizacionBatchItemSchema(
                    unit_idx=0, caracterizacion=_make_caracterizacion(),
                ),
                CaracterizacionBatchItemSchema(
                    unit_idx=1, caracterizacion=_make_caracterizacion(),
                ),
            ]),
        ])
        agent = CharacterizerAgent(backend)
        df = pd.DataFrame([
            {"codigo": "A", "frase": "f0", "experienciador": "X",
             "tipo_emocion": "alegria", "modo_existencia": "realizada"},
            {"codigo": "A", "frase": "f1", "experienciador": "Y",
             "tipo_emocion": "tristeza", "modo_existencia": "realizada"},
        ])
        agent.run(df)

        user = backend.calls[0]["user"]
        # En este agente, el "unit" es una emoción → numerada como
        # EMOCIÓN [0], EMOCIÓN [1].
        assert "EMOCIÓN [0]" in user
        assert "EMOCIÓN [1]" in user


class TestOutputMapping:

    def test_all_output_columns_added(self) -> None:
        backend = _FakeBackend([
            ListaCaracterizacionBatchSchema(root=[
                CaracterizacionBatchItemSchema(
                    unit_idx=0, caracterizacion=_make_caracterizacion(),
                ),
            ]),
        ])
        agent = CharacterizerAgent(backend)
        df = pd.DataFrame([
            {"codigo": "A", "frase": "x", "experienciador": "X",
             "tipo_emocion": "miedo", "modo_existencia": "realizada"},
        ])
        out = agent.run(df)

        for col in CharacterizerAgent.OUTPUT_COLUMNS:
            assert col in out.columns

    def test_values_mapped_from_caracterizacion(self) -> None:
        backend = _FakeBackend([
            ListaCaracterizacionBatchSchema(root=[
                CaracterizacionBatchItemSchema(
                    unit_idx=0,
                    caracterizacion=_make_caracterizacion(
                        foria="euforico",
                        intensidad="baja",
                        tipo_fuente="situacion",
                        fuente="la victoria electoral",
                    ),
                ),
            ]),
        ])
        agent = CharacterizerAgent(backend)
        df = pd.DataFrame([
            {"codigo": "A", "frase": "x", "experienciador": "X",
             "tipo_emocion": "alegria", "modo_existencia": "realizada"},
        ])
        out = agent.run(df)

        assert out.iloc[0]["foria"] == "euforico"
        assert out.iloc[0]["intensidad"] == "baja"
        assert out.iloc[0]["tipo_fuente"] == "situacion"
        assert out.iloc[0]["fuente"] == "la victoria electoral"
        # Las justificaciones también.
        assert "tono negativo" in out.iloc[0]["foria_justificacion"]


class TestPreservesEmotionMetadata:
    """Las columnas de la emoción original (experienciador, tipo, modo)
    se preservan en el output."""

    def test_original_columns_preserved(self) -> None:
        backend = _FakeBackend([
            ListaCaracterizacionBatchSchema(root=[
                CaracterizacionBatchItemSchema(
                    unit_idx=0, caracterizacion=_make_caracterizacion(),
                ),
            ]),
        ])
        agent = CharacterizerAgent(backend)
        df = pd.DataFrame([
            {"codigo": "DISC_A", "frase": "x", "experienciador": "el orador",
             "tipo_emocion": "miedo", "modo_existencia": "realizada"},
        ])
        out = agent.run(df)

        # Originales preservadas.
        assert out.iloc[0]["codigo"] == "DISC_A"
        assert out.iloc[0]["experienciador"] == "el orador"
        assert out.iloc[0]["tipo_emocion"] == "miedo"
        assert out.iloc[0]["modo_existencia"] == "realizada"
