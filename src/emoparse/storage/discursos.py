# ══════════════════════════════════════════════════════════════════════════════
#  emoparse.storage.discursos
#
#  Repositorio de la tabla `discursos`
# ══════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

import json
from collections.abc import Iterable
from datetime import datetime, timezone
from typing import Any, Literal

from emoparse.storage.db import Database

#: Etapas válidas para esta tabla.
DiscursoStage = Literal["summarizer", "metadata", "enunciation"]
_VALID_STAGES: tuple[DiscursoStage, ...] = ("summarizer", "metadata", "enunciation")


class DiscursosRepository:
    """Repositorio de discursos completos."""

    def __init__(self, db: Database) -> None:
        self._db = db

    # ── Insert input ─────────────────────────────────────────────────────────

    def upsert_input(self, codigo: str, input_payload: dict[str, Any]) -> None:
        """Guarda o actualiza el input de un discurso."""
        payload_str = json.dumps(input_payload, ensure_ascii=False, default=str)
        with self._db.transaction() as cur:
            cur.execute(
                """
                INSERT INTO discursos (codigo, input)
                VALUES (?, ?)
                ON CONFLICT(codigo) DO UPDATE SET
                    input = excluded.input,
                    updated_at = ?
                """,
                (codigo, payload_str, datetime.now(timezone.utc)),
            )

    def upsert_inputs(
        self,
        rows: Iterable[tuple[str, dict[str, Any]]],
    ) -> None:
        """Bulk insert/update de inputs."""
        now = datetime.now(timezone.utc)
        params = [
            (codigo, json.dumps(payload, ensure_ascii=False, default=str), now)
            for codigo, payload in rows
        ]
        with self._db.transaction() as cur:
            cur.executemany(
                """
                INSERT INTO discursos (codigo, input)
                VALUES (?, ?)
                ON CONFLICT(codigo) DO UPDATE SET
                    input = excluded.input,
                    updated_at = ?
                """,
                params,
            )

    # ── Set output por etapa ─────────────────────────────────────────────────

    def set_payload(
        self,
        codigo: str,
        stage: DiscursoStage,
        payload: dict[str, Any],
        version: str | None = None,
    ) -> None:
        """Marca una etapa como completada exitosamente para un discurso."""
        self._validate_stage(stage)
        col_payload = f"{stage}_payload"
        col_version = f"{stage}_version"
        col_error = f"{stage}_error"
        payload_str = json.dumps(payload, ensure_ascii=False, default=str)

        with self._db.transaction() as cur:
            cur.execute(
                f"""
                UPDATE discursos SET
                    {col_payload} = ?,
                    {col_version} = ?,
                    {col_error}   = NULL,
                    updated_at    = ?
                WHERE codigo = ?
                """,
                (payload_str, version, datetime.now(timezone.utc), codigo),
            )

    def set_error(
        self,
        codigo: str,
        stage: DiscursoStage,
        error_message: str,
    ) -> None:
        """Marca una etapa como fallida para un discurso."""
        self._validate_stage(stage)
        col_payload = f"{stage}_payload"
        col_version = f"{stage}_version"
        col_error = f"{stage}_error"

        with self._db.transaction() as cur:
            cur.execute(
                f"""
                UPDATE discursos SET
                    {col_payload} = NULL,
                    {col_version} = NULL,
                    {col_error}   = ?,
                    updated_at    = ?
                WHERE codigo = ?
                """,
                (error_message, datetime.now(timezone.utc), codigo),
            )

    # ── Lookup ───────────────────────────────────────────────────────────────

    def get_input(self, codigo: str) -> dict[str, Any] | None:
        row = self._db.execute(
            "SELECT input FROM discursos WHERE codigo = ?",
            (codigo,),
        ).fetchone()
        if row is None:
            return None
        return json.loads(row["input"])

    def get_payload(
        self,
        codigo: str,
        stage: DiscursoStage,
    ) -> dict[str, Any] | None:
        """Devuelve el payload de una etapa, o None si no procesada o falló."""
        self._validate_stage(stage)
        col = f"{stage}_payload"
        row = self._db.execute(
            f"SELECT {col} FROM discursos WHERE codigo = ?",
            (codigo,),
        ).fetchone()
        if row is None or row[col] is None:
            return None
        return json.loads(row[col])

    def list_codigos(self) -> list[str]:
        """Todos los discursos en la DB."""
        return [
            row["codigo"]
            for row in self._db.execute("SELECT codigo FROM discursos").fetchall()
        ]

    def list_pending(self, stage: DiscursoStage) -> list[str]:
        """Discursos donde la etapa está pendiente (payload NULL y error NULL)."""
        self._validate_stage(stage)
        col_payload = f"{stage}_payload"
        col_error = f"{stage}_error"
        rows = self._db.execute(
            f"SELECT codigo FROM discursos "
            f"WHERE {col_payload} IS NULL AND {col_error} IS NULL"
        ).fetchall()
        return [row["codigo"] for row in rows]

    def list_failed(self, stage: DiscursoStage) -> list[str]:
        """Discursos donde la etapa falló (error no-NULL)."""
        self._validate_stage(stage)
        col_error = f"{stage}_error"
        rows = self._db.execute(
            f"SELECT codigo FROM discursos WHERE {col_error} IS NOT NULL"
        ).fetchall()
        return [row["codigo"] for row in rows]

    def clear_errors(self, stage: DiscursoStage) -> int:
        """Limpia errores de una etapa, marcando discursos como pendientes."""
        self._validate_stage(stage)
        col_error = f"{stage}_error"
        with self._db.transaction() as cur:
            cur.execute(
                f"UPDATE discursos SET {col_error} = NULL "
                f"WHERE {col_error} IS NOT NULL"
            )
            return cur.rowcount

    def list_completed(self, stage: DiscursoStage) -> list[str]:
        """Discursos donde la etapa fue completada exitosamente."""
        self._validate_stage(stage)
        col_payload = f"{stage}_payload"
        rows = self._db.execute(
            f"SELECT codigo FROM discursos WHERE {col_payload} IS NOT NULL"
        ).fetchall()
        return [row["codigo"] for row in rows]

    # ── Helpers ──────────────────────────────────────────────────────────────

    @staticmethod
    def _validate_stage(stage: str) -> None:
        """Valida que el nombre de etapa sea correcto."""
        if stage not in _VALID_STAGES:
            raise ValueError(
                f"Stage '{stage}' inválida. Válidas: {_VALID_STAGES}"
            )
