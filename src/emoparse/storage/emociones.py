# ══════════════════════════════════════════════════════════════════════════════
#  emoparse.storage.emociones
#
#  Repositorio de la tabla `emociones`.
# ══════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

import json
from collections.abc import Iterable
from datetime import datetime, timezone
from typing import Any

from emoparse.storage.db import Database


class EmocionesRepository:
    """Repositorio de emociones individuales."""

    def __init__(self, db: Database) -> None:
        self._db = db

    # ── Insert (explode) ─────────────────────────────────────────────────────

    def upsert_emocion(
        self,
        codigo: str,
        frase_idx: int,
        emocion_idx: int,
        experienciador: str,
        tipo_emocion: str,
        modo_existencia: str,
        deteccion_justificacion: str | None = None,
    ) -> None:
        """Insert/update de una emoción individual."""
        with self._db.transaction() as cur:
            cur.execute(
                """
                INSERT INTO emociones (
                    codigo, frase_idx, emocion_idx,
                    experienciador, tipo_emocion, modo_existencia,
                    deteccion_justificacion
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(codigo, frase_idx, emocion_idx) DO UPDATE SET
                    experienciador          = excluded.experienciador,
                    tipo_emocion            = excluded.tipo_emocion,
                    modo_existencia         = excluded.modo_existencia,
                    deteccion_justificacion = excluded.deteccion_justificacion,
                    updated_at              = ?
                """,
                (
                    codigo, frase_idx, emocion_idx,
                    experienciador, tipo_emocion, modo_existencia,
                    deteccion_justificacion,
                    datetime.now(timezone.utc),
                ),
            )

    def upsert_emociones(
        self,
        rows: Iterable[dict[str, Any]],
    ) -> None:
        """Bulk insert/update de emociones."""
        now = datetime.now(timezone.utc)
        params = [
            (
                r["codigo"], r["frase_idx"], r["emocion_idx"],
                r["experienciador"], r["tipo_emocion"], r["modo_existencia"],
                r.get("deteccion_justificacion"),
                now,
            )
            for r in rows
        ]
        with self._db.transaction() as cur:
            cur.executemany(
                """
                INSERT INTO emociones (
                    codigo, frase_idx, emocion_idx,
                    experienciador, tipo_emocion, modo_existencia,
                    deteccion_justificacion
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(codigo, frase_idx, emocion_idx) DO UPDATE SET
                    experienciador          = excluded.experienciador,
                    tipo_emocion            = excluded.tipo_emocion,
                    modo_existencia         = excluded.modo_existencia,
                    deteccion_justificacion = excluded.deteccion_justificacion,
                    updated_at              = ?
                """,
                params,
            )

    # ── Caracterización ──────────────────────────────────────────────────────

    def set_caracterizacion(
        self,
        codigo: str,
        frase_idx: int,
        emocion_idx: int,
        payload: dict[str, Any],
        version: str | None = None,
    ) -> None:
        """Marca una emoción como caracterizada exitosamente."""
        payload_str = json.dumps(payload, ensure_ascii=False, default=str)
        with self._db.transaction() as cur:
            cur.execute(
                """
                UPDATE emociones SET
                    caracterizacion_payload = ?,
                    caracterizacion_version = ?,
                    caracterizacion_error   = NULL,
                    updated_at              = ?
                WHERE codigo = ? AND frase_idx = ? AND emocion_idx = ?
                """,
                (
                    payload_str, version,
                    datetime.now(timezone.utc),
                    codigo, frase_idx, emocion_idx,
                ),
            )

    def set_caracterizacion_error(
        self,
        codigo: str,
        frase_idx: int,
        emocion_idx: int,
        error_message: str,
    ) -> None:
        """Marca una emoción como fallida en caracterización."""
        with self._db.transaction() as cur:
            cur.execute(
                """
                UPDATE emociones SET
                    caracterizacion_payload = NULL,
                    caracterizacion_version = NULL,
                    caracterizacion_error   = ?,
                    updated_at              = ?
                WHERE codigo = ? AND frase_idx = ? AND emocion_idx = ?
                """,
                (
                    error_message,
                    datetime.now(timezone.utc),
                    codigo, frase_idx, emocion_idx,
                ),
            )

    # ── Lookup ───────────────────────────────────────────────────────────────

    def list_emociones_of_discurso(
        self,
        codigo: str,
    ) -> list[dict[str, Any]]:
        """Todas las emociones de un discurso, ordenadas por (frase, emocion)."""
        rows = self._db.execute(
            """
            SELECT * FROM emociones
            WHERE codigo = ?
            ORDER BY frase_idx, emocion_idx
            """,
            (codigo,),
        ).fetchall()
        return [dict(row) for row in rows]

    def list_pending_caracterizacion(
        self,
        codigo: str | None = None,
    ) -> list[tuple[str, int, int]]:
        """Emociones pendientes de caracterización (sin error)."""
        base_sql = (
            "SELECT codigo, frase_idx, emocion_idx FROM emociones "
            "WHERE caracterizacion_payload IS NULL "
            "AND caracterizacion_error IS NULL"
        )
        if codigo is None:
            rows = self._db.execute(base_sql).fetchall()
        else:
            rows = self._db.execute(
                base_sql + " AND codigo = ?", (codigo,)
            ).fetchall()
        return [
            (row["codigo"], row["frase_idx"], row["emocion_idx"])
            for row in rows
        ]

    def clear_errors(self, codigo: str | None = None) -> int:
        """Limpia errors de caracterización para reintento."""
        sql = (
            "UPDATE emociones SET caracterizacion_error = NULL "
            "WHERE caracterizacion_error IS NOT NULL"
        )
        params: tuple = ()
        if codigo is not None:
            sql += " AND codigo = ?"
            params = (codigo,)
        with self._db.transaction() as cur:
            cur.execute(sql, params)
            return cur.rowcount
