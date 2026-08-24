"""Backend remoto para Anthropic Messages API."""

from __future__ import annotations

import os
import time
from typing import Any, TypeVar

import httpx
from pydantic import BaseModel, ValidationError

from emoparse.core.backend.base import FinishReason, LLMBackend, LLMResponse, TokenUsage
from emoparse.core.backend.exceptions import (
    BackendConfigError,
    BackendTimeoutError,
    BackendUnavailableError,
    ContextLengthExceededError,
    SchemaViolationError,
)
from emoparse.core.backend.http_api import json_object, raise_api_http_error
from emoparse.core.backend.structured import anthropic_output_schema

T = TypeVar("T", bound=BaseModel)

_DEFAULT_BASE_URL = "https://api.anthropic.com/v1"
_DEFAULT_VERSION = "2023-06-01"
_DEFAULT_MAX_TOKENS = 2048
_DEFAULT_TEMPERATURE = 0.0
_DEFAULT_TIMEOUT = 90.0


class AnthropicBackend(LLMBackend):
    """Anthropic Messages vía HTTP directo y structured outputs nativos."""

    def __init__(self, alias: str, model_config: dict[str, Any]) -> None:
        self.alias = alias
        self._cfg = dict(model_config)
        self._model_id = str(self._cfg.get("model_id") or "").strip()
        if not self._model_id:
            raise BackendConfigError(f"Anthropic:{alias} requiere model_id")
        self._base_url = str(self._cfg.get("base_url") or _DEFAULT_BASE_URL).rstrip("/")
        self._version = str(self._cfg.get("anthropic_version") or _DEFAULT_VERSION)
        self._default_max_tokens = int(self._cfg.get("max_tokens", _DEFAULT_MAX_TOKENS))
        self._default_temperature = float(self._cfg.get("temperature", _DEFAULT_TEMPERATURE))
        self._timeout = float(self._cfg.get("timeout") or _DEFAULT_TIMEOUT)

        api_key = self._resolve_api_key()
        self._http = httpx.Client(
            base_url=self._base_url,
            headers={
                "x-api-key": api_key,
                "anthropic-version": self._version,
                "content-type": "application/json",
            },
            timeout=self._timeout,
        )

    def _resolve_api_key(self) -> str:
        direct = self._cfg.get("api_key")
        if direct:
            return str(direct)
        env_name = str(self._cfg.get("api_key_env") or "ANTHROPIC_API_KEY")
        value = os.environ.get(env_name)
        if value:
            return value
        raise BackendConfigError(
            f"Anthropic:{self.alias} requiere la variable de entorno {env_name} "
            "o api_key en el config"
        )

    def healthcheck(self) -> bool:
        # Anthropic no expone un endpoint de modelos equivalente que sea una
        # comprobación barata y universal. Una key presente + cliente válido no
        # justifica consumir tokens en un healthcheck implícito.
        return True

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
        del reset_before, seed
        if images:
            raise BackendConfigError("Anthropic backend 3.2A todavía no acepta images")

        eff_max_tokens = max_tokens if max_tokens is not None else self._default_max_tokens
        eff_temp = temperature if temperature is not None else self._default_temperature

        payload: dict[str, Any] = {
            "model": self._model_id,
            "max_tokens": eff_max_tokens,
            "temperature": eff_temp,
            "messages": [{"role": "user", "content": user}],
        }
        if system:
            payload["system"] = system
        if stop:
            payload["stop_sequences"] = stop
        if schema is not None:
            payload["output_config"] = {
                "format": {
                    "type": "json_schema",
                    "schema": anthropic_output_schema(schema, max_items=max_items),
                }
            }

        started = time.perf_counter()
        try:
            response = self._http.post("/messages", json=payload)
        except httpx.TimeoutException as exc:
            raise BackendTimeoutError(f"Anthropic timeout después de {self._timeout}s") from exc
        except httpx.TransportError as exc:
            raise BackendUnavailableError(
                f"Anthropic inalcanzable en {self._base_url}: {exc}"
            ) from exc
        latency_ms = (time.perf_counter() - started) * 1000.0

        raise_api_http_error("Anthropic", response, max_tokens=eff_max_tokens)
        data = json_object(response, "Anthropic")

        usage_raw = data.get("usage") if isinstance(data.get("usage"), dict) else {}
        usage = TokenUsage(
            prompt_tokens=int(usage_raw.get("input_tokens") or 0),
            completion_tokens=int(usage_raw.get("output_tokens") or 0),
        )
        stop_reason = str(data.get("stop_reason") or "")

        content = data.get("content")
        text_blocks = (
            [block for block in content if isinstance(block, dict) and block.get("type") == "text"]
            if isinstance(content, list)
            else []
        )
        raw = "".join(str(block.get("text") or "") for block in text_blocks)

        if stop_reason == "refusal":
            err = SchemaViolationError("Anthropic rechazó la solicitud durante structured output")
            err.attach_usage(usage, latency_ms=latency_ms)
            raise err
        if stop_reason == "max_tokens":
            if schema is not None:
                err = ContextLengthExceededError(max_tokens=eff_max_tokens)
                err.attach_usage(usage, latency_ms=latency_ms)
                raise err
            finish: FinishReason = "length"
        elif stop_reason in {"end_turn", "stop_sequence", ""}:
            finish = "stop"
        else:
            finish = "error"

        parsed: BaseModel | None = None
        if schema is not None:
            try:
                parsed = schema.model_validate_json(raw)
            except ValidationError as exc:
                err = SchemaViolationError(
                    "Anthropic response no valida contra "
                    f"{schema.__name__}: {exc}; raw={raw[:300]!r}"
                )
                err.attach_usage(usage, latency_ms=latency_ms)
                raise err from exc
            root = getattr(parsed, "root", None)
            if max_items is not None and isinstance(root, list) and len(root) != max_items:
                err = SchemaViolationError(
                    "Anthropic response no respeta la cardinalidad esperada del batch: "
                    f"esperados={max_items}, recibidos={len(root)}"
                )
                err.attach_usage(usage, latency_ms=latency_ms)
                raise err

        return LLMResponse(
            parsed=parsed,
            raw=raw,
            usage=usage,
            latency_ms=latency_ms,
            model_alias=self.alias,
            cache_hit=False,
            finish_reason=finish,
            extra={"provider": "anthropic", "model_id": str(data.get("model") or self._model_id)},
        )

    def close(self) -> None:
        self._http.close()
