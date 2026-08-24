"""Presupuesto acumulado de tokens para una corrida.

El presupuesto gobierna llamadas reales al backend. La capa de caché debe
envolver a :class:`BudgetedBackend`: así un cache hit puede resolverse aunque
el techo ya se haya alcanzado, porque no consume tokens nuevos.
"""

from __future__ import annotations

import threading
from typing import TypeVar

from pydantic import BaseModel

from emoparse.core.backend.base import LLMBackend, LLMResponse
from emoparse.core.backend.exceptions import BackendError

T = TypeVar("T", bound=BaseModel)


class TokenBudgetReached(BaseException):
    """Señal de control: no debe convertirse en error de un ítem.

    Hereda directamente de ``BaseException`` para atravesar los manejadores
    genéricos ``except Exception`` de agentes y stages. Solo el runner y el CLI
    deben capturarla explícitamente.
    """

    def __init__(self, *, spent: int, limit: int) -> None:
        super().__init__(f"presupuesto de tokens alcanzado: {spent}/{limit}")
        self.spent = spent
        self.limit = limit


class TokenBudget:
    """Contador compartido de consumo real acumulado del run."""

    def __init__(self, limit: int, *, initial_spent: int = 0) -> None:
        if limit <= 0:
            raise ValueError("token budget debe ser mayor que cero")
        if initial_spent < 0:
            raise ValueError("initial_spent no puede ser negativo")
        self._limit = int(limit)
        self._spent = int(initial_spent)
        self._lock = threading.Lock()

    @property
    def limit(self) -> int:
        return self._limit

    @property
    def spent(self) -> int:
        with self._lock:
            return self._spent

    @property
    def remaining(self) -> int:
        return max(self._limit - self.spent, 0)

    def ensure_can_start(self) -> None:
        """Impide iniciar otra llamada real una vez alcanzado el techo."""
        with self._lock:
            if self._spent >= self._limit:
                raise TokenBudgetReached(spent=self._spent, limit=self._limit)

    def record(self, total_tokens: int) -> None:
        """Suma el uso informado por una llamada que ya terminó."""
        if total_tokens <= 0:
            return
        with self._lock:
            self._spent += int(total_tokens)


class BudgetedBackend(LLMBackend):
    """Decorator que aplica un :class:`TokenBudget` a llamadas reales."""

    def __init__(self, wrapped: LLMBackend, budget: TokenBudget) -> None:
        self._wrapped = wrapped
        self._budget = budget
        self.alias = wrapped.alias

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
        images: list[str] | None = None,
    ) -> LLMResponse:
        self._budget.ensure_can_start()
        extra_kwargs: dict[str, list[str]] = {"images": images} if images else {}
        try:
            response = self._wrapped.generate(
                system=system,
                user=user,
                schema=schema,
                max_tokens=max_tokens,
                temperature=temperature,
                seed=seed,
                stop=stop,
                reset_before=reset_before,
                max_items=max_items,
                **extra_kwargs,
            )
        except BackendError as exc:
            # APIs remotas pueden devolver usage facturable aun cuando la
            # respuesta falle luego por refusal, truncamiento o validación.
            self._budget.record(
                int(getattr(exc, "prompt_tokens", 0) or 0)
                + int(getattr(exc, "completion_tokens", 0) or 0)
            )
            raise
        self._budget.record(response.usage.total_tokens)
        return response

    def healthcheck(self) -> bool:
        return self._wrapped.healthcheck()

    def close(self) -> None:
        self._wrapped.close()

    def reset_state(self) -> None:
        self._wrapped.reset_state()

    def __repr__(self) -> str:
        return (
            f"<BudgetedBackend wrapping={self._wrapped!r} "
            f"budget={self._budget.spent}/{self._budget.limit}>"
        )
