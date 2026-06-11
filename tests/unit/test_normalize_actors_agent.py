# ══════════════════════════════════════════════════════════════════════════════
#  tests.unit.test_normalize_actors_agent
#
#  Tests del NormalizeActorsAgent: prompts correctos, mapeo a columnas,
#  manejo de KB serializada, casos límite de actores_a_linkear.
# ══════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

import json
from typing import TypeVar

import pandas as pd
import pytest
from pydantic import BaseModel

from emoparse.agents.normalize_actors import NormalizeActorsAgent
from emoparse.core.backend.base import LLMBackend, LLMResponse, TokenUsage
from emoparse.core.schemas import (
    ActorLinkingBatchItemSchema,
    ActorLinkingSchema,
    ListaActorLinkingBatchSchema,
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


def _resp(items: list[ActorLinkingBatchItemSchema]) -> ListaActorLinkingBatchSchema:
    return ListaActorLinkingBatchSchema(root=items)


# ══════════════════════════════════════════════════════════════════════════════


class TestSystemPrompt:

    def test_includes_kb_serialized(self) -> None:
        kb = (
            "- javier_milei [tipo=individuo]: Javier Milei | aliases: Milei; el presidente\n"
            "- gobierno_argentino [tipo=institucion]: Gobierno argentino | aliases: el gobierno"
        )
        backend = _FakeBackend([_resp([
            ActorLinkingBatchItemSchema(unit_idx=0, linkings=[]),
        ])])
        agent = NormalizeActorsAgent(backend, actors_kb_serialized=kb)
        df = pd.DataFrame([{
            "codigo": "DISC_001",
            "unit_idx": 0,
            "frase": "Hola.",
            "actores_a_linkear": json.dumps([{"actor": "Milei", "tipo": "individuo"}]),
        }])
        agent.run(df)

        system = backend.calls[0]["system"]
        assert "javier_milei" in system
        assert "Milei" in system
        assert "gobierno_argentino" in system


class TestUserPrompt:

    def test_units_numbered_zero_based(self) -> None:
        backend = _FakeBackend([_resp([
            ActorLinkingBatchItemSchema(unit_idx=0, linkings=[]),
            ActorLinkingBatchItemSchema(unit_idx=1, linkings=[]),
        ])])
        agent = NormalizeActorsAgent(backend, actors_kb_serialized="(empty)")
        df = pd.DataFrame([
            {
                "codigo": "A",
                "unit_idx": 0,
                "frase": "primera frase",
                "actores_a_linkear": json.dumps([{"actor": "Milei", "tipo": "?"}]),
            },
            {
                "codigo": "A",
                "unit_idx": 1,
                "frase": "segunda frase",
                "actores_a_linkear": json.dumps([{"actor": "Cristina", "tipo": "?"}]),
            },
        ])
        agent.run(df)

        user = backend.calls[0]["user"]
        assert "UNIDAD [0]" in user
        assert "UNIDAD [1]" in user
        assert "primera frase" in user
        assert "segunda frase" in user
        assert "Milei" in user
        assert "Cristina" in user

    def test_includes_codigo_in_each_unit(self) -> None:
        backend = _FakeBackend([_resp([
            ActorLinkingBatchItemSchema(unit_idx=0, linkings=[]),
        ])])
        agent = NormalizeActorsAgent(backend, actors_kb_serialized="(empty)")
        df = pd.DataFrame([{
            "codigo": "DISC_XYZ",
            "unit_idx": 0,
            "frase": "x",
            "actores_a_linkear": json.dumps([{"actor": "Milei", "tipo": "?"}]),
        }])
        agent.run(df)

        user = backend.calls[0]["user"]
        assert "DISC_XYZ" in user


class TestOutputMapping:

    def test_linkings_serialized_as_json(self) -> None:
        backend = _FakeBackend([_resp([
            ActorLinkingBatchItemSchema(
                unit_idx=0,
                linkings=[
                    ActorLinkingSchema(
                        actor_mencionado="Milei",
                        actor_canonico="javier_milei",
                        confianza="alta",
                        es_nuevo=False,
                        justificacion="Alias directo en KB.",
                        canonical_id_sugerido=None,
                        display_name_sugerido=None,
                        tipo_sugerido=None,
                    )
                ],
            ),
        ])])
        agent = NormalizeActorsAgent(backend, actors_kb_serialized="(empty)")
        df = pd.DataFrame([{
            "codigo": "A",
            "unit_idx": 0,
            "frase": "x",
            "actores_a_linkear": json.dumps([{"actor": "Milei", "tipo": "?"}]),
        }])
        out = agent.run(df)

        canonicos_str = out.iloc[0]["actores_canonicos"]
        assert isinstance(canonicos_str, str)

        parsed = json.loads(canonicos_str)
        assert len(parsed) == 1
        assert parsed[0]["actor_canonico"] == "javier_milei"
        assert parsed[0]["confianza"] == "alta"
        assert parsed[0]["es_nuevo"] is False

    def test_es_nuevo_when_no_match(self) -> None:
        backend = _FakeBackend([_resp([
            ActorLinkingBatchItemSchema(
                unit_idx=0,
                linkings=[
                    ActorLinkingSchema(
                        actor_mencionado="Pepito",
                        actor_canonico=None,
                        confianza="alta",
                        es_nuevo=True,
                        justificacion="No matchea con la KB.",
                        canonical_id_sugerido=None,
                        display_name_sugerido=None,
                        tipo_sugerido=None,
                    ),
                ],
            ),
        ])])
        agent = NormalizeActorsAgent(backend, actors_kb_serialized="(empty)")
        df = pd.DataFrame([{
            "codigo": "A",
            "unit_idx": 0,
            "frase": "x",
            "actores_a_linkear": json.dumps([{"actor": "Pepito", "tipo": "?"}]),
        }])
        out = agent.run(df)

        parsed = json.loads(out.iloc[0]["actores_canonicos"])
        assert parsed[0]["actor_canonico"] is None
        assert parsed[0]["es_nuevo"] is True


class TestActoresFormatting:

    def test_handles_missing_actores_a_linkear(self) -> None:
        """Si actores_a_linkear es string vacío o None, el prompt no rompe."""
        backend = _FakeBackend([_resp([
            ActorLinkingBatchItemSchema(unit_idx=0, linkings=[]),
        ])])
        agent = NormalizeActorsAgent(backend, actors_kb_serialized="(empty)")
        df = pd.DataFrame([{
            "codigo": "A",
            "unit_idx": 0,
            "frase": "x",
            "actores_a_linkear": None,
        }])
        # No debe lanzar.
        agent.run(df)
        user = backend.calls[0]["user"]
        assert "(sin actores)" in user

    def test_handles_malformed_json(self) -> None:
        backend = _FakeBackend([_resp([
            ActorLinkingBatchItemSchema(unit_idx=0, linkings=[]),
        ])])
        agent = NormalizeActorsAgent(backend, actors_kb_serialized="(empty)")
        df = pd.DataFrame([{
            "codigo": "A",
            "unit_idx": 0,
            "frase": "x",
            "actores_a_linkear": "{esto no es JSON",
        }])
        agent.run(df)
        user = backend.calls[0]["user"]
        assert "error de parseo" in user
