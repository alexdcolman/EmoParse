# ══════════════════════════════════════════════════════════════════════════════
#  tests/unit/test_retry.py
# ══════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

import pytest
from unittest.mock import MagicMock, call, patch

import sys
import types

loguru_mod = types.ModuleType("loguru")
logger_stub = MagicMock()
loguru_mod.logger = logger_stub
sys.modules.setdefault("loguru", loguru_mod)

try:
    from emoparse.core.backend.exceptions import (
        BackendError,
        BackendTimeoutError,
        PermanentBackendError,
        SchemaViolationError,
        TransientBackendError,
    )
except ModuleNotFoundError:
    class BackendError(Exception): pass
    class TransientBackendError(BackendError): pass
    class PermanentBackendError(BackendError): pass
    class BackendTimeoutError(TransientBackendError): pass
    class SchemaViolationError(PermanentBackendError): pass

    exc_mod = types.ModuleType("emoparse.core.backend.exceptions")
    exc_mod.BackendError = BackendError
    exc_mod.TransientBackendError = TransientBackendError
    exc_mod.PermanentBackendError = PermanentBackendError
    exc_mod.BackendTimeoutError = BackendTimeoutError
    exc_mod.SchemaViolationError = SchemaViolationError
    sys.modules["emoparse"] = types.ModuleType("emoparse")
    sys.modules["emoparse.core"] = types.ModuleType("emoparse.core")
    sys.modules["emoparse.core.backend"] = types.ModuleType("emoparse.core.backend")
    sys.modules["emoparse.core.backend.exceptions"] = exc_mod

from emoparse.core.backend.retry import RetryConfig, retry_with_backoff


# ── RetryConfig ──────────────────────────────────────────────────────────────

class TestRetryConfig:
    def test_valid(self):
        cfg = RetryConfig(max_retries=3, delays_seconds=[2, 8, 15])
        assert cfg.max_retries == 3
        assert cfg.delays_seconds == [2, 8, 15]

    def test_max_retries_zero_is_valid(self):
        cfg = RetryConfig(max_retries=0, delays_seconds=[1])
        assert cfg.max_retries == 0

    def test_negative_max_retries_raises(self):
        with pytest.raises(ValueError, match="max_retries"):
            RetryConfig(max_retries=-1, delays_seconds=[1])

    def test_empty_delays_raises(self):
        with pytest.raises(ValueError, match="delays_seconds"):
            RetryConfig(max_retries=1, delays_seconds=[])

    def test_frozen(self):
        cfg = RetryConfig(max_retries=1, delays_seconds=[1])
        with pytest.raises(Exception):  # dataclass frozen
            cfg.max_retries = 2  # type: ignore


# ── retry_with_backoff ───────────────────────────────────────────────────────

class TestRetryWithBackoff:

    def _cfg(self, max_retries=3, delays=None):
        return RetryConfig(
            max_retries=max_retries,
            delays_seconds=delays or [2, 8, 15],
        )

    # -- Éxito en el primer intento --

    def test_success_first_attempt(self):
        fn = MagicMock(return_value="ok")
        sleep = MagicMock()
        result = retry_with_backoff(fn, self._cfg(), _sleep=sleep)
        assert result == "ok"
        fn.assert_called_once()
        sleep.assert_not_called()

    # -- Reintentos ante TransientBackendError --

    def test_retries_on_transient(self):
        """Falla 2 veces con Transient, luego éxito → 3 llamadas totales."""
        fn = MagicMock(side_effect=[
            TransientBackendError("timeout"),
            TransientBackendError("timeout"),
            "success",
        ])
        sleep = MagicMock()
        result = retry_with_backoff(fn, self._cfg(max_retries=3), _sleep=sleep)
        assert result == "success"
        assert fn.call_count == 3
        assert sleep.call_count == 2

    def test_delays_respected(self):
        """Los delays usados son los de la config en orden."""
        fn = MagicMock(side_effect=[
            TransientBackendError("a"),
            TransientBackendError("b"),
            "ok",
        ])
        sleep = MagicMock()
        retry_with_backoff(fn, self._cfg(delays=[5, 10, 20]), _sleep=sleep)
        assert sleep.call_args_list == [call(5.0), call(10.0)]

    def test_last_delay_repeated_when_fewer_delays_than_retries(self):
        """Si hay menos delays que reintentos, se repite el último."""
        fn = MagicMock(side_effect=[
            TransientBackendError("a"),
            TransientBackendError("b"),
            TransientBackendError("c"),
            "ok",
        ])
        sleep = MagicMock()
        cfg = RetryConfig(max_retries=4, delays_seconds=[2, 8])
        retry_with_backoff(fn, cfg, _sleep=sleep)
        assert sleep.call_args_list == [call(2.0), call(8.0), call(8.0)]

    def test_raises_after_all_retries_exhausted(self):
        """Si todos los intentos fallan con Transient, relanza la última."""
        exc = TransientBackendError("persistente")
        fn = MagicMock(side_effect=exc)
        sleep = MagicMock()
        cfg = self._cfg(max_retries=2)
        with pytest.raises(TransientBackendError):
            retry_with_backoff(fn, cfg, _sleep=sleep)
        assert fn.call_count == 3  # 1 original + 2 reintentos
        assert sleep.call_count == 2

    def test_max_retries_zero_no_retry(self):
        """max_retries=0 → sin reintentos, propaga en el primer fallo."""
        fn = MagicMock(side_effect=TransientBackendError("fail"))
        sleep = MagicMock()
        with pytest.raises(TransientBackendError):
            retry_with_backoff(fn, self._cfg(max_retries=0), _sleep=sleep)
        fn.assert_called_once()
        sleep.assert_not_called()

    # -- NO reintenta ante PermanentBackendError --

    def test_no_retry_on_permanent(self):
        """PermanentBackendError se propaga inmediatamente sin reintentar."""
        fn = MagicMock(side_effect=PermanentBackendError("schema inválido"))
        sleep = MagicMock()
        with pytest.raises(PermanentBackendError):
            retry_with_backoff(fn, self._cfg(max_retries=3), _sleep=sleep)
        fn.assert_called_once()
        sleep.assert_not_called()

    def test_no_retry_on_schema_violation(self):
        """SchemaViolationError (subclase Permanent) tampoco se reintenta."""
        fn = MagicMock(side_effect=SchemaViolationError("bad schema"))
        sleep = MagicMock()
        with pytest.raises(SchemaViolationError):
            retry_with_backoff(fn, self._cfg(max_retries=3), _sleep=sleep)
        fn.assert_called_once()

    # -- Subclases de Transient sí se reintentan --

    def test_retries_on_transient_subclass(self):
        """BackendTimeoutError (subclase Transient) se reintenta."""
        fn = MagicMock(side_effect=[
            BackendTimeoutError("timeout"),
            "ok",
        ])
        sleep = MagicMock()
        result = retry_with_backoff(fn, self._cfg(max_retries=2), _sleep=sleep)
        assert result == "ok"
        assert fn.call_count == 2

    # -- Otras excepciones no se tocan --

    def test_non_backend_error_propagates_immediately(self):
        """ValueError u otras excepciones no BackendError se propagan sin reintentar."""
        fn = MagicMock(side_effect=ValueError("bug"))
        sleep = MagicMock()
        with pytest.raises(ValueError):
            retry_with_backoff(fn, self._cfg(max_retries=3), _sleep=sleep)
        fn.assert_called_once()
        sleep.assert_not_called()
