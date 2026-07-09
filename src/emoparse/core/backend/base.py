# ══════════════════════════════════════════════════════════════════════════════
#  emoparse.core.backend.base
#
#  Interfaz común para backends LLM.
#  Contrato: (system, user) + schema opcional → LLMResponse válido o excepción
#  tipada.
#
#  Diseño:
#  - Separación de system y user para reutilización de KV-cache y hashing estable.
#  - Schema tipado con Pydantic v2, traducido al mecanismo nativo del backend.
#  - Seed explícita para idempotencia.
#  - LLMResponse incluye telemetría y debugging.
# ══════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Literal, TypeVar

from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)

FinishReason = Literal["stop", "length", "schema", "error"]


# ══════════════════════════════════════════════════════════════════════════════
#  Tipos de retorno
# ══════════════════════════════════════════════════════════════════════════════

@dataclass(frozen=True, slots=True)
class TokenUsage:
    """Tokens consumidos por una llamada.

    prompt_tokens incluye system, user y control tokens del template.  
    Si no se exponen tokens, los campos quedan en 0.
    """

    prompt_tokens: int = 0
    completion_tokens: int = 0

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens


@dataclass(frozen=True, slots=True)
class LLMResponse:
    """Resultado de una llamada al backend LLM.

    Atributos:
        parsed: Instancia del schema solicitado o None.
        raw: Texto crudo devuelto por el backend.
        usage: Tokens prompt/completion.
        latency_ms: Tiempo de inferencia en ms.
        model_alias: Alias del modelo en config.
        cache_hit: True si la respuesta vino del caché.
        finish_reason: Motivo de finalización ("stop", "length", "schema", "error").
        timestamp: Hora UTC ISO de la llamada.
        extra: Metadata adicional del backend.
    """
    
    parsed: BaseModel | None
    raw: str
    usage: TokenUsage
    latency_ms: float
    model_alias: str
    cache_hit: bool
    finish_reason: FinishReason
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    extra: dict[str, Any] = field(default_factory=dict)


# ══════════════════════════════════════════════════════════════════════════════
#  Interfaz abstracta
# ══════════════════════════════════════════════════════════════════════════════

class LLMBackend(ABC):
    """Backend LLM con generación estructurada opcional.

    Contratos:
        1. Con schema: LLMResponse.parsed instancia válida o excepción.
        2. Sin schema: parsed=None y raw contiene texto libre.
        3. Errores: subclases de BackendError.
        4. Llamada síncrona y bloqueante.
    """

    #: Alias del modelo según config.yaml; se setea en __init__ de la subclase.
    alias: str

    @abstractmethod
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
        max_items: int | None = None,
    ) -> LLMResponse:
        """Genera respuesta del LLM.

        Args:
            system: Mensaje de sistema.
            user: Mensaje de usuario.
            schema: Schema Pydantic opcional.
            max_tokens: Máximo de tokens en la respuesta.
            temperature: Temperatura de sampling.
            seed: Semilla del sampler.
            stop: Strings de corte.
            reset_before: Si True, llama a reset_state() antes de inferencia.
            max_items: Si el schema es una lista de batch (RootModel[list[...]]),
                acota la salida a EXACTAMENTE `max_items` elementos. Se usa para
                pasar el tamaño real del batch y evitar que el modelo repita
                ítems al infinito. Ignorado si el top-level del schema no es lista.

        Returns:
            LLMResponse con parsed o raw.

        Raises:
            BackendTimeoutError
            BackendUnavailableError
            ContextLengthExceededError
            SchemaViolationError
            BackendConfigError
            BackendError
        """

    @abstractmethod
    def healthcheck(self) -> bool:
        """Verifica que el backend está operativo con una llamada mínima.

        Devuelve True si la llamada tiene éxito, False si hay error.
        """

    def close(self) -> None:
        """Libera recursos del backend.

        Default: no-op. Override en backends con estado pesado.
        """

    def reset_state(self) -> None:
        """Vacía estado interno persistente entre llamadas.

        Ejemplo: KV-cache en llama.cpp. Default: no-op. Override en backends con estado.
        """

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__} alias={getattr(self, 'alias', '?')!r}>"

    # Context manager para asegurar liberación de recursos.
    def __enter__(self) -> LLMBackend:
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()
