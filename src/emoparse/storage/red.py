# ══════════════════════════════════════════════════════════════════════════════
#  emoparse.storage.red
#
#  Repositorio de las tablas `aristas` y `red_metricas`.
# ══════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

from typing import Any

import pandas as pd

from emoparse.storage.db import Database


class RedRepository:
    """Repositorio de `aristas` y `red_metricas`."""

    def __init__(self, db: Database) -> None:
        self._db = db

    def replace_edges(self, grafo: str, df_edges: pd.DataFrame) -> int:
        """Reemplaza las aristas de un grafo (idempotente)."""
        rows = df_edges.to_dict(orient="records")
        with self._db.transaction() as cur:
            cur.execute("DELETE FROM aristas WHERE grafo = ?", (grafo,))
            for r in rows:
                cur.execute(
                    "INSERT INTO aristas "
                    "(grafo, origen, destino, post_id, peso, fecha) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (
                        grafo, str(r["origen"]), str(r["destino"]),
                        _s(r.get("post_id")), float(r.get("peso", 1.0)),
                        _s(r.get("fecha")),
                    ),
                )
        return len(rows)

    def replace_metrics(
        self,
        grafo: str,
        df_metrics: pd.DataFrame,
        communities: dict[str, int] | None = None,
    ) -> int:
        """Reemplaza las métricas por nodo de un grafo (idempotente)."""
        communities = communities or {}
        rows = df_metrics.to_dict(orient="records")
        with self._db.transaction() as cur:
            cur.execute("DELETE FROM red_metricas WHERE grafo = ?", (grafo,))
            for r in rows:
                nodo = str(r["nodo"])
                cur.execute(
                    "INSERT INTO red_metricas "
                    "(grafo, nodo, grado_in, grado_out, grado_total, "
                    " pagerank, intermediacion, comunidad) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        grafo, nodo,
                        _i(r.get("grado_in")), _i(r.get("grado_out")),
                        _i(r.get("grado_total")),
                        _f(r.get("pagerank")), _f(r.get("intermediacion")),
                        communities.get(nodo),
                    ),
                )
        return len(rows)

    def load_edges(self, grafo: str) -> pd.DataFrame:
        """Aristas persistidas de un grafo."""
        rows = self._db.execute(
            "SELECT grafo, origen, destino, post_id, peso, fecha "
            "FROM aristas WHERE grafo = ?",
            (grafo,),
        ).fetchall()
        return pd.DataFrame([dict(r) for r in rows])

    def load_metrics(self, grafo: str) -> pd.DataFrame:
        """Métricas persistidas de un grafo, por PageRank descendente."""
        rows = self._db.execute(
            "SELECT * FROM red_metricas WHERE grafo = ? "
            "ORDER BY pagerank DESC",
            (grafo,),
        ).fetchall()
        return pd.DataFrame([dict(r) for r in rows])

    def grafos_disponibles(self) -> list[str]:
        """Grafos con aristas persistidas."""
        rows = self._db.execute(
            "SELECT DISTINCT grafo FROM aristas ORDER BY grafo"
        ).fetchall()
        return [str(r["grafo"]) for r in rows]


def _s(value: Any) -> str | None:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    s = str(value).strip()
    return s or None


def _i(value: Any) -> int | None:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    return int(value)


def _f(value: Any) -> float | None:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    return float(value)
