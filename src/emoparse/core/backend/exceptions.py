# ══════════════════════════════════════════════════════════════════════════════
#  emoparse.core.backend.exceptions
#
#  Taxonomía de errores del backend LLM.
#
#  Diferencia entre errores transitorios (retry posible) y permanentes (retry
#  inútil).
# ══════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from emoparse.core.backend.base import TokenUsage


class BackendError(Exception):
    """Raíz de todos los errores del backend LLM.

    Puede transportar telemetría facturable cuando el proveedor la devuelve
    aun en una respuesta que termina en error. Esa metadata no cambia la
    taxonomía del error y permite que las métricas del run no pierdan consumo.
    """

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.prompt_tokens = 0
        self.completion_tokens = 0
        self.latency_ms = 0.0

    def attach_usage(
        self,
        usage: "TokenUsage",  # noqa: UP037
        *,
        latency_ms: float = 0.0,
    ) -> None:
        self.prompt_tokens = int(usage.prompt_tokens)
        self.completion_tokens = int(usage.completion_tokens)
        self.latency_ms = float(latency_ms)


# ══════════════════════════════════════════════════════════════════════════════
#  Errores transitorios — el retry puede ayudar
# ══════════════════════════════════════════════════════════════════════════════


class TransientBackendError(BackendError):
    """Categoría base para errores reintentables."""

    def __init__(self, message: str, *, retry_after_seconds: float | None = None) -> None:
        super().__init__(message)
        self.retry_after_seconds = retry_after_seconds


class BackendTimeoutError(TransientBackendError):
    """La inferencia excedió el timeout configurado."""


class BackendUnavailableError(TransientBackendError):
    """Backend temporalmente inalcanzable (ej. conexión rechazada, 503)."""


# ══════════════════════════════════════════════════════════════════════════════
#  Errores permanentes — el retry no va a ayudar
# ══════════════════════════════════════════════════════════════════════════════


class PermanentBackendError(BackendError):
    """Categoría base para errores no reintentables."""


class SchemaViolationError(PermanentBackendError):
    """Backend no soporta la generación estructurada solicitada."""


class ContextLengthExceededError(PermanentBackendError):
    """Prompt + completion excedió el contexto del modelo.

    Debe acortarse el prompt o subdividir la tarea.
    """

    def __init__(
        self,
        *,
        prompt_tokens: int | None = None,
        max_tokens: int | None = None,
        context_length: int | None = None,
    ) -> None:
        msg_parts = ["Context length exceeded"]
        if prompt_tokens is not None and context_length is not None:
            msg_parts.append(f"prompt={prompt_tokens} tokens")
            msg_parts.append(f"context={context_length} tokens")
        if max_tokens is not None:
            msg_parts.append(f"max_completion={max_tokens} tokens")
        super().__init__(" | ".join(msg_parts))
        self.context_prompt_tokens = prompt_tokens
        self.max_tokens = max_tokens
        self.context_length = context_length


class BackendConfigError(PermanentBackendError):
    """Configuración del backend inválida.

    Ej.: alias inexistente, archivo no encontrado, parámetro fuera de rango).
    """


# ══════════════════════════════════════════════════════════════════════════════
#  Estado del backend (no son errores de una llamada puntual)
# ══════════════════════════════════════════════════════════════════════════════


class BackendUnhealthyError(BackendError):
    """Circuit breaker marcó al backend como degradado tras fallos consecutivos."""

    def __init__(self, alias: str, consecutive_failures: int) -> None:
        super().__init__(
            f"Backend '{alias}' marcado unhealthy tras {consecutive_failures} fallos consecutivos"
        )
        self.alias = alias
        self.consecutive_failures = consecutive_failures
