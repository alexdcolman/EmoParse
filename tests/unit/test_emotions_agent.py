# ══════════════════════════════════════════════════════════════════════════════
#  tests.unit.test_emotions_agent
#
#  Específicos: que la ontología y heurísticas estén en el system,
#  que los actores previos se inyecten correctamente en el user,
#  que el output sea JSON list parseable.
# ══════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

import json
from typing import TypeVar

import pandas as pd
from pydantic import BaseModel

from emoparse.agents.emotions import EmotionsAgent
from emoparse.core.backend.base import LLMBackend, LLMResponse, TokenUsage
from emoparse.core.schemas import (
    EmocionesBatchItemSchema,
    EmocionSchema,
    ListaEmocionesBatchSchema,
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


def _resp(items: list[EmocionesBatchItemSchema]) -> ListaEmocionesBatchSchema:
    return ListaEmocionesBatchSchema(root=items)


# ══════════════════════════════════════════════════════════════════════════════


class TestSystemPrompt:

    def test_includes_ontology_and_heuristics(self) -> None:
        backend = _FakeBackend([
            _resp([EmocionesBatchItemSchema(unit_idx=0, emociones=[])]),
        ])
        agent = EmotionsAgent(
            backend,
            ontologia="ONTOLOGIA_MARK",
            heuristicas="HEURISTICAS_MARK",
            titulo="T", tipo_discurso="td", enunciador="E",
        )
        df = pd.DataFrame([{"codigo": "A", "frase": "x"}])
        agent.run(df)

        system = backend.calls[0]["system"]
        assert "ONTOLOGIA_MARK" in system
        assert "HEURISTICAS_MARK" in system


class TestUserPrompt:

    def test_actors_injected_per_unit(self) -> None:
        """Cada unidad del user incluye los actores previamente identificados."""
        backend = _FakeBackend([
            _resp([
                EmocionesBatchItemSchema(unit_idx=0, emociones=[]),
                EmocionesBatchItemSchema(unit_idx=1, emociones=[]),
            ]),
        ])
        agent = EmotionsAgent(backend, ontologia="o", heuristicas="h")
        df = pd.DataFrame([
            {
                "codigo": "A", "frase": "frase 0",
                "actores": json.dumps([
                    {"actor": "el pueblo", "tipo": "colectivo", "modo": "explicito",
                     "justificacion": "x"},
                ]),
            },
            {
                "codigo": "A", "frase": "frase 1",
                "actores": json.dumps([
                    {"actor": "Juan", "tipo": "humano_individual", "modo": "explicito",
                     "justificacion": "y"},
                ]),
            },
        ])
        agent.run(df)

        user = backend.calls[0]["user"]
        # Cada actor formateado como "Nombre (tipo)".
        assert "el pueblo (colectivo)" in user
        assert "Juan (humano_individual)" in user

    def test_no_actors_column_marks_as_not_processed(self) -> None:
        """Si la fila no tiene 'actores' (None/NaN), se indica explícitamente."""
        backend = _FakeBackend([
            _resp([EmocionesBatchItemSchema(unit_idx=0, emociones=[])]),
        ])
        agent = EmotionsAgent(backend, ontologia="o", heuristicas="h")
        df = pd.DataFrame([
            {"codigo": "A", "frase": "x", "actores": None},
        ])
        agent.run(df)

        user = backend.calls[0]["user"]
        assert "no procesados" in user

    def test_empty_actors_list_shows_none_identified(self) -> None:
        """Lista vacía de actores = "ninguno identificado"."""
        backend = _FakeBackend([
            _resp([EmocionesBatchItemSchema(unit_idx=0, emociones=[])]),
        ])
        agent = EmotionsAgent(backend, ontologia="o", heuristicas="h")
        df = pd.DataFrame([
            {"codigo": "A", "frase": "x", "actores": "[]"},
        ])
        agent.run(df)

        user = backend.calls[0]["user"]
        assert "ninguno identificado" in user


class TestOutputMapping:

    def test_emotions_serialized_as_json(self) -> None:
        backend = _FakeBackend([
            _resp([
                EmocionesBatchItemSchema(
                    unit_idx=0,
                    emociones=[
                        EmocionSchema(
                            experienciador="el presidente",
                            tipo_emocion="orgullo",
                            modo_existencia="realizada",
                            justificacion="Habla con voz firme y sonríe.",
                        ),
                    ],
                ),
            ]),
        ])
        agent = EmotionsAgent(backend, ontologia="o", heuristicas="h")
        df = pd.DataFrame([{"codigo": "A", "frase": "x", "actores": "[]"}])
        out = agent.run(df)

        emociones_str = out.iloc[0]["emociones"]
        parsed = json.loads(emociones_str)
        assert len(parsed) == 1
        assert parsed[0]["tipo_emocion"] == "orgullo"
        assert parsed[0]["modo_existencia"] == "realizada"
