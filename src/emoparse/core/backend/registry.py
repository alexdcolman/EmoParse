# ══════════════════════════════════════════════════════════════════════════════
#  emoparse.core.backend.registry
#
#  Registro nombrado de backends LLM con lazy loading, health check y circuit breaker.
#  Provee acceso por alias; la selección de backend la define el perfil de género.
# ══════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from loguru import logger

from emoparse.core.backend.base import LLMBackend
from emoparse.core.backend.exceptions import (
    BackendConfigError,
    BackendUnhealthyError,
)


# ══════════════════════════════════════════════════════════════════════════════
#  Estado de salud por backend
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class _HealthState:
    """Estado del circuit breaker para un backend.

    consecutive_failures se resetea con cada éxito.
    is_open=True cuando supera el threshold.
    """
    consecutive_failures: int = 0
    last_error: str | None = None
    is_open: bool = False

    def record_success(self) -> None:
        if self.consecutive_failures > 0 or self.is_open:
            logger.info(
                "[Registry] Circuit reseteado tras éxito "
                f"(habían {self.consecutive_failures} fallos previos)"
            )
        self.consecutive_failures = 0
        self.last_error = None
        self.is_open = False

    def record_failure(self, threshold: int, error: str) -> bool:
        """Registra un fallo. Devuelve True si el circuit acaba de abrirse."""
        self.consecutive_failures += 1
        self.last_error = error
        just_opened = False
        if not self.is_open and self.consecutive_failures >= threshold:
            self.is_open = True
            just_opened = True
        return just_opened


# ══════════════════════════════════════════════════════════════════════════════
#  Configuración del registry
# ══════════════════════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class RegistryConfig:
    """Parámetros de comportamiento del registry."""
    #: Número de fallos consecutivos para marcar backend unhealthy.
    failure_threshold: int = 5
    #: Si True, realiza healthcheck al instanciar cada backend.
    healthcheck_on_load: bool = False


# ══════════════════════════════════════════════════════════════════════════════
#  Factory
# ══════════════════════════════════════════════════════════════════════════════

def build_backend(alias: str, model_config: dict[str, Any]) -> LLMBackend:
    """Construye un backend LLM según model_config['backend'].

    Soporta llama_cpp y lmstudio. Raises BackendConfigError si backend
    desconocido o config inválida.
    """
    backend_key = model_config.get("backend")
    if backend_key == "llama_cpp":
        from emoparse.core.backend.llamacpp import LlamaCppBackend
        return LlamaCppBackend(alias=alias, model_config=model_config)
    if backend_key == "lmstudio":
        from emoparse.core.backend.lmstudio import LMStudioBackend
        return LMStudioBackend(alias=alias, model_config=model_config)
    if backend_key == "llama_server":
        from emoparse.core.backend.llama_server import LlamaServerBackend
        return LlamaServerBackend(alias=alias, model_config=model_config)
    raise BackendConfigError(
        f"Backend '{backend_key}' no reconocido para alias '{alias}'. "
        f"Opciones: llama_cpp, llama_server, lmstudio"
    )


# ══════════════════════════════════════════════════════════════════════════════
#  Registry
# ══════════════════════════════════════════════════════════════════════════════

class BackendRegistry:
    """Registro lazy de backends LLM con circuit breaker.

    El registro de éxito/fallo lo decide el caller, no es automático.
    """

    def __init__(
        self,
        models_config: dict[str, dict[str, Any]],
        registry_config: RegistryConfig | None = None,
    ) -> None:
        self._configs: dict[str, dict[str, Any]] = dict(models_config)
        self._instances: dict[str, LLMBackend] = {}
        self._health: dict[str, _HealthState] = {
            alias: _HealthState() for alias in self._configs
        }
        self._cfg = registry_config or RegistryConfig()

    # ── Acceso ───────────────────────────────────────────────────────────────

    def get(self, alias: str) -> LLMBackend:
        """Devuelve o instancia el backend con alias dado.

        Raises: KeyError, BackendUnhealthyError, BackendConfigError.
        """
        if alias not in self._configs:
            raise KeyError(
                f"Modelo '{alias}' no definido. "
                f"Aliases disponibles: {sorted(self._configs)}"
            )

        health = self._health[alias]
        if health.is_open:
            raise BackendUnhealthyError(
                alias=alias,
                consecutive_failures=health.consecutive_failures,
            )

        if alias not in self._instances:
            logger.info(f"[Registry] Instanciando backend '{alias}'")
            backend = build_backend(alias, self._configs[alias])
            if self._cfg.healthcheck_on_load:
                if not backend.healthcheck():
                    raise BackendConfigError(
                        f"Backend '{alias}' falló healthcheck inicial"
                    )
            self._instances[alias] = backend

        return self._instances[alias]

    # ── Telemetría de circuit breaker ────────────────────────────────────────

    def record_success(self, alias: str) -> None:
        """Reporta una llamada exitosa al backend (resetea contador)."""
        if alias in self._health:
            self._health[alias].record_success()

    def record_failure(self, alias: str, error: str) -> None:
        """Reporta una llamada fallida.
        
        Si se cruza el threshold, el circuit se abre.
        """
        if alias not in self._health:
            return
        just_opened = self._health[alias].record_failure(
            threshold=self._cfg.failure_threshold,
            error=error,
        )
        if just_opened:
            logger.error(
                f"[Registry] Circuit ABIERTO para '{alias}' "
                f"tras {self._cfg.failure_threshold} fallos. "
                f"Último error: {error}"
            )

    def reset_health(self, alias: str | None = None) -> None:
        """Cierra el circuit breaker para todos los backends o uno específico."""
        if alias is not None:
            if alias in self._health:
                self._health[alias].record_success()
        else:
            for state in self._health.values():
                state.record_success()

    # ── Lifecycle ────────────────────────────────────────────────────────────

    def preload(self, aliases: list[str]) -> None:
        """Precarga una lista de backends."""
        for alias in aliases:
            self.get(alias)

    def loaded(self) -> list[str]:
        """Aliases con backend ya instanciado."""
        return list(self._instances.keys())

    def unload(self, alias: str) -> None:
        """Descarga un backend de memoria."""
        instance = self._instances.pop(alias, None)
        if instance is not None:
            instance.close()
            logger.info(f"[Registry] Backend '{alias}' descargado")

    def unload_all(self) -> None:
        """Descarga todos los backends de memoria."""
        for alias in list(self._instances):
            self.unload(alias)

    # ── Introspection ────────────────────────────────────────────────────────

    def health_summary(self) -> dict[str, dict[str, Any]]:
        """Resumen del estado de salud de todos los backends."""
        return {
            alias: {
                "loaded": alias in self._instances,
                "consecutive_failures": h.consecutive_failures,
                "is_open": h.is_open,
                "last_error": h.last_error,
            }
            for alias, h in self._health.items()
        }

    def __repr__(self) -> str:
        loaded = self.loaded()
        unhealthy = [a for a, h in self._health.items() if h.is_open]
        return (
            f"<BackendRegistry loaded={loaded} unhealthy={unhealthy}>"
        )
