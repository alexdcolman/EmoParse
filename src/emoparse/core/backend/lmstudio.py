# ══════════════════════════════════════════════════════════════════════════════
#  emoparse.core.backend.lmstudio
#
#  Backend para LM Studio (API OpenAI-compatible).
#
#  Usa response_format con json_schema para structured generation.
#  Aplica chat templates internamente y permite pasar seed en la request.
#  Latencia incluye round-trip HTTP.
# ══════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any, TypeVar

from loguru import logger
from pydantic import BaseModel, ValidationError

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
    ContextLengthExceededError,
    SchemaViolationError,
)

if TYPE_CHECKING:
    from openai import OpenAI

T = TypeVar("T", bound=BaseModel)

#: Valores por defecto de configuración: base_url, model_id, temperatura,
#: max_tokens, seed y timeout.
_DEFAULT_BASE_URL = "http://localhost:1234/v1"
_DEFAULT_MODEL_ID = "local-model"
_DEFAULT_TEMPERATURE = 0.0
_DEFAULT_MAX_TOKENS = 2048
_DEFAULT_SEED = 42
_DEFAULT_TIMEOUT = 90.0


class LMStudioBackend(LLMBackend):
    """Backend para LM Studio vía API OpenAI-compatible."""

    def __init__(
        self,
        alias: str,
        model_config: dict[str, Any],
    ) -> None:
        try:
            from openai import OpenAI  # noqa: F401
        except ImportError as e:
            raise BackendConfigError(
                "openai no está instalado. Instalar con: pip install openai"
            ) from e

        self.alias = alias
        self._cfg = dict(model_config)

        self._model_id = self._cfg.get("model_id", _DEFAULT_MODEL_ID)
        self._base_url = self._cfg.get("base_url", _DEFAULT_BASE_URL)
        self._default_max_tokens = self._cfg.get("max_tokens", _DEFAULT_MAX_TOKENS)
        self._default_temperature = self._cfg.get("temperature", _DEFAULT_TEMPERATURE)
        self._default_seed = self._cfg.get("seed", _DEFAULT_SEED)
        self._timeout = self._cfg.get("timeout", _DEFAULT_TIMEOUT)

        from openai import OpenAI as _OpenAI
        self._client: OpenAI = _OpenAI(
            base_url=self._base_url,
            # LM Studio no valida la api_key pero el SDK la requiere.
            api_key=self._cfg.get("api_key", "lm-studio"),
            timeout=self._timeout,
        )
        logger.info(
            f"[LMStudio:{alias}] Configurado → {self._base_url} / {self._model_id}"
        )

    # ── Health check ─────────────────────────────────────────────────────────

    def healthcheck(self) -> bool:
        """Verifica conectividad con una llamada mínima."""
        try:
            self._client.chat.completions.create(
                model=self._model_id,
                messages=[{"role": "user", "content": "ok"}],
                max_tokens=1,
                temperature=0.0,
            )
            return True
        except Exception as e:
            logger.warning(f"[LMStudio:{self.alias}] Healthcheck falló: {e}")
            return False

    # ── Generación principal ─────────────────────────────────────────────────

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
        # reset_before es no-op: cada request HTTP es stateless; se mantiene en
        # la firma por compatibilidad.
        del reset_before  # explicit unused

        from openai import (
            APIConnectionError,
            APITimeoutError,
            BadRequestError,
        )

        eff_max_tokens = max_tokens if max_tokens is not None else self._default_max_tokens
        eff_temp = temperature if temperature is not None else self._default_temperature
        eff_seed = seed if seed is not None else self._default_seed

        messages: list[dict[str, str]] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": user})

        kwargs: dict[str, Any] = {
            "model": self._model_id,
            "messages": messages,
            "max_tokens": eff_max_tokens,
            "temperature": eff_temp,
            "seed": eff_seed,
        }
        if stop:
            kwargs["stop"] = stop

        # Salida estructurada vía JSON Schema (modo estándar OpenAI).
        if schema is not None:
            kwargs["response_format"] = self._make_response_format(
                schema, max_items=max_items
            )

        # Inferencia.
        t_start = time.perf_counter()
        try:
            output = self._client.chat.completions.create(**kwargs)
        except APITimeoutError as e:
            raise BackendTimeoutError(
                f"LM Studio timeout después de {self._timeout}s"
            ) from e
        except APIConnectionError as e:
            raise BackendUnavailableError(
                f"LM Studio inalcanzable en {self._base_url}: {e}"
            ) from e
        except BadRequestError as e:
            # 400: context length o schema no soportado.
            msg = str(e).lower()
            if "context" in msg or "token" in msg:
                raise ContextLengthExceededError(
                    max_tokens=eff_max_tokens,
                ) from e
            if "schema" in msg or "response_format" in msg:
                raise SchemaViolationError(
                    f"LM Studio rechazó el schema: {e}"
                ) from e
            raise BackendError(f"LM Studio bad request: {e}") from e
        except Exception as e:
            raise BackendError(f"LM Studio error: {e}") from e
        latency_ms = (time.perf_counter() - t_start) * 1000.0

        choice = output.choices[0]
        raw = choice.message.content or ""

        # Mapear finish_reason de OpenAI: stop, length, content_filter,
        # tool_calls o function_call.
        finish_raw = choice.finish_reason
        finish: FinishReason
        if finish_raw == "length":
            finish = "length"
        elif finish_raw == "stop":
            finish = "stop"
        else:
            finish = "error"

        if schema is not None and finish == "length":
            raise ContextLengthExceededError(max_tokens=eff_max_tokens)

        usage = TokenUsage(
            prompt_tokens=output.usage.prompt_tokens if output.usage else 0,
            completion_tokens=output.usage.completion_tokens if output.usage else 0,
        )

        parsed: BaseModel | None = None
        if schema is not None:
            try:
                parsed = schema.model_validate_json(raw)
            except ValidationError as e:
                raise SchemaViolationError(
                    f"LM Studio response no valida contra {schema.__name__}: {e}\n"
                    f"raw={raw[:300]!r}"
                ) from e

        return LLMResponse(
            parsed=parsed,
            raw=raw,
            usage=usage,
            latency_ms=latency_ms,
            model_alias=self.alias,
            cache_hit=False,
            finish_reason=finish,
        )

    # ── Helpers ──────────────────────────────────────────────────────────────

    @staticmethod
    def _make_response_format(
        schema: type[BaseModel],
        *,
        max_items: int | None = None,
    ) -> dict[str, Any]:
        """Construye response_format para API OpenAI/LM Studio.

        Usa json_schema y strict:true. Si `max_items` viene y el top-level es un
        array (schema de batch), lo acota a EXACTAMENTE `max_items` elementos
        para evitar que el modelo repita ítems indefinidamente.
        """

        json_schema = schema.model_json_schema()
        # Se agrega additionalProperties:false requerido por OpenAI strict mode.
        _add_strict_flags(json_schema)
        if max_items is not None and json_schema.get("type") == "array":
            n = max(1, int(max_items))
            json_schema["minItems"] = n
            json_schema["maxItems"] = n

        return {
            "type": "json_schema",
            "json_schema": {
                "name": schema.__name__,
                "schema": json_schema,
                "strict": True,
            },
        }


def _add_strict_flags(node: dict[str, Any]) -> None:
    """Agrega additionalProperties:false a todos los type:object.
    
    Para strict mode de OpenAI.
    """
    if not isinstance(node, dict):
        return
    if node.get("type") == "object":
        node.setdefault("additionalProperties", False)
        # Strict mode requiere todos los campos en required; Pydantic
        # ya maneja optional con anyOf null.
        properties = node.get("properties", {})
        if properties:
            node["required"] = list(properties.keys())
    # Recurse.
    for value in node.values():
        if isinstance(value, dict):
            _add_strict_flags(value)
        elif isinstance(value, list):
            for item in value:
                if isinstance(item, dict):
                    _add_strict_flags(item)
