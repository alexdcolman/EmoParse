# ══════════════════════════════════════════════════════════════════════════════
#  tests.unit.test_base_agent_retry
#
#  Tests de la integración de retry_config en BaseAgent y BaseBatchAgent.
# ══════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

import sys
import types
from unittest.mock import MagicMock, call, patch

import pytest

loguru_mod = types.ModuleType("loguru")
loguru_mod.logger = MagicMock()
sys.modules.setdefault("loguru", loguru_mod)

try:
    import pandas as pd
except ImportError:
    pytest.skip("pandas no disponible", allow_module_level=True)

try:
    from pydantic import BaseModel, RootModel
except ImportError:
    pytest.skip("pydantic no disponible", allow_module_level=True)

try:
    from emoparse.core.backend.exceptions import (
        BackendError,
        PermanentBackendError,
        TransientBackendError,
    )
except ModuleNotFoundError:
    class BackendError(Exception): pass
    class TransientBackendError(BackendError): pass
    class PermanentBackendError(BackendError): pass

    exc_mod = types.ModuleType("emoparse.core.backend.exceptions")
    exc_mod.BackendError = BackendError
    exc_mod.TransientBackendError = TransientBackendError
    exc_mod.PermanentBackendError = PermanentBackendError
    for name in ["emoparse", "emoparse.core", "emoparse.core.backend"]:
        sys.modules.setdefault(name, types.ModuleType(name))
    sys.modules["emoparse.core.backend.exceptions"] = exc_mod

from emoparse.core.backend.retry import RetryConfig, retry_with_backoff
from emoparse.agents.base import BaseAgent, BaseBatchAgent


# ── Schemas de prueba ─────────────────────────────────────────────────────────

class DummySchema(BaseModel):
    value: str


class DummyBatchItem(BaseModel):
    unit_idx: int
    value: str


class DummyBatchSchema(RootModel[list[DummyBatchItem]]):
    pass


# ── Implementaciones concretas mínimas ───────────────────────────────────────

class ConcreteAgent(BaseAgent[DummySchema]):
    NAME = "test_agent"
    SCHEMA = DummySchema
    OUTPUT_COLUMNS = ("value",)

    def _build_system(self) -> str:
        return "system"

    def _build_user(self, row):
        return f"user: {row.get('text', '')}"

    def _map_to_columns(self, parsed, row):
        return {"value": parsed.value}


class ConcreteBatchAgent(BaseBatchAgent[DummyBatchSchema]):
    NAME = "test_batch_agent"
    SCHEMA = DummyBatchSchema
    OUTPUT_COLUMNS = ("value",)
    BATCH_SIZE = 2

    def _build_system(self) -> str:
        return "system"

    def _build_user(self, batch) -> str:
        return "user"

    def _map_item_to_columns(self, item, row):
        return {"value": item.value}


def _make_response(schema_instance):
    """Construye un LLMResponse mock."""
    r = MagicMock()
    r.parsed = schema_instance
    r.model_alias = "test_model"
    return r


# ── Tests BaseAgent con retry_config ─────────────────────────────────────────

class TestBaseAgentRetry:

    def _make_backend(self, side_effects):
        backend = MagicMock()
        backend.generate.side_effect = side_effects
        return backend

    def test_retry_config_none_no_retry_on_transient(self):
        """Sin retry_config, TransientBackendError se propaga en el primer fallo."""
        backend = self._make_backend([TransientBackendError("timeout")])
        agent = ConcreteAgent(backend, retry_config=None)
        with pytest.raises(TransientBackendError):
            agent.process_unit(pd.Series({"text": "hola"}))
        backend.generate.assert_called_once()

    def test_retry_config_retries_on_transient_then_succeeds(self):
        """Con retry_config, falla 2 veces (Transient) y luego succeed."""
        backend = self._make_backend([
            TransientBackendError("timeout"),
            TransientBackendError("timeout"),
            _make_response(DummySchema(value="resultado")),
        ])
        sleep_mock = MagicMock()
        cfg = RetryConfig(max_retries=3, delays_seconds=[1, 2, 4])

        with patch("emoparse.core.backend.retry.time.sleep", sleep_mock):
            agent = ConcreteAgent(backend, retry_config=cfg)
            result = agent.process_unit(pd.Series({"text": "hola"}))

        assert result.value == "resultado"
        assert backend.generate.call_count == 3
        assert sleep_mock.call_count == 2

    def test_retry_config_does_not_retry_permanent(self):
        """Con retry_config, PermanentBackendError se propaga sin reintentar."""
        backend = self._make_backend([PermanentBackendError("schema")])
        cfg = RetryConfig(max_retries=3, delays_seconds=[1])
        sleep_mock = MagicMock()
        with patch("emoparse.core.backend.retry.time.sleep", sleep_mock):
            agent = ConcreteAgent(backend, retry_config=cfg)
            with pytest.raises(PermanentBackendError):
                agent.process_unit(pd.Series({"text": "hola"}))
        backend.generate.assert_called_once()
        sleep_mock.assert_not_called()

    def test_run_catches_transient_after_retries_exhausted(self):
        """run() atrapa el TransientBackendError final y rellena con None."""
        # Siempre falla — agota los reintentos.
        backend = self._make_backend([TransientBackendError("fail")] * 10)
        cfg = RetryConfig(max_retries=2, delays_seconds=[0])
        with patch("emoparse.core.backend.retry.time.sleep"):
            agent = ConcreteAgent(backend, retry_config=cfg)
            df_in = pd.DataFrame([{"text": "hola", "codigo": "D001"}])
            df_out = agent.run(df_in)
        assert df_out.iloc[0]["value"] is None

    def test_default_behavior_unchanged_without_retry_config(self):
        """Comportamiento default (sin retry_config) idéntico al original."""
        response = _make_response(DummySchema(value="ok"))
        backend = self._make_backend([response])
        agent = ConcreteAgent(backend)  # sin retry_config
        result = agent.process_unit(pd.Series({"text": "test"}))
        assert result.value == "ok"
        backend.generate.assert_called_once()


# ── Tests BaseBatchAgent con retry_config ─────────────────────────────────────

class TestBaseBatchAgentRetry:

    def _make_backend(self, side_effects):
        backend = MagicMock()
        backend.generate.side_effect = side_effects
        return backend

    def test_retry_config_retries_batch_on_transient_then_succeeds(self):
        """En un batch, reintenta ante TransientBackendError y tiene éxito."""
        ok_response = _make_response(
            DummyBatchSchema(root=[
                DummyBatchItem(unit_idx=0, value="a"),
                DummyBatchItem(unit_idx=1, value="b"),
            ])
        )
        backend = self._make_backend([
            TransientBackendError("timeout"),
            ok_response,
        ])
        cfg = RetryConfig(max_retries=2, delays_seconds=[0])
        with patch("emoparse.core.backend.retry.time.sleep"):
            agent = ConcreteBatchAgent(backend, retry_config=cfg)
            df_in = pd.DataFrame([
                {"codigo": "D1", "unit_idx": 0, "text": "x"},
                {"codigo": "D1", "unit_idx": 1, "text": "y"},
            ])
            df_out = agent.run(df_in)
        assert list(df_out["value"]) == ["a", "b"]
        assert backend.generate.call_count == 2

    def test_no_retry_config_batch_fails_on_transient(self):
        """Sin retry_config, TransientBackendError deja el batch en None."""
        backend = self._make_backend([TransientBackendError("timeout")])
        agent = ConcreteBatchAgent(backend, retry_config=None)
        df_in = pd.DataFrame([
            {"codigo": "D1", "unit_idx": 0, "text": "x"},
        ])
        df_out = agent.run(df_in)
        assert df_out.iloc[0]["value"] is None
