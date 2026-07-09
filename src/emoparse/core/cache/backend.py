# ══════════════════════════════════════════════════════════════════════════════
#  emoparse.core.cache.backend
#
#  CachedBackend: decorator de LLMBackend con caché transparente.
#
#  Implementa interfaz completa; en generate construye clave, devuelve hit o
#  delega y guarda.
#  cache_hit=True en respuestas cacheadas; latency_ms mide lookup.
# ══════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

import time
from typing import TypeVar

from loguru import logger
from pydantic import BaseModel, ValidationError

from emoparse.core.backend.base import (
    LLMBackend,
    LLMResponse,
    TokenUsage,
)
from emoparse.core.backend.exceptions import SchemaViolationError
from emoparse.core.cache.keys import make_cache_key
from emoparse.core.cache.repository import CacheRepository
from emoparse.storage.models import RunContext

T = TypeVar("T", bound=BaseModel)


class CachedBackend(LLMBackend):
    """Decorator de LLMBackend con caché transparente."""

    def __init__(
        self,
        backend: LLMBackend,
        repo: CacheRepository,
        ctx: RunContext,
    ) -> None:
        """
        Args:
            backend: LLMBackend a envolver.
            repo: Repositorio de cache.
            ctx: RunContext con versiones activas.
        """
        self._backend = backend
        self._repo = repo
        self._ctx = ctx
        # Inicializa alias para compatibilidad con __repr__.
        self.alias = backend.alias

    # ── Interfaz LLMBackend ──────────────────────────────────────────────────

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
        # Construir clave; si seed no se pasa, se usa None.
        schema_qualname = (
            f"{schema.__module__}.{schema.__qualname__}" if schema else None
        )
        key = make_cache_key(
            model_alias=self._backend.alias,
            system=system,
            user=user,
            schema_qualname=schema_qualname,
            seed=seed,
            versions=self._ctx.versions,
        )

        # Lookup.
        t_start = time.perf_counter()
        cached = self._repo.get(key)

        if cached is not None:
            # HIT: reconstruir LLMResponse desde entrada cacheada.
            logger.debug(
                f"[CachedBackend:{self.alias}] HIT (key={key.digest[:12]}...)"
            )
            self._repo.record_hit(key.digest)

            parsed: BaseModel | None = None
            if schema is not None:
                try:
                    parsed = schema.model_validate_json(cached.raw)
                except ValidationError as e:
                    # Si el schema cambió, entradas viejas fallan al
                    # re-parsear; se lanza SchemaViolationError.
                    raise SchemaViolationError(
                        f"Cache hit no parsea contra {schema.__name__}: {e}. "
                        "¿Cambió el schema sin bumpear schema_version?"
                    ) from e

            latency_ms = (time.perf_counter() - t_start) * 1000.0
            return LLMResponse(
                parsed=parsed,
                raw=cached.raw,
                usage=TokenUsage(
                    prompt_tokens=cached.prompt_tokens,
                    completion_tokens=cached.completion_tokens,
                ),
                # Usa latencia original si existe; si no, la del lookup.
                latency_ms=cached.latency_ms if cached.latency_ms is not None else latency_ms,
                model_alias=self._backend.alias,
                cache_hit=True,
                # Usa finish_reason cacheado si válido; si no, "stop".
                finish_reason=cached.finish_reason or "stop",  # type: ignore[arg-type]
            )

        # MISS: delegar al backend.
        logger.debug(
            f"[CachedBackend:{self.alias}] MISS (key={key.digest[:12]}...)"
        )
        response = self._backend.generate(
            system=system,
            user=user,
            schema=schema,
            max_tokens=max_tokens,
            temperature=temperature,
            seed=seed,
            stop=stop,
            reset_before=reset_before,
            max_items=max_items,
        )

        # Guardar en cache solo si finish_reason es "stop" o "schema".
        if response.finish_reason in ("stop", "schema"):
            self._repo.set(
                key,
                raw=response.raw,
                finish_reason=response.finish_reason,
                prompt_tokens=response.usage.prompt_tokens,
                completion_tokens=response.usage.completion_tokens,
                latency_ms=response.latency_ms,
            )

        return response

    def healthcheck(self) -> bool:
        """Healthcheck delega al backend; el cache depende de la DB SQLite."""
        return self._backend.healthcheck()

    def close(self) -> None:
        """Cierra el backend wrapeado; la DB del cache la maneja el caller."""
        self._backend.close()

    def reset_state(self) -> None:
        """Resetea el estado del backend; el cache es persistente y no aplica reset."""
        self._backend.reset_state()

    def __repr__(self) -> str:
        return f"<CachedBackend wrapping={self._backend!r}>"
