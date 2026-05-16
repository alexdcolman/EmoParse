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
        tipo_configuracion: str | None = None,
        deteccion_justificacion: str | None = None,
    ) -> None:
        """Insert/update de una emoción individual."""
        with self._db.transaction() as cur:
            cur.execute(
                """
                INSERT INTO emociones (
                    codigo, frase_idx, emocion_idx,
                    experienciador, tipo_emocion, modo_existencia,
                    tipo_configuracion,
                    deteccion_justificacion
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(codigo, frase_idx, emocion_idx) DO UPDATE SET
                    experienciador          = excluded.experienciador,
                    tipo_emocion            = excluded.tipo_emocion,
                    modo_existencia         = excluded.modo_existencia,
                    tipo_configuracion      = excluded.tipo_configuracion,
                    deteccion_justificacion = excluded.deteccion_justificacion,
                    updated_at              = ?
                """,
                (
                    codigo, frase_idx, emocion_idx,
                    experienciador, tipo_emocion, modo_existencia,
                    tipo_configuracion,
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
                r.get("tipo_configuracion"),
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
                    tipo_configuracion,
                    deteccion_justificacion
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(codigo, frase_idx, emocion_idx) DO UPDATE SET
                    experienciador          = excluded.experienciador,
                    tipo_emocion            = excluded.tipo_emocion,
                    modo_existencia         = excluded.modo_existencia,
                    tipo_configuracion      = excluded.tipo_configuracion,
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

    # ── Actantes ─────────────────────────────────────────────────────────────

    def set_actantes(
        self,
        codigo: str,
        frase_idx: int,
        emocion_idx: int,
        payload: dict[str, Any],
        version: str | None = None,
    ) -> None:
        """Marca una emoción como analizada actancialmente."""
        payload_str = json.dumps(payload, ensure_ascii=False, default=str)
        with self._db.transaction() as cur:
            cur.execute(
                """
                UPDATE emociones SET
                    actantes_payload = ?,
                    actantes_version = ?,
                    actantes_error   = NULL,
                    updated_at       = ?
                WHERE codigo = ? AND frase_idx = ? AND emocion_idx = ?
                """,
                (
                    payload_str, version,
                    datetime.now(timezone.utc),
                    codigo, frase_idx, emocion_idx,
                ),
            )

    def set_actantes_error(
        self,
        codigo: str,
        frase_idx: int,
        emocion_idx: int,
        error_message: str,
    ) -> None:
        """Marca una emoción como fallida en análisis actancial."""
        with self._db.transaction() as cur:
            cur.execute(
                """
                UPDATE emociones SET
                    actantes_payload = NULL,
                    actantes_version = NULL,
                    actantes_error   = ?,
                    updated_at       = ?
                WHERE codigo = ? AND frase_idx = ? AND emocion_idx = ?
                """,
                (
                    error_message,
                    datetime.now(timezone.utc),
                    codigo, frase_idx, emocion_idx,
                ),
            )

    def list_pending_actantes(
        self,
        codigo: str | None = None,
    ) -> list[tuple[str, int, int]]:
        """Emociones pendientes de análisis actancial (sin error)."""
        base_sql = (
            "SELECT codigo, frase_idx, emocion_idx FROM emociones "
            "WHERE actantes_payload IS NULL "
            "AND actantes_error IS NULL"
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

    def clear_actantes_errors(self, codigo: str | None = None) -> int:
        """Limpia errors de actantes para reintento."""
        sql = (
            "UPDATE emociones SET actantes_error = NULL "
            "WHERE actantes_error IS NOT NULL"
        )
        params: tuple = ()
        if codigo is not None:
            sql += " AND codigo = ?"
            params = (codigo,)
        with self._db.transaction() as cur:
            cur.execute(sql, params)
            return cur.rowcount

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

    # ── Normalización ────────────────────────────────────────────────────────

    def get_emocion(
        self,
        codigo: str,
        frase_idx: int,
        emocion_idx: int,
    ) -> dict[str, Any] | None:
        """Devuelve una emoción individual como dict, o None si no existe."""
        row = self._db.execute(
            "SELECT * FROM emociones "
            "WHERE codigo = ? AND frase_idx = ? AND emocion_idx = ?",
            (codigo, frase_idx, emocion_idx),
        ).fetchone()
        return dict(row) if row is not None else None

    def set_normalized_emotion(
        self,
        codigo: str,
        frase_idx: int,
        emocion_idx: int,
        tipo_emocion_canonico: str | None,
        version: str | None = None,
    ) -> None:
        """Escribe el canónico de emoción (NULL si no matchea ontología)."""
        with self._db.transaction() as cur:
            cur.execute(
                """
                UPDATE emociones SET
                    tipo_emocion_canonico      = ?,
                    normalize_emotions_version = ?,
                    updated_at                 = ?
                WHERE codigo = ? AND frase_idx = ? AND emocion_idx = ?
                """,
                (
                    tipo_emocion_canonico, version,
                    datetime.now(timezone.utc),
                    codigo, frase_idx, emocion_idx,
                ),
            )

    def list_pending_normalization(
        self,
        codigo: str | None = None,
    ) -> list[tuple[str, int, int]]:
        """Emociones con tipo_emocion no nulo y tipo_emocion_canonico nulo."""
        base_sql = (
            "SELECT codigo, frase_idx, emocion_idx FROM emociones "
            "WHERE tipo_emocion IS NOT NULL "
            "AND tipo_emocion_canonico IS NULL"
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
