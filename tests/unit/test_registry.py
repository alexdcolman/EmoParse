# ══════════════════════════════════════════════════════════════════════════════
#  tests.unit.test_registry
#
#  Verifica el comportamiento del BackendRegistry sin requerir un modelo
#  real cargado.
# ══════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

from typing import Any, TypeVar

import pytest
from pydantic import BaseModel

from emoparse.core.backend.base import LLMBackend, LLMResponse, TokenUsage
from emoparse.core.backend.exceptions import (
    BackendConfigError,
    BackendUnhealthyError,
)
from emoparse.core.backend.registry import BackendRegistry, RegistryConfig

T = TypeVar("T", bound=BaseModel)


# ══════════════════════════════════════════════════════════════════════════════
#  FakeBackend para tests
# ══════════════════════════════════════════════════════════════════════════════

class FakeBackend(LLMBackend):
    """Backend de prueba: devuelve respuestas configuradas, contabiliza llamadas."""

    def __init__(self, alias: str, healthy: bool = True) -> None:
        self.alias = alias
        self.calls: list[tuple[str, str]] = []
        self.closed = False
        self._healthy = healthy

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
        self.calls.append((system, user))
        return LLMResponse(
            parsed=None,
            raw="ok",
            usage=TokenUsage(prompt_tokens=1, completion_tokens=1),
            latency_ms=1.0,
            model_alias=self.alias,
            cache_hit=False,
            finish_reason="stop",
        )

    def healthcheck(self) -> bool:
        return self._healthy

    def close(self) -> None:
        self.closed = True


# ══════════════════════════════════════════════════════════════════════════════
#  Fixtures
# ══════════════════════════════════════════════════════════════════════════════

@pytest.fixture
def fake_models_config() -> dict[str, dict[str, Any]]:
    return {
        "modelo_a": {"backend": "fake", "_healthy": True},
        "modelo_b": {"backend": "fake", "_healthy": True},
    }


@pytest.fixture
def patched_build(monkeypatch: pytest.MonkeyPatch) -> dict[str, FakeBackend]:
    """Patchea build_backend para que devuelva FakeBackends rastreables."""
    instances: dict[str, FakeBackend] = {}

    def _fake_build(alias: str, model_config: dict[str, Any]) -> LLMBackend:
        if model_config.get("backend") != "fake":
            # Permitir que el test original de "backend desconocido" funcione.
            raise BackendConfigError(f"Backend '{model_config.get('backend')}' desconocido")
        b = FakeBackend(alias, healthy=model_config.get("_healthy", True))
        instances[alias] = b
        return b

    import emoparse.core.backend.registry as reg_mod
    monkeypatch.setattr(reg_mod, "build_backend", _fake_build)
    return instances


# ══════════════════════════════════════════════════════════════════════════════
#  Lazy loading
# ══════════════════════════════════════════════════════════════════════════════

class TestLazyLoading:

    def test_no_instance_until_get(
        self,
        fake_models_config: dict[str, dict[str, Any]],
        patched_build: dict[str, FakeBackend],
    ) -> None:
        registry = BackendRegistry(fake_models_config)
        assert registry.loaded() == []
        assert patched_build == {}

        registry.get("modelo_a")
        assert registry.loaded() == ["modelo_a"]
        assert "modelo_a" in patched_build
        assert "modelo_b" not in patched_build

    def test_get_twice_reuses_instance(
        self,
        fake_models_config: dict[str, dict[str, Any]],
        patched_build: dict[str, FakeBackend],
    ) -> None:
        registry = BackendRegistry(fake_models_config)
        b1 = registry.get("modelo_a")
        b2 = registry.get("modelo_a")
        assert b1 is b2

    def test_unknown_alias_raises_keyerror(
        self,
        fake_models_config: dict[str, dict[str, Any]],
        patched_build: dict[str, FakeBackend],
    ) -> None:
        registry = BackendRegistry(fake_models_config)
        with pytest.raises(KeyError, match="no definido"):
            registry.get("modelo_inexistente")


# ══════════════════════════════════════════════════════════════════════════════
#  Circuit breaker
# ══════════════════════════════════════════════════════════════════════════════

class TestCircuitBreaker:

    def test_record_failure_does_not_open_below_threshold(
        self,
        fake_models_config: dict[str, dict[str, Any]],
        patched_build: dict[str, FakeBackend],
    ) -> None:
        registry = BackendRegistry(
            fake_models_config,
            registry_config=RegistryConfig(failure_threshold=3),
        )
        registry.get("modelo_a")
        registry.record_failure("modelo_a", "boom")
        registry.record_failure("modelo_a", "boom")
        registry.get("modelo_a")  # no raise

    def test_circuit_opens_at_threshold(
        self,
        fake_models_config: dict[str, dict[str, Any]],
        patched_build: dict[str, FakeBackend],
    ) -> None:
        registry = BackendRegistry(
            fake_models_config,
            registry_config=RegistryConfig(failure_threshold=2),
        )
        registry.get("modelo_a")
        registry.record_failure("modelo_a", "boom")
        registry.record_failure("modelo_a", "boom")
        with pytest.raises(BackendUnhealthyError) as exc_info:
            registry.get("modelo_a")
        assert exc_info.value.alias == "modelo_a"
        assert exc_info.value.consecutive_failures == 2

    def test_record_success_resets_counter(
        self,
        fake_models_config: dict[str, dict[str, Any]],
        patched_build: dict[str, FakeBackend],
    ) -> None:
        registry = BackendRegistry(
            fake_models_config,
            registry_config=RegistryConfig(failure_threshold=2),
        )
        registry.get("modelo_a")
        registry.record_failure("modelo_a", "boom")
        registry.record_success("modelo_a")
        # Después de reset, dos fallos más para abrir el circuit.
        registry.record_failure("modelo_a", "boom")
        registry.get("modelo_a")  # aún cerrado
        registry.record_failure("modelo_a", "boom")
        with pytest.raises(BackendUnhealthyError):
            registry.get("modelo_a")

    def test_reset_health_closes_circuit(
        self,
        fake_models_config: dict[str, dict[str, Any]],
        patched_build: dict[str, FakeBackend],
    ) -> None:
        registry = BackendRegistry(
            fake_models_config,
            registry_config=RegistryConfig(failure_threshold=1),
        )
        registry.get("modelo_a")
        registry.record_failure("modelo_a", "boom")
        with pytest.raises(BackendUnhealthyError):
            registry.get("modelo_a")
        registry.reset_health("modelo_a")
        registry.get("modelo_a")  # accesible de nuevo

    def test_reset_health_global(
        self,
        fake_models_config: dict[str, dict[str, Any]],
        patched_build: dict[str, FakeBackend],
    ) -> None:
        registry = BackendRegistry(
            fake_models_config,
            registry_config=RegistryConfig(failure_threshold=1),
        )
        registry.get("modelo_a")
        registry.get("modelo_b")
        registry.record_failure("modelo_a", "boom")
        registry.record_failure("modelo_b", "boom")
        registry.reset_health()
        registry.get("modelo_a")
        registry.get("modelo_b")


# ══════════════════════════════════════════════════════════════════════════════
#  Lifecycle
# ══════════════════════════════════════════════════════════════════════════════

class TestLifecycle:

    def test_unload_calls_close(
        self,
        fake_models_config: dict[str, dict[str, Any]],
        patched_build: dict[str, FakeBackend],
    ) -> None:
        registry = BackendRegistry(fake_models_config)
        registry.get("modelo_a")
        backend = patched_build["modelo_a"]
        assert not backend.closed
        registry.unload("modelo_a")
        assert backend.closed
        assert "modelo_a" not in registry.loaded()

    def test_unload_all_closes_everyone(
        self,
        fake_models_config: dict[str, dict[str, Any]],
        patched_build: dict[str, FakeBackend],
    ) -> None:
        registry = BackendRegistry(fake_models_config)
        registry.preload(["modelo_a", "modelo_b"])
        registry.unload_all()
        assert patched_build["modelo_a"].closed
        assert patched_build["modelo_b"].closed
        assert registry.loaded() == []

    def test_unload_unloaded_is_safe(
        self,
        fake_models_config: dict[str, dict[str, Any]],
        patched_build: dict[str, FakeBackend],
    ) -> None:
        registry = BackendRegistry(fake_models_config)
        registry.unload("modelo_a")  # no raise


# ══════════════════════════════════════════════════════════════════════════════
#  Healthcheck on load
# ══════════════════════════════════════════════════════════════════════════════

class TestHealthcheckOnLoad:

    def test_healthcheck_on_load_success(
        self,
        patched_build: dict[str, FakeBackend],
    ) -> None:
        registry = BackendRegistry(
            {"modelo_a": {"backend": "fake", "_healthy": True}},
            registry_config=RegistryConfig(healthcheck_on_load=True),
        )
        registry.get("modelo_a")  # no raise

    def test_healthcheck_on_load_failure_raises(
        self,
        patched_build: dict[str, FakeBackend],
    ) -> None:
        registry = BackendRegistry(
            {"modelo_a": {"backend": "fake", "_healthy": False}},
            registry_config=RegistryConfig(healthcheck_on_load=True),
        )
        with pytest.raises(BackendConfigError, match="healthcheck"):
            registry.get("modelo_a")
