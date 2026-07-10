# ══════════════════════════════════════════════════════════════════════════════
#  tests.unit.test_base_batch_agent
#
#  Tests específicos del comportamiento de BaseBatchAgent:
#  - Particionamiento del DF en batches.
#  - Validación de cobertura de unit_idx.
#  - Comportamiento ante items missing/duplicados/fuera de rango.
#  - Preservación del orden original.
# ══════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

from typing import Any, TypeVar

import pandas as pd
import pytest
from pydantic import BaseModel, Field, RootModel

from emoparse.agents.base import BaseBatchAgent
from emoparse.core.backend.base import LLMBackend, LLMResponse, TokenUsage
from emoparse.core.backend.exceptions import BackendTimeoutError
from emoparse.core.schemas import StrictBase

T = TypeVar("T", bound=BaseModel)


# ══════════════════════════════════════════════════════════════════════════════
#  Schemas de prueba
# ══════════════════════════════════════════════════════════════════════════════


class _BatchItem(StrictBase):
    """Item de batch trivial: unit_idx + un payload."""
    unit_idx: int = Field(description="Índice 0-based")
    payload: str = Field(description="Algún valor")


class _BatchSchema(RootModel[list[_BatchItem]]):
    """Top-level: lista de items."""


class _BatchAgent(BaseBatchAgent[_BatchSchema]):
    """Agente batch concreto trivial para tests."""

    NAME = "trivial_batch"
    SCHEMA = _BatchSchema
    OUTPUT_COLUMNS = ("payload_out",)
    BATCH_SIZE = 3

    def _build_system(self) -> str:
        return "system_batch"

    def _build_user(self, batch: pd.DataFrame) -> str:
        return f"user_batch_{len(batch)}_rows"

    def _map_item_to_columns(
        self,
        item: _BatchItem,
        row: pd.Series,
    ) -> dict[str, Any]:
        return {"payload_out": item.payload}


# ══════════════════════════════════════════════════════════════════════════════
#  FakeBackend con cola de respuestas (cada llamada = un batch)
# ══════════════════════════════════════════════════════════════════════════════


class _FakeBackend(LLMBackend):

    def __init__(self, responses: list[BaseModel | Exception]) -> None:
        self.alias = "fake"
        self._responses = list(responses)
        self.calls: int = 0

    def generate(
        self,
        system: str,
        user: str,
        *,
        schema: type[T] | None = None,
        max_tokens: int | None = None,
        max_items: int | None = None,
        temperature: float | None = None,
        seed: int | None = None,
        stop: list[str] | None = None,
        reset_before: bool = False,
    ) -> LLMResponse:
        self.calls += 1
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
#  Helpers
# ══════════════════════════════════════════════════════════════════════════════


def _make_batch_response(items: list[tuple[int, str]]) -> _BatchSchema:
    """Construye un _BatchSchema desde una lista de (unit_idx, payload)."""
    return _BatchSchema(root=[
        _BatchItem(unit_idx=idx, payload=pl) for idx, pl in items
    ])


def _make_df(n: int) -> pd.DataFrame:
    return pd.DataFrame([
        {"codigo": f"R{i}", "frase": f"frase_{i}"} for i in range(n)
    ])


# ══════════════════════════════════════════════════════════════════════════════
#  Particionamiento
# ══════════════════════════════════════════════════════════════════════════════


class TestBatching:

    def test_single_batch_when_df_smaller_than_batch_size(self) -> None:
        """DF de 2 con BATCH_SIZE=3 → 1 sola llamada."""
        backend = _FakeBackend([
            _make_batch_response([(0, "p0"), (1, "p1")]),
        ])
        agent = _BatchAgent(backend)
        df = _make_df(2)
        out = agent.run(df)

        assert backend.calls == 1
        assert len(out) == 2
        assert list(out["payload_out"]) == ["p0", "p1"]

    def test_multiple_batches_when_df_larger(self) -> None:
        """DF de 7 con BATCH_SIZE=3 → 3 batches (3 + 3 + 1)."""
        backend = _FakeBackend([
            _make_batch_response([(0, "a"), (1, "b"), (2, "c")]),
            _make_batch_response([(0, "d"), (1, "e"), (2, "f")]),
            _make_batch_response([(0, "g")]),
        ])
        agent = _BatchAgent(backend)
        df = _make_df(7)
        out = agent.run(df)

        assert backend.calls == 3
        assert list(out["payload_out"]) == ["a", "b", "c", "d", "e", "f", "g"]

    def test_exact_batch_boundary(self) -> None:
        """DF de exactamente BATCH_SIZE → 1 batch."""
        backend = _FakeBackend([
            _make_batch_response([(0, "x"), (1, "y"), (2, "z")]),
        ])
        agent = _BatchAgent(backend)
        out = agent.run(_make_df(3))

        assert backend.calls == 1
        assert list(out["payload_out"]) == ["x", "y", "z"]


# ══════════════════════════════════════════════════════════════════════════════
#  Cobertura del batch response
# ══════════════════════════════════════════════════════════════════════════════


class TestCoverage:

    def test_full_coverage(self) -> None:
        backend = _FakeBackend([
            _make_batch_response([(0, "a"), (1, "b"), (2, "c")]),
        ])
        agent = _BatchAgent(backend)
        out = agent.run(_make_df(3))

        assert list(out["payload_out"]) == ["a", "b", "c"]

    def test_missing_item_leaves_none(self) -> None:
        """unit_idx=1 no está en el response → fila 1 queda con None."""
        backend = _FakeBackend([
            _make_batch_response([(0, "a"), (2, "c")]),
        ])
        agent = _BatchAgent(backend)
        out = agent.run(_make_df(3))

        assert out.iloc[0]["payload_out"] == "a"
        assert pd.isna(out.iloc[1]["payload_out"])
        assert out.iloc[2]["payload_out"] == "c"

    def test_extra_item_out_of_range_is_discarded(self) -> None:
        """unit_idx=5 con batch_size=3 → descartado, warning."""
        backend = _FakeBackend([
            _make_batch_response([(0, "a"), (5, "x"), (1, "b"), (2, "c")]),
        ])
        agent = _BatchAgent(backend)
        out = agent.run(_make_df(3))

        # Las 3 filas válidas se mapean; la fuera de rango se descarta.
        assert list(out["payload_out"]) == ["a", "b", "c"]

    def test_negative_unit_idx_discarded(self) -> None:
        backend = _FakeBackend([
            _make_batch_response([(-1, "x"), (0, "a"), (1, "b"), (2, "c")]),
        ])
        agent = _BatchAgent(backend)
        out = agent.run(_make_df(3))

        assert list(out["payload_out"]) == ["a", "b", "c"]

    def test_duplicate_unit_idx_last_wins(self) -> None:
        """Si un unit_idx aparece dos veces, el último gana (con warning)."""
        backend = _FakeBackend([
            _make_batch_response([(0, "first"), (0, "second"), (1, "b"), (2, "c")]),
        ])
        agent = _BatchAgent(backend)
        out = agent.run(_make_df(3))

        # 0 → "second" (último gana).
        assert out.iloc[0]["payload_out"] == "second"
        assert out.iloc[1]["payload_out"] == "b"
        assert out.iloc[2]["payload_out"] == "c"

    def test_total_miss_leaves_all_none(self) -> None:
        """Response vacío → toda la batch en None, no crashea."""
        backend = _FakeBackend([
            _make_batch_response([]),
        ])
        agent = _BatchAgent(backend)
        out = agent.run(_make_df(3))

        for i in range(3):
            assert pd.isna(out.iloc[i]["payload_out"])


# ══════════════════════════════════════════════════════════════════════════════
#  Errores del backend afectan solo al batch que falla
# ══════════════════════════════════════════════════════════════════════════════


class TestErrorIsolation:

    def test_failed_batch_does_not_affect_others(self) -> None:
        """Si batch 1 falla, batch 2 sigue procesando normal."""
        backend = _FakeBackend([
            _make_batch_response([(0, "a"), (1, "b"), (2, "c")]),
            BackendTimeoutError("simulated"),  # batch 2 entero falla
            _make_batch_response([(0, "g")]),
        ])
        agent = _BatchAgent(backend)
        df = _make_df(7)
        out = agent.run(df)

        # Batch 1: ok.
        assert list(out["payload_out"][:3]) == ["a", "b", "c"]
        # Batch 2: todo None.
        for i in range(3, 6):
            assert pd.isna(out.iloc[i]["payload_out"])
        # Batch 3: ok.
        assert out.iloc[6]["payload_out"] == "g"


# ══════════════════════════════════════════════════════════════════════════════
#  Preservación de orden y filas originales
# ══════════════════════════════════════════════════════════════════════════════


class TestOrderPreservation:

    def test_row_order_matches_input(self) -> None:
        """El DF de salida tiene las filas en el MISMO orden que el input."""
        backend = _FakeBackend([
            _make_batch_response([(0, "p0"), (1, "p1"), (2, "p2")]),
            _make_batch_response([(0, "p3"), (1, "p4")]),
        ])
        agent = _BatchAgent(backend)
        df = _make_df(5)
        out = agent.run(df)

        assert list(out["codigo"]) == ["R0", "R1", "R2", "R3", "R4"]

    def test_original_columns_preserved(self) -> None:
        backend = _FakeBackend([
            _make_batch_response([(0, "a"), (1, "b")]),
        ])
        agent = _BatchAgent(backend)
        df = _make_df(2)
        out = agent.run(df)

        assert "codigo" in out.columns
        assert "frase" in out.columns
        assert list(out["frase"]) == ["frase_0", "frase_1"]


# ══════════════════════════════════════════════════════════════════════════════
#  Edge cases
# ══════════════════════════════════════════════════════════════════════════════


class TestEdgeCases:

    def test_empty_df(self) -> None:
        backend = _FakeBackend([])
        agent = _BatchAgent(backend)
        out = agent.run(pd.DataFrame(columns=["codigo"]))
        assert len(out) == 0
        for col in _BatchAgent.OUTPUT_COLUMNS:
            assert col in out.columns
        assert backend.calls == 0
