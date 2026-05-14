# ══════════════════════════════════════════════════════════════════════════════
#  tests.unit.test_base_agent
#
#  Tests de la abstracción BaseAgent, usando un agente concreto trivial
#  para validar el comportamiento común (loop, error handling, df
#  operations) independientemente de los agentes de producción.
# ══════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

from typing import Any, TypeVar

import pandas as pd
import pytest
from pydantic import BaseModel, Field

from emoparse.agents.base import BaseAgent, BaseBatchAgent
from emoparse.core.backend.base import LLMBackend, LLMResponse, TokenUsage
from emoparse.core.backend.exceptions import BackendTimeoutError
from emoparse.core.schemas import StrictBase

T = TypeVar("T", bound=BaseModel)


# ══════════════════════════════════════════════════════════════════════════════
#  Schemas y agentes de prueba
# ══════════════════════════════════════════════════════════════════════════════


class _TrivialSchema(StrictBase):
    """Schema mínimo para tests del BaseAgent."""
    valor: str = Field(description="Un valor cualquiera")
    longitud: int = Field(description="La longitud del valor")


class _TrivialAgent(BaseAgent[_TrivialSchema]):
    """Agente concreto trivial para testing."""

    NAME = "trivial"
    SCHEMA = _TrivialSchema
    OUTPUT_COLUMNS = ("valor_calc", "longitud_calc")

    def __init__(self, backend: LLMBackend, system_extra: str = "") -> None:
        self._extra = system_extra
        super().__init__(backend)

    def _build_system(self) -> str:
        return f"system_base|{self._extra}"

    def _build_user(self, row: pd.Series) -> str:
        return f"user_for_{row['codigo']}"

    def _map_to_columns(
        self,
        parsed: _TrivialSchema,
        row: pd.Series,
    ) -> dict[str, Any]:
        return {
            "valor_calc": parsed.valor,
            "longitud_calc": parsed.longitud,
        }


# ══════════════════════════════════════════════════════════════════════════════
#  FakeBackend reutilizable
# ══════════════════════════════════════════════════════════════════════════════


class _FakeBackend(LLMBackend):
    """Cola de respuestas; cada generate() consume una."""

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
        self.calls.append({
            "system": system, "user": user, "schema": schema,
            "reset_before": reset_before,
        })
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
#  Tests del BaseAgent
# ══════════════════════════════════════════════════════════════════════════════


class TestBaseAgentBasics:

    def test_system_built_once_in_init(self) -> None:
        """El system se construye en __init__, no por llamada."""
        backend = _FakeBackend([
            _TrivialSchema(valor="x", longitud=1),
            _TrivialSchema(valor="y", longitud=1),
        ])
        agent = _TrivialAgent(backend, system_extra="MARK")
        df = pd.DataFrame([{"codigo": "A"}, {"codigo": "B"}])
        agent.run(df)

        # Las dos llamadas comparten el system idéntico, con la marca.
        assert len(backend.calls) == 2
        assert backend.calls[0]["system"] == backend.calls[1]["system"]
        assert "MARK" in backend.calls[0]["system"]

    def test_user_varies_per_row(self) -> None:
        backend = _FakeBackend([
            _TrivialSchema(valor="x", longitud=1),
            _TrivialSchema(valor="y", longitud=1),
        ])
        agent = _TrivialAgent(backend)
        df = pd.DataFrame([{"codigo": "FIRST"}, {"codigo": "SECOND"}])
        agent.run(df)

        assert "FIRST" in backend.calls[0]["user"]
        assert "SECOND" in backend.calls[1]["user"]

    def test_schema_passed_in_each_call(self) -> None:
        backend = _FakeBackend([_TrivialSchema(valor="x", longitud=1)])
        agent = _TrivialAgent(backend)
        agent.run(pd.DataFrame([{"codigo": "A"}]))

        assert backend.calls[0]["schema"] is _TrivialSchema


class TestBaseAgentDataFrameOperations:

    def test_output_columns_added(self) -> None:
        backend = _FakeBackend([
            _TrivialSchema(valor="hola", longitud=4),
        ])
        agent = _TrivialAgent(backend)
        out = agent.run(pd.DataFrame([{"codigo": "A"}]))

        for col in _TrivialAgent.OUTPUT_COLUMNS:
            assert col in out.columns

    def test_values_mapped_correctly(self) -> None:
        backend = _FakeBackend([
            _TrivialSchema(valor="hola", longitud=4),
        ])
        agent = _TrivialAgent(backend)
        out = agent.run(pd.DataFrame([{"codigo": "A"}]))

        assert out.iloc[0]["valor_calc"] == "hola"
        assert out.iloc[0]["longitud_calc"] == 4

    def test_original_columns_preserved(self) -> None:
        backend = _FakeBackend([_TrivialSchema(valor="x", longitud=1)])
        agent = _TrivialAgent(backend)
        df = pd.DataFrame([{"codigo": "A", "extra": "preservar"}])
        out = agent.run(df)

        assert out.iloc[0]["codigo"] == "A"
        assert out.iloc[0]["extra"] == "preservar"

    def test_row_order_preserved(self) -> None:
        backend = _FakeBackend([
            _TrivialSchema(valor=f"v{i}", longitud=i)
            for i in range(5)
        ])
        agent = _TrivialAgent(backend)
        df = pd.DataFrame([{"codigo": f"R{i}"} for i in range(5)])
        out = agent.run(df)

        assert list(out["codigo"]) == ["R0", "R1", "R2", "R3", "R4"]
        assert list(out["longitud_calc"]) == [0, 1, 2, 3, 4]


class TestBaseAgentErrorHandling:

    def test_run_continues_after_single_error(self) -> None:
        backend = _FakeBackend([
            BackendTimeoutError("simulated"),
            _TrivialSchema(valor="x", longitud=1),
        ])
        agent = _TrivialAgent(backend)
        df = pd.DataFrame([{"codigo": "A"}, {"codigo": "B"}])
        out = agent.run(df)

        # Fila 0: falló, columnas en None.
        assert pd.isna(out.iloc[0]["valor_calc"])
        # Fila 1: ok.
        assert out.iloc[1]["valor_calc"] == "x"

    def test_process_unit_propagates_error(self) -> None:
        """process_unit no atrapa errores: los propaga al caller."""
        backend = _FakeBackend([BackendTimeoutError("up")])
        agent = _TrivialAgent(backend)
        with pytest.raises(BackendTimeoutError):
            agent.process_unit(pd.Series({"codigo": "A"}))


class TestBaseAgentEdgeCases:

    def test_empty_df_returns_with_columns(self) -> None:
        backend = _FakeBackend([])
        agent = _TrivialAgent(backend)
        out = agent.run(pd.DataFrame(columns=["codigo"]))

        for col in _TrivialAgent.OUTPUT_COLUMNS:
            assert col in out.columns
        assert len(out) == 0

    def test_no_calls_on_empty_df(self) -> None:
        backend = _FakeBackend([])
        agent = _TrivialAgent(backend)
        agent.run(pd.DataFrame(columns=["codigo"]))
        assert backend.calls == []
