# ══════════════════════════════════════════════════════════════════════════════
#  emoparse.core.backend.retry
#
#  Retry con backoff para errores transitorios del backend.
#  Solo reintenta TransientBackendError; los permanentes se propagan.
# ══════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Callable, TypeVar

from loguru import logger

from emoparse.core.backend.exceptions import (
    PermanentBackendError,
    TransientBackendError,
)

T = TypeVar("T")


@dataclass(frozen=True)
class RetryConfig:
    """Parámetros de retry.

    max_retries: número máximo de reintentos.  
    delays_seconds: lista de delays entre intentos.
    """

    max_retries: int
    delays_seconds: list[int]

    def __post_init__(self) -> None:
        if self.max_retries < 0:
            raise ValueError(f"max_retries debe ser >= 0, got {self.max_retries}")
        if not self.delays_seconds:
            raise ValueError("delays_seconds no puede estar vacío")


def retry_with_backoff(
    fn: Callable[[], T],
    config: RetryConfig,
    *,
    _sleep: Callable[[float], None] | None = None,
) -> T:
    """Ejecuta fn() reintentando ante TransientBackendError.

    Máximo intentos: config.max_retries + 1.  
    Raises: PermanentBackendError inmediato, TransientBackendError
    tras agotar reintentos, otras excepciones propagadas.
    """
    sleep_fn = _sleep if _sleep is not None else time.sleep
    last_exc: TransientBackendError | None = None

    for attempt in range(config.max_retries + 1):
        try:
            return fn()
        except PermanentBackendError:
            raise
        except TransientBackendError as exc:
            last_exc = exc
            if attempt < config.max_retries:
                delay_idx = min(attempt, len(config.delays_seconds) - 1)
                delay = config.delays_seconds[delay_idx]
                logger.warning(
                    "[retry] TransientBackendError en intento {}/{}: {}. "
                    "Reintentando en {}s.",
                    attempt + 1,
                    config.max_retries + 1,
                    exc,
                    delay,
                )
                sleep_fn(float(delay))
            else:
                logger.error(
                    "[retry] TransientBackendError tras {} intento(s). Desistiendo: {}",
                    config.max_retries + 1,
                    exc,
                )

    assert last_exc is not None
    raise last_exc
