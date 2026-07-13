# ══════════════════════════════════════════════════════════════════════════════
#  emoparse.storage.analytics
#
#  Capa analítica opcional sobre la SQLite de un run, vía DuckDB.
#
#  Para corpus grandes (decenas de miles de unidades), las agregaciones del
#  dashboard y de los exports son mucho más rápidas en DuckDB que en SQLite.
#  Este módulo NO reemplaza a `storage.db`: la SQLite sigue siendo la única
#  fuente de verdad; DuckDB la lee en modo read-only (ATTACH), sin copiar.
#
#  Requiere el extra `analytics` (pip install -e ".[analytics]").
# ══════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

from pathlib import Path
from typing import Any


class AnalyticsUnavailableError(RuntimeError):
    """DuckDB no está instalado o no pudo attachear la DB."""


def attach_run(db_path: Path | str, alias: str = "run") -> Any:
    """Abre una conexión DuckDB con la SQLite del run attacheada read-only.

    Devuelve una conexión DuckDB en la que las tablas del run quedan
    accesibles como `<alias>.<tabla>` (p. ej. ``SELECT * FROM run.emociones``).

    Raises:
        AnalyticsUnavailableError: si duckdb no está instalado o el attach
            falla (path inexistente, archivo corrupto, etc.).
    """
    p = Path(db_path).expanduser().resolve()
    if not p.is_file():
        raise AnalyticsUnavailableError(f"DB no encontrada: {p}")
    try:
        import duckdb
    except ImportError as e:
        raise AnalyticsUnavailableError(
            "DuckDB no está instalado. Instalá el extra: "
            'pip install -e ".[analytics]"'
        ) from e
    try:
        con = duckdb.connect(database=":memory:")
        con.execute(
            f"ATTACH '{p.as_posix()}' AS {alias} (TYPE SQLITE, READ_ONLY)"
        )
    except Exception as e:  # duckdb expone jerarquías propias según versión
        raise AnalyticsUnavailableError(
            f"No pude attachear {p} en DuckDB: {e}"
        ) from e
    return con


def query_df(con: Any, sql: str) -> Any:
    """Ejecuta SQL sobre la conexión analítica y devuelve un DataFrame pandas."""
    return con.execute(sql).df()
