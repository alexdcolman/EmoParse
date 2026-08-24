"""Helpers compartidos para salida estructurada basada en JSON Schema."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from pydantic import BaseModel

_ANTHROPIC_UNSUPPORTED_CONSTRAINTS = {
    "exclusiveMaximum",
    "exclusiveMinimum",
    "maxItems",
    "maxLength",
    "maximum",
    "minItems",
    "minLength",
    "minimum",
    "multipleOf",
}
_ANTHROPIC_SUPPORTED_STRING_FORMATS = {
    "date-time",
    "date",
    "time",
    "duration",
    "email",
    "hostname",
    "ipv4",
    "ipv6",
    "uuid",
    "uri",
}


def pydantic_to_json_schema_strict(
    schema: type[BaseModel],
    *,
    max_items: int | None = None,
) -> dict[str, Any]:
    """Convierte un schema Pydantic al contrato estricto usado por OpenAI.

    Mantiene el comportamiento histórico del backend LM Studio: todos los
    objetos rechazan propiedades adicionales y todos sus campos se marcan como
    requeridos. Si el schema raíz es un array de batch, ``max_items`` fija su
    cardinalidad exacta.
    """
    json_schema = deepcopy(schema.model_json_schema())
    _add_strict_flags(json_schema)
    if max_items is not None and json_schema.get("type") == "array":
        n = max(1, int(max_items))
        json_schema["minItems"] = n
        json_schema["maxItems"] = n
    return json_schema


def openai_response_format(
    schema: type[BaseModel],
    *,
    max_items: int | None = None,
) -> dict[str, Any]:
    """Construye ``response_format`` para APIs OpenAI-compatible."""
    return {
        "type": "json_schema",
        "json_schema": {
            "name": _schema_name(schema),
            "schema": pydantic_to_json_schema_strict(schema, max_items=max_items),
            "strict": True,
        },
    }


def anthropic_output_schema(
    schema: type[BaseModel],
    *,
    max_items: int | None = None,
) -> dict[str, Any]:
    """Adapta Pydantic al subconjunto de JSON Schema de Anthropic.

    Anthropic elimina algunas restricciones al compilar salidas estructuradas;
    EmoParse replica esa frontera porque usa HTTP directo en lugar del SDK. La
    respuesta se valida después contra el schema Pydantic original, de modo que
    esas restricciones no se pierden como contrato del proyecto.
    """
    original = pydantic_to_json_schema_strict(schema, max_items=max_items)
    transformed = _transform_anthropic_node(original)

    # Anthropic no soporta minItems/maxItems en structured outputs. Para batches
    # la cardinalidad exacta sigue siendo verificada después por Pydantic y por
    # los contratos unit_idx del agente.
    transformed.pop("minItems", None)
    transformed.pop("maxItems", None)
    return transformed


def _schema_name(schema: type[BaseModel]) -> str:
    raw = schema.__name__ or "emoparse_result"
    cleaned = "".join(ch if ch.isalnum() or ch in "_-" else "_" for ch in raw)
    return cleaned[:64] or "emoparse_result"


def _add_strict_flags(node: Any) -> None:
    if isinstance(node, dict):
        if node.get("type") == "object":
            node.setdefault("additionalProperties", False)
            properties = node.get("properties", {})
            if isinstance(properties, dict) and properties:
                node["required"] = list(properties.keys())
        for value in node.values():
            _add_strict_flags(value)
    elif isinstance(node, list):
        for item in node:
            _add_strict_flags(item)


def _transform_anthropic_node(node: Any) -> Any:
    if isinstance(node, list):
        return [_transform_anthropic_node(item) for item in node]
    if not isinstance(node, dict):
        return node

    out: dict[str, Any] = {}
    for key, value in node.items():
        if key in _ANTHROPIC_UNSUPPORTED_CONSTRAINTS:
            continue
        if key == "format" and value not in _ANTHROPIC_SUPPORTED_STRING_FORMATS:
            continue
        out[key] = _transform_anthropic_node(value)

    if out.get("type") == "object":
        out["additionalProperties"] = False
    return out
