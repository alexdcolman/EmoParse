"""Backend LLM con generación estructurada.

Provee contrato común, registro de backends y excepciones.
"""

from emoparse.core.backend.base import (
    FinishReason,
    LLMBackend,
    LLMResponse,
    TokenUsage,
)
from emoparse.core.backend.exceptions import (
    BackendConfigError,
    BackendError,
    BackendTimeoutError,
    BackendUnavailableError,
    BackendUnhealthyError,
    ContextLengthExceededError,
    PermanentBackendError,
    SchemaViolationError,
    TransientBackendError,
)
from emoparse.core.backend.registry import BackendRegistry, RegistryConfig, build_backend

__all__ = [
    # Tipos de retorno y contrato
    "LLMBackend",
    "LLMResponse",
    "TokenUsage",
    "FinishReason",
    # Registro y factory
    "BackendRegistry",
    "RegistryConfig",
    "build_backend",
    # Excepciones
    "BackendError",
    "TransientBackendError",
    "PermanentBackendError",
    "BackendTimeoutError",
    "BackendUnavailableError",
    "BackendUnhealthyError",
    "ContextLengthExceededError",
    "SchemaViolationError",
    "BackendConfigError",
]
