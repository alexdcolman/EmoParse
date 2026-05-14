# ══════════════════════════════════════════════════════════════════════════════
#  emoparse.storage.judgments
#
#  Repositorio de la tabla `judgments`.
# ══════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from emoparse.storage.db import Database


class JudgmentsRepository:
    """Repositorio de la tabla judgments."""

    def __init__(self, db: Database) -> None:
        self._db = db

    # ── Set veredicto ────────────────────────────────────────────────────────

    def set_judgment(
        self,
        codigo: str,
        frase_idx: int,
        emocion_idx: int,
        *,
        coherente: bool,
        issues: str,
        confianza: str,
        version: str | None = None,
    ) -> None:
        """Persiste un veredicto exitoso (upsert)."""
        with self._db.transaction() as cur:
            cur.execute(
                """
                INSERT INTO judgments (
                    codigo, frase_idx, emocion_idx,
                    coherente, issues, confianza,
                    judge_version, judge_error
                ) VALUES (?, ?, ?, ?, ?, ?, ?, NULL)
                ON CONFLICT(codigo, frase_idx, emocion_idx) DO UPDATE SET
                    coherente     = excluded.coherente,
                    issues        = excluded.issues,
                    confianza     = excluded.confianza,
                    judge_version = excluded.judge_version,
                    judge_error   = NULL,
                    updated_at    = ?
                """,
                (
                    codigo, frase_idx, emocion_idx,
                    1 if coherente else 0,
                    issues,
                    confianza,
                    version,
                    datetime.now(timezone.utc),
                ),
            )

    def set_error(
        self,
        codigo: str,
        frase_idx: int,
        emocion_idx: int,
        error_message: str,
    ) -> None:
        """Marca un juicio como fallido."""
        with self._db.transaction() as cur:
            cur.execute(
                """
                INSERT INTO judgments (
                    codigo, frase_idx, emocion_idx,
                    coherente, issues, confianza,
                    judge_version, judge_error
                ) VALUES (?, ?, ?, NULL, NULL, NULL, NULL, ?)
                ON CONFLICT(codigo, frase_idx, emocion_idx) DO UPDATE SET
                    coherente     = NULL,
                    issues        = NULL,
                    confianza     = NULL,
                    judge_version = NULL,
                    judge_error   = excluded.judge_error,
                    updated_at    = ?
                """,
                (
                    codigo, frase_idx, emocion_idx,
                    error_message,
                    datetime.now(timezone.utc),
                ),
            )

    # ── Lookup ───────────────────────────────────────────────────────────────

    def get_judgment(
        self,
        codigo: str,
        frase_idx: int,
        emocion_idx: int,
    ) -> dict[str, Any] | None:
        """Devuelve un juicio completo o None si no existe."""
        row = self._db.execute(
            """
            SELECT codigo, frase_idx, emocion_idx,
                   coherente, issues, confianza,
                   judge_version, judge_error,
                   created_at, updated_at
            FROM judgments
            WHERE codigo = ? AND frase_idx = ? AND emocion_idx = ?
            """,
            (codigo, frase_idx, emocion_idx),
        ).fetchone()
        if row is None:
            return None
        d = dict(row)
        if d["coherente"] is not None:
            d["coherente"] = bool(d["coherente"])
        return d

    def list_for_discurso(self, codigo: str) -> list[dict[str, Any]]:
        """Todos los juicios de un discurso."""
        rows = self._db.execute(
            """
            SELECT codigo, frase_idx, emocion_idx,
                   coherente, issues, confianza,
                   judge_version, judge_error
            FROM judgments
            WHERE codigo = ?
            ORDER BY frase_idx, emocion_idx
            """,
            (codigo,),
        ).fetchall()
        out: list[dict[str, Any]] = []
        for row in rows:
            d = dict(row)
            if d["coherente"] is not None:
                d["coherente"] = bool(d["coherente"])
            out.append(d)
        return out

    def list_pending(
        self,
        codigo: str | None = None,
    ) -> list[tuple[str, int, int]]:
        """Emociones caracterizadas que aún no fueron juzgadas."""
        sql = """
            SELECT e.codigo, e.frase_idx, e.emocion_idx
            FROM emociones e
            LEFT JOIN judgments j
                ON e.codigo = j.codigo
                AND e.frase_idx = j.frase_idx
                AND e.emocion_idx = j.emocion_idx
            WHERE e.caracterizacion_payload IS NOT NULL
              AND (j.codigo IS NULL OR (j.coherente IS NULL AND j.judge_error IS NULL))
        """
        params: tuple = ()
        if codigo is not None:
            sql += " AND e.codigo = ?"
            params = (codigo,)
        rows = self._db.execute(sql, params).fetchall()
        return [
            (row["codigo"], row["frase_idx"], row["emocion_idx"])
            for row in rows
        ]

    def clear_errors(self, codigo: str | None = None) -> int:
        """Borra rows con error para reintento."""
        sql = "DELETE FROM judgments WHERE judge_error IS NOT NULL"
        params: tuple = ()
        if codigo is not None:
            sql += " AND codigo = ?"
            params = (codigo,)
        with self._db.transaction() as cur:
            cur.execute(sql, params)
            return cur.rowcount

    def count_by_coherence(self, codigo: str | None = None) -> dict[str, int]:
        """Conteos simples de coherencia y errores."""
        sql = """
            SELECT
                SUM(CASE WHEN coherente = 1 THEN 1 ELSE 0 END) AS coherent,
                SUM(CASE WHEN coherente = 0 THEN 1 ELSE 0 END) AS incoherent,
                SUM(CASE WHEN judge_error IS NOT NULL THEN 1 ELSE 0 END) AS errors,
                COUNT(*) AS total
            FROM judgments
        """
        params: tuple = ()
        if codigo is not None:
            sql += " WHERE codigo = ?"
            params = (codigo,)
        row = self._db.execute(sql, params).fetchone()
        if row is None:
            return {"coherent": 0, "incoherent": 0, "errors": 0, "total": 0}
        return {
            "coherent": int(row["coherent"] or 0),
            "incoherent": int(row["incoherent"] or 0),
            "errors": int(row["errors"] or 0),
            "total": int(row["total"] or 0),
        }
