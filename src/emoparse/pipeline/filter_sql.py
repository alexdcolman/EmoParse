# ══════════════════════════════════════════════════════════════════════════════
#  emoparse.pipeline.filter_sql
#
#  Traducción compartida de filtros declarativos a SQL sobre payloads JSON.
# ══════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

from typing import Any, Protocol


class JsonFilter(Protocol):
    """Contrato mínimo de un filtro declarativo sobre JSON."""

    field: str
    op: str
    value: Any


def where_for_json_filters(
    filters: list[JsonFilter],
    payload_expr: str,
    *,
    case_sensitive_contains: bool = True,
) -> tuple[list[str], list[Any]]:
    """Convierte filtros a cláusulas SQL y parámetros.

    `payload_expr` puede ser una columna JSON o una expresión que devuelva JSON.
    Los paths ya deben estar validados por el modelo que declara el filtro.
    """
    clauses: list[str] = []
    params: list[Any] = []
    for item in filters:
        json_path = "$." + item.field
        extracted = f"json_extract({payload_expr}, '{json_path}')"
        if item.op == "eq":
            clauses.append(f"{extracted} = ?")
            params.append(item.value)
        elif item.op == "ne":
            clauses.append(f"{extracted} != ?")
            params.append(item.value)
        elif item.op == "in":
            values = list(item.value)
            if not values:
                clauses.append("0")
            else:
                placeholders = ", ".join(["?"] * len(values))
                clauses.append(f"{extracted} IN ({placeholders})")
                params.extend(values)
        elif item.op == "contains":
            escaped = str(item.value).replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            collate = "" if case_sensitive_contains else " COLLATE NOCASE"
            clauses.append(f"{extracted} LIKE ? ESCAPE '\\'{collate}")
            params.append(f"%{escaped}%")
        elif item.op == "gte":
            clauses.append(f"{extracted} >= ?")
            params.append(item.value)
        elif item.op == "lte":
            clauses.append(f"{extracted} <= ?")
            params.append(item.value)
        elif item.op == "between":
            lower, upper = item.value
            if lower is not None:
                clauses.append(f"{extracted} >= ?")
                params.append(lower)
            if upper is not None:
                clauses.append(f"{extracted} <= ?")
                params.append(upper)
        elif item.op == "is_null":
            clauses.append(f"{extracted} IS NULL")
        elif item.op == "is_not_null":
            clauses.append(f"{extracted} IS NOT NULL")
        else:
            raise ValueError(f"op desconocida: {item.op}")
    return clauses, params
