"""Redacción de secretos antes de persistir configuración de runs."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

_SECRET_KEYS = {"api_key", "authorization", "x-api-key"}


def sanitize_config_snapshot(value: Any) -> Any:
    """Copia una estructura omitiendo credenciales conocidas recursivamente."""
    if isinstance(value, Mapping):
        return {
            str(key): sanitize_config_snapshot(item)
            for key, item in value.items()
            if str(key).lower() not in _SECRET_KEYS
        }
    if isinstance(value, list):
        return [sanitize_config_snapshot(item) for item in value]
    if isinstance(value, tuple):
        return [sanitize_config_snapshot(item) for item in value]
    return value
