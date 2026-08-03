"""Resolución determinista del referente emisor desde metadata de entrada."""

from __future__ import annotations

import json
from typing import Any


def resolve_from_input_field(
    row: dict[str, Any],
    field: str,
) -> tuple[str, str]:
    """Devuelve referente y evidencia desde un campo del input del género."""
    referents = normalize_referents(_input_value(row, field))
    if not referents:
        return "", ""
    return (
        format_referents(referents),
        f"Autoría declarada en la metadata del campo `{field}`.",
    )


def normalize_referents(value: Any) -> tuple[str, ...]:
    """Normaliza string, JSON o colección de nombres y elimina duplicados."""
    if _is_missing(value):
        return ()

    if isinstance(value, str):
        raw = value.strip()
        if not raw:
            return ()
        if raw.startswith("["):
            try:
                value = json.loads(raw)
            except json.JSONDecodeError:
                value = raw
        if isinstance(value, str):
            parts = [part.strip() for part in value.replace("|", ";").split(";")]
            return tuple(dict.fromkeys(part for part in parts if part))

    if isinstance(value, (list, tuple, set)):
        values = (str(item).strip() for item in value if not _is_missing(item))
        return tuple(dict.fromkeys(item for item in values if item))

    text = str(value).strip()
    return (text,) if text else ()


def format_referents(referents: tuple[str, ...]) -> str:
    """Representación legible de una autoría simple o colectiva."""
    if len(referents) == 1:
        return referents[0]
    if len(referents) == 2:
        return f"{referents[0]} y {referents[1]}"
    return f"{', '.join(referents[:-1])} y {referents[-1]}"


def _input_value(row: dict[str, Any], field: str) -> Any:
    direct = row.get(field)
    if not _is_missing(direct):
        return direct

    raw_input = row.get("input")
    if isinstance(raw_input, dict):
        return raw_input.get(field)
    if isinstance(raw_input, str) and raw_input.strip():
        try:
            parsed = json.loads(raw_input)
        except json.JSONDecodeError:
            return None
        if isinstance(parsed, dict):
            return parsed.get(field)
    return None


def _is_missing(value: Any) -> bool:
    if value is None:
        return True
    try:
        return bool(value != value)
    except (TypeError, ValueError):
        return False


__all__ = ["format_referents", "normalize_referents", "resolve_from_input_field"]
