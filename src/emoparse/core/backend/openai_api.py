"""Backend remoto para OpenAI Chat Completions."""

from __future__ import annotations

import os
import time
from typing import Any, TypeVar

import httpx
from pydantic import BaseModel, ValidationError

from emoparse.core.backend.base import FinishReason, LLMBackend, LLMResponse, TokenUsage
from emoparse.core.backend.exceptions import (
    BackendConfigError,
    BackendError,
    BackendTimeoutError,
    BackendUnavailableError,
    ContextLengthExceededError,
    SchemaViolationError,
)
from emoparse.core.backend.http_api import json_object, raise_api_http_error
from emoparse.core.backend.structured import openai_response_format

T = TypeVar("T", bound=BaseModel)

_DEFAULT_BASE_URL = "https://api.openai.com/v1"
_DEFAULT_MAX_TOKENS = 2048
_DEFAULT_TEMPERATURE = 0.0
_DEFAULT_TIMEOUT = 90.0


class OpenAIBackend(LLMBackend):
    """OpenAI vía HTTP directo, sin retries ocultos del SDK."""

    def __init__(self, alias: str, model_config: dict[str, Any]) -> None:
        self.alias = alias
        self._cfg = dict(model_config)
        self._model_id = str(self._cfg.get("model_id") or "").strip()
        if not self._model_id:
            raise BackendConfigError(f"OpenAI:{alias} requiere model_id")
        self._base_url = str(self._cfg.get("base_url") or _DEFAULT_BASE_URL).rstrip("/")
        self._default_max_tokens = int(self._cfg.get("max_tokens", _DEFAULT_MAX_TOKENS))
        self._default_temperature = float(self._cfg.get("temperature", _DEFAULT_TEMPERATURE))
        self._default_seed = self._cfg.get("seed")
        self._timeout = float(self._cfg.get("timeout") or _DEFAULT_TIMEOUT)

        api_key = self._resolve_api_key()
        self._http = httpx.Client(
            base_url=self._base_url,
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=self._timeout,
        )

    def _resolve_api_key(self) -> str:
        direct = self._cfg.get("api_key")
        if direct:
            return str(direct)
        env_name = str(self._cfg.get("api_key_env") or "OPENAI_API_KEY")
        value = os.environ.get(env_name)
        if value:
            return value
        raise BackendConfigError(
            f"OpenAI:{self.alias} requiere la variable de entorno {env_name} o api_key en el config"
        )

    def healthcheck(self) -> bool:
        try:
            response = self._http.get("/models")
            return response.is_success
        except httpx.HTTPError:
            return False

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
        del reset_before
        if images:
            raise BackendConfigError("OpenAI backend 3.2A todavía no acepta images")

        eff_max_tokens = max_tokens if max_tokens is not None else self._default_max_tokens
        eff_temp = temperature if temperature is not None else self._default_temperature
        eff_seed = seed if seed is not None else self._default_seed

        messages: list[dict[str, str]] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": user})

        payload: dict[str, Any] = {
            "model": self._model_id,
            "messages": messages,
            "max_completion_tokens": eff_max_tokens,
            "temperature": eff_temp,
        }
        if eff_seed is not None:
            payload["seed"] = int(eff_seed)
        if stop:
            payload["stop"] = stop
        if schema is not None:
            payload["response_format"] = openai_response_format(schema, max_items=max_items)

        started = time.perf_counter()
        try:
            response = self._http.post("/chat/completions", json=payload)
        except httpx.TimeoutException as exc:
            raise BackendTimeoutError(f"OpenAI timeout después de {self._timeout}s") from exc
        except httpx.TransportError as exc:
            raise BackendUnavailableError(
                f"OpenAI inalcanzable en {self._base_url}: {exc}"
            ) from exc
        latency_ms = (time.perf_counter() - started) * 1000.0

        raise_api_http_error("OpenAI", response, max_tokens=eff_max_tokens)
        data = json_object(response, "OpenAI")

        usage_raw = data.get("usage") if isinstance(data.get("usage"), dict) else {}
        usage = TokenUsage(
            prompt_tokens=int(usage_raw.get("prompt_tokens") or 0),
            completion_tokens=int(usage_raw.get("completion_tokens") or 0),
        )

        choices = data.get("choices")
        if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
            raise BackendError("OpenAI: respuesta sin choices[0]")
        choice = choices[0]
        message = choice.get("message") if isinstance(choice.get("message"), dict) else {}
        refusal = message.get("refusal")
        raw = message.get("content")
        if not isinstance(raw, str):
            raw = ""

        finish_raw = str(choice.get("finish_reason") or "")
        finish: FinishReason = "length" if finish_raw == "length" else "stop"
        if refusal:
            err = SchemaViolationError(f"OpenAI rechazó la salida estructurada: {refusal}")
            err.attach_usage(usage, latency_ms=latency_ms)
            raise err
        if schema is not None and finish == "length":
            err = ContextLengthExceededError(max_tokens=eff_max_tokens)
            err.attach_usage(usage, latency_ms=latency_ms)
            raise err

        parsed: BaseModel | None = None
        if schema is not None:
            try:
                parsed = schema.model_validate_json(raw)
            except ValidationError as exc:
                err = SchemaViolationError(
                    f"OpenAI response no valida contra {schema.__name__}: {exc}; raw={raw[:300]!r}"
                )
                err.attach_usage(usage, latency_ms=latency_ms)
                raise err from exc

        return LLMResponse(
            parsed=parsed,
            raw=raw,
            usage=usage,
            latency_ms=latency_ms,
            model_alias=self.alias,
            cache_hit=False,
            finish_reason=finish,
            extra={"provider": "openai", "model_id": str(data.get("model") or self._model_id)},
        )

    def close(self) -> None:
        self._http.close()
