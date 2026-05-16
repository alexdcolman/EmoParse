# ══════════════════════════════════════════════════════════════════════════════
#  tests.unit.test_characterizer_includes_tier1
#
#  Verifica que CharacterizerAgent produce los 4 campos nuevos de Tier 1
#  y que el system prompt los incluye.
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


def _make_carac(**overrides) -> CaracterizacionEmocionSchema:
    base = {
        "foria": "euforico",
        "foria_justificacion": "jus foria",
        "dominancia": "cognoscitiva",
        "dominancia_justificacion": "jus dom",
        "intensidad": "alta",
        "intensidad_justificacion": "jus int",
        "fuente": "el acuerdo",
        "tipo_fuente": "situacion",
        "fuente_justificacion": "jus fuente",
        "duracion": "durable",
        "duracion_justificacion": "jus dur",
        "modo_semiotizacion": "dicha",
        "modo_semiotizacion_justificacion": "jus semiot",
        "modo_identificacion": "directa",
        "modo_identificacion_justificacion": "jus iden",
        "tipo_atribucion": "auto_atribucion",
        "tipo_atribucion_justificacion": "jus atr",
    }
    base.update(overrides)
    return CaracterizacionEmocionSchema(**base)


def _resp(items: list[CaracterizacionBatchItemSchema]) -> ListaCaracterizacionBatchSchema:
    return ListaCaracterizacionBatchSchema(root=items)


# ── Tests ─────────────────────────────────────────────────────────────────────

class TestCharacterizerTier1Output:

    def test_output_columns_include_tier1(self) -> None:
        """OUTPUT_COLUMNS declara los 8 campos nuevos."""
        cols = CharacterizerAgent.OUTPUT_COLUMNS
        for field in (
            "duracion", "duracion_justificacion",
            "modo_semiotizacion", "modo_semiotizacion_justificacion",
            "modo_identificacion", "modo_identificacion_justificacion",
            "tipo_atribucion", "tipo_atribucion_justificacion",
        ):
            assert field in cols, f"Campo Tier 1 ausente en OUTPUT_COLUMNS: {field}"

    def test_agent_produces_tier1_columns(self) -> None:
        """El DataFrame de salida contiene los 4 campos Tier 1."""
        carac = _make_carac()
        backend = _FakeBackend([
            _resp([CaracterizacionBatchItemSchema(unit_idx=0, caracterizacion=carac)]),
        ])
        agent = CharacterizerAgent(backend)
        df_in = pd.DataFrame([{
            "codigo": "A",
            "frase": "El presidente habló con orgullo.",
            "experienciador": "el presidente",
            "tipo_emocion": "orgullo",
            "modo_existencia": "realizada",
            "frase_idx": 0,
            "emocion_idx": 0,
        }])
        df_out = agent.run(df_in)

        for col in ("duracion", "modo_semiotizacion", "modo_identificacion", "tipo_atribucion"):
            assert col in df_out.columns, f"Columna Tier 1 ausente en output: {col}"

        row = df_out.iloc[0]
        assert row["duracion"] == "durable"
        assert row["modo_semiotizacion"] == "dicha"
        assert row["modo_identificacion"] == "directa"
        assert row["tipo_atribucion"] == "auto_atribucion"
        assert row["duracion_justificacion"] == "jus dur"
        assert row["tipo_atribucion_justificacion"] == "jus atr"

    def test_system_prompt_mentions_tier1_dimensions(self) -> None:
        """El system prompt incluye las 4 dimensiones Tier 1."""
        carac = _make_carac()
        backend = _FakeBackend([
            _resp([CaracterizacionBatchItemSchema(unit_idx=0, caracterizacion=carac)]),
        ])
        agent = CharacterizerAgent(backend, titulo="T", tipo_discurso="td")
        df_in = pd.DataFrame([{
            "codigo": "A",
            "frase": "x",
            "experienciador": "y",
            "tipo_emocion": "miedo",
            "modo_existencia": "realizada",
            "frase_idx": 0,
            "emocion_idx": 0,
        }])
        agent.run(df_in)

        system = backend.calls[0]["system"]
        for keyword in ("DURACION", "MODO_SEMIOTIZACION", "MODO_IDENTIFICACION", "TIPO_ATRIBUCION"):
            assert keyword in system, f"Keyword '{keyword}' ausente en system prompt"
