# ══════════════════════════════════════════════════════════════════════════════
#  tests.unit.test_actors_agent
#
#  Tests para el ActorsAgent: prompts correctos, mapeo de items a columnas,
#  formato del bloque de unidades.
# ══════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

import json
from typing import TypeVar

import pandas as pd
import pytest
from pydantic import BaseModel

from emoparse.agents.actors import ActorsAgent
from emoparse.core.backend.base import LLMBackend, LLMResponse, TokenUsage
from emoparse.core.schemas import (
    ActorSchema,
    ActoresBatchItemSchema,
    ListaActoresBatchSchema,
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
        self.calls.append({"system": system, "user": user, "schema": schema})
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


def _resp(items: list[ActoresBatchItemSchema]) -> ListaActoresBatchSchema:
    return ListaActoresBatchSchema(root=items)


# ══════════════════════════════════════════════════════════════════════════════


class TestSystemPrompt:

    def test_includes_context_from_constructor(self) -> None:
        backend = _FakeBackend([
            _resp([
                ActoresBatchItemSchema(unit_idx=0, actores=[]),
            ]),
        ])
        agent = ActorsAgent(
            backend,
            titulo="Asunción Presidencial 2024",
            tipo_discurso="asuncion",
            enunciador="Presidente X",
        )
        df = pd.DataFrame([{"codigo": "DISC_001", "frase": "Hola."}])
        agent.run(df)

        system = backend.calls[0]["system"]
        assert "Asunción Presidencial 2024" in system
        assert "asuncion" in system
        assert "Presidente X" in system


class TestUserPrompt:

    def test_units_numbered_zero_based(self) -> None:
        backend = _FakeBackend([
            _resp([
                ActoresBatchItemSchema(unit_idx=0, actores=[]),
                ActoresBatchItemSchema(unit_idx=1, actores=[]),
                ActoresBatchItemSchema(unit_idx=2, actores=[]),
            ]),
        ])
        agent = ActorsAgent(backend)
        df = pd.DataFrame([
            {"codigo": "A", "frase": "primera frase"},
            {"codigo": "A", "frase": "segunda frase"},
            {"codigo": "A", "frase": "tercera frase"},
        ])
        agent.run(df)

        user = backend.calls[0]["user"]
        assert "UNIDAD [0]" in user
        assert "UNIDAD [1]" in user
        assert "UNIDAD [2]" in user
        assert "primera frase" in user
        assert "tercera frase" in user

    def test_codigo_included_in_each_unit(self) -> None:
        backend = _FakeBackend([
            _resp([ActoresBatchItemSchema(unit_idx=0, actores=[])]),
        ])
        agent = ActorsAgent(backend)
        df = pd.DataFrame([{"codigo": "DISC_XYZ", "frase": "x"}])
        agent.run(df)

        user = backend.calls[0]["user"]
        assert "DISC_XYZ" in user


class TestOutputMapping:

    def test_actors_serialized_as_json(self) -> None:
        backend = _FakeBackend([
            _resp([
                ActoresBatchItemSchema(
                    unit_idx=0,
                    actores=[
                        ActorSchema(
                            marca="el presidente",
                            actor="el presidente",
                            tipo="humano_individual",
                            modo="explicito",
                            justificacion="Mencionado por nombre.",
                        ),
                        ActorSchema(
                            marca="el pueblo",
                            actor="el pueblo",
                            tipo="colectivo",
                            modo="inferido",
                            justificacion="Apelación implícita.",
                        ),
                    ],
                ),
            ]),
        ])
        agent = ActorsAgent(backend)
        df = pd.DataFrame([{"codigo": "A", "frase": "x"}])
        out = agent.run(df)

        actores_str = out.iloc[0]["actores"]
        assert isinstance(actores_str, str)

        parsed = json.loads(actores_str)
        assert len(parsed) == 2
        assert parsed[0]["actor"] == "el presidente"
        assert parsed[0]["tipo"] == "humano_individual"
        assert parsed[1]["marca"] == "el pueblo"
        assert parsed[1]["modo"] == "inferido"

    def test_empty_actors_list_serialized_as_empty_json_list(self) -> None:
        """Frases sin actores: lista vacía, NO None.

        Distinción crítica: lista vacía = "el modelo procesó y dijo
        que no hay actores"; None = "hubo error técnico".
        """
        backend = _FakeBackend([
            _resp([ActoresBatchItemSchema(unit_idx=0, actores=[])]),
        ])
        agent = ActorsAgent(backend)
        df = pd.DataFrame([{"codigo": "A", "frase": "Llovió."}])
        out = agent.run(df)

        actores_str = out.iloc[0]["actores"]
        # No debe ser None ni NaN.
        assert actores_str is not None
        assert not (isinstance(actores_str, float) and pd.isna(actores_str))
        # Debe ser "[]" parseable.
        assert json.loads(actores_str) == []
