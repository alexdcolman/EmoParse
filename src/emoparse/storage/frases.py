# ══════════════════════════════════════════════════════════════════════════════
#  emoparse.storage.frases
#
#  Repositorio de la tabla `frases`.
# ══════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

import json
from collections.abc import Iterable
from datetime import datetime, timezone
from typing import Any, Literal

from emoparse.storage.db import Database

FraseStage = Literal["actores", "emociones", "emociones_pass2", "actores_canonicos"]
_VALID_STAGES: tuple[FraseStage, ...] = (
    "actores",
    "emociones",
    "emociones_pass2",
    "actores_canonicos",
)


class FrasesRepository:
    """Repositorio de frases individuales."""

    def __init__(self, db: Database) -> None:
        self._db = db

    # ── Insertar frases ──────────────────────────────────────────────────────

    def upsert_frase(
        self,
        codigo: str,
        unit_idx: int,
        frase: str,
    ) -> None:
        """Insert/update de una frase individual."""
        with self._db.transaction() as cur:
            cur.execute(
                """
                INSERT INTO frases (codigo, unit_idx, frase)
                VALUES (?, ?, ?)
                ON CONFLICT(codigo, unit_idx) DO UPDATE SET
                    frase = excluded.frase,
                    updated_at = ?
                """,
                (codigo, unit_idx, frase, datetime.now(timezone.utc)),
            )

    def upsert_frases(
        self,
        rows: Iterable[tuple[str, int, str]],
    ) -> None:
        """Bulk insert/update de frases."""
        now = datetime.now(timezone.utc)
        params = [(codigo, idx, frase, now) for codigo, idx, frase in rows]
        with self._db.transaction() as cur:
            cur.executemany(
                """
                INSERT INTO frases (codigo, unit_idx, frase)
                VALUES (?, ?, ?)
                ON CONFLICT(codigo, unit_idx) DO UPDATE SET
                    frase = excluded.frase,
                    updated_at = ?
                """,
                params,
            )

    # ── Outputs por etapa ────────────────────────────────────────────────────

    def set_payload(
        self,
        codigo: str,
        unit_idx: int,
        stage: FraseStage,
        payload: list[dict[str, Any]] | dict[str, Any],
        version: str | None = None,
    ) -> None:
        """Marca una etapa como completada para una frase."""
        self._validate_stage(stage)
        col_payload = f"{stage}_payload"
        col_version = f"{stage}_version"
        col_error = f"{stage}_error"
        payload_str = json.dumps(payload, ensure_ascii=False, default=str)

        with self._db.transaction() as cur:
            cur.execute(
                f"""
                UPDATE frases SET
                    {col_payload} = ?,
                    {col_version} = ?,
                    {col_error}   = NULL,
                    updated_at    = ?
                WHERE codigo = ? AND unit_idx = ?
                """,
                (
                    payload_str,
                    version,
                    datetime.now(timezone.utc),
                    codigo,
                    unit_idx,
                ),
            )

    def set_error(
        self,
        codigo: str,
        unit_idx: int,
        stage: FraseStage,
        error_message: str,
    ) -> None:
        """Marca una etapa como fallida para una frase."""
        self._validate_stage(stage)
        col_payload = f"{stage}_payload"
        col_version = f"{stage}_version"
        col_error = f"{stage}_error"
        with self._db.transaction() as cur:
            cur.execute(
                f"""
                UPDATE frases SET
                    {col_payload} = NULL,
                    {col_version} = NULL,
                    {col_error}   = ?,
                    updated_at    = ?
                WHERE codigo = ? AND unit_idx = ?
                """,
                (
                    error_message,
                    datetime.now(timezone.utc),
                    codigo,
                    unit_idx,
                ),
            )

    # ── Lookup ───────────────────────────────────────────────────────────────

    def get_frase(self, codigo: str, unit_idx: int) -> str | None:
        """Devuelve el texto de una frase."""
        row = self._db.execute(
            "SELECT frase FROM frases WHERE codigo = ? AND unit_idx = ?",
            (codigo, unit_idx),
        ).fetchone()
        return row["frase"] if row else None

    def get_payload(
        self,
        codigo: str,
        unit_idx: int,
        stage: FraseStage,
    ) -> list[dict[str, Any]] | dict[str, Any] | None:
        """Devuelve el payload de una etapa para una frase."""
        self._validate_stage(stage)
        col = f"{stage}_payload"
        row = self._db.execute(
            f"SELECT {col} FROM frases WHERE codigo = ? AND unit_idx = ?",
            (codigo, unit_idx),
        ).fetchone()
        if row is None or row[col] is None:
            return None
        return json.loads(row[col])

    def list_frases_of_discurso(
        self,
        codigo: str,
    ) -> list[tuple[int, str]]:
        """Todas las frases de un discurso, ordenadas por unit_idx."""
        rows = self._db.execute(
            """
            SELECT unit_idx, frase FROM frases
            WHERE codigo = ?
            ORDER BY unit_idx
            """,
            (codigo,),
        ).fetchall()
        return [(row["unit_idx"], row["frase"]) for row in rows]

    def list_pending(
        self,
        stage: FraseStage,
        codigo: str | None = None,
    ) -> list[tuple[str, int]]:
        """Frases pendientes de una etapa (payload NULL y error NULL)."""
        self._validate_stage(stage)
        col_payload = f"{stage}_payload"
        col_error = f"{stage}_error"
        base_sql = (
            f"SELECT codigo, unit_idx FROM frases "
            f"WHERE {col_payload} IS NULL AND {col_error} IS NULL"
        )
        if codigo is None:
            rows = self._db.execute(base_sql).fetchall()
        else:
            rows = self._db.execute(
                base_sql + " AND codigo = ?", (codigo,)
            ).fetchall()
        return [(row["codigo"], row["unit_idx"]) for row in rows]

    def clear_errors(
        self,
        stage: FraseStage,
        codigo: str | None = None,
    ) -> int:
        """Limpia errores de una etapa para reintento."""
        self._validate_stage(stage)
        col_error = f"{stage}_error"
        sql = f"UPDATE frases SET {col_error} = NULL WHERE {col_error} IS NOT NULL"
        params: tuple = ()
        if codigo is not None:
            sql += " AND codigo = ?"
            params = (codigo,)
        with self._db.transaction() as cur:
            cur.execute(sql, params)
            return cur.rowcount

    @staticmethod
    def _validate_stage(stage: str) -> None:
        """Valida que el nombre de etapa sea correcto."""
        if stage not in _VALID_STAGES:
            raise ValueError(
                f"Stage '{stage}' inválida. Válidas: {_VALID_STAGES}"
            )
