"""Utilidades HTTP compartidas por los backends de API remota."""

from __future__ import annotations

from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import Any

import httpx

from emoparse.core.backend.exceptions import (
    BackendConfigError,
    BackendError,
    BackendUnavailableError,
    ContextLengthExceededError,
    SchemaViolationError,
)


def retry_after_seconds(response: httpx.Response) -> float | None:
    """Interpreta Retry-After como segundos o fecha HTTP."""
    raw = response.headers.get("retry-after")
    if raw is None:
        return None
    raw = raw.strip()
    if not raw:
        return None
    try:
        return max(0.0, float(raw))
    except ValueError:
        pass
    try:
        when = parsedate_to_datetime(raw)
    except (TypeError, ValueError, OverflowError):
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=UTC)
    return max(0.0, (when - datetime.now(UTC)).total_seconds())


def response_error_text(response: httpx.Response) -> str:
    """Extrae un mensaje breve sin incluir headers ni credenciales."""
    try:
        payload = response.json()
    except ValueError:
        return response.text[:500]
    if isinstance(payload, dict):
        error = payload.get("error")
        if isinstance(error, dict):
            message = error.get("message")
            if message:
                return str(message)[:500]
        if isinstance(error, str):
            return error[:500]
        message = payload.get("message")
        if message:
            return str(message)[:500]
    return str(payload)[:500]


def raise_api_http_error(
    provider: str,
    response: httpx.Response,
    *,
    max_tokens: int | None,
) -> None:
    """Mapea estados HTTP a la taxonomía común de EmoParse."""
    if response.is_success:
        return

    status = response.status_code
    message = response_error_text(response)
    lower = message.lower()
    prefix = f"{provider} HTTP {status}: {message}"

    if status in {401, 403}:
        raise BackendConfigError(f"{provider}: credenciales rechazadas ({status})")

    if status == 429 or status >= 500:
        raise BackendUnavailableError(
            prefix,
            retry_after_seconds=retry_after_seconds(response),
        )

    if status == 400:
        if any(
            marker in lower
            for marker in (
                "context length",
                "context_length",
                "context window",
                "maximum context",
                "too many tokens",
                "prompt is too long",
            )
        ):
            raise ContextLengthExceededError(max_tokens=max_tokens)
        if any(
            marker in lower
            for marker in (
                "json_schema",
                "json schema",
                "response_format",
                "output_config",
                "structured output",
                "schema",
            )
        ):
            raise SchemaViolationError(prefix)

    raise BackendError(prefix)


def json_object(response: httpx.Response, provider: str) -> dict[str, Any]:
    try:
        payload = response.json()
    except ValueError as exc:
        raise BackendError(f"{provider}: respuesta HTTP no es JSON válido") from exc
    if not isinstance(payload, dict):
        raise BackendError(f"{provider}: respuesta JSON inesperada ({type(payload).__name__})")
    return payload
