# ══════════════════════════════════════════════════════════════════════════════
#  emoparse.storage.validation
#
#  Repositorio para la tabla `validation_issues`.
# ══════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from emoparse.domain.validators.base import ValidationIssue
from emoparse.storage.db import Database


CREATE_VALIDATION_ISSUES = """
CREATE TABLE IF NOT EXISTS validation_issues (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    validator_id        TEXT NOT NULL,
    severidad           TEXT NOT NULL DEFAULT 'warning',
    mensaje             TEXT NOT NULL,
    codigo              TEXT NOT NULL,
    frase_idx           INTEGER,        -- NULL si es issue de discurso
    emocion_idx         INTEGER,        -- NULL si es issue de discurso
    contexto            TEXT,           -- JSON con valores que activaron la regla
    run_at              TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
)
""".strip()

CREATE_VALIDATION_ISSUES_INDEX = """
CREATE INDEX IF NOT EXISTS idx_validation_issues_codigo
    ON validation_issues(codigo)
""".strip()


class ValidationRepository:
    """Repositorio de validation_issues."""

    def __init__(self, db: Database) -> None:
        self._db = db
        self._ensure_table()

    def _ensure_table(self) -> None:
        """Crea la tabla si no existe."""
        with self._db.transaction() as cur:
            cur.execute(CREATE_VALIDATION_ISSUES)
            cur.execute(CREATE_VALIDATION_ISSUES_INDEX)

    # ── Escritura ────────────────────────────────────────────────────────────

    def save_issues(self, issues: list[ValidationIssue]) -> None:
        """Inserta un lote de issues."""
        now = datetime.now(timezone.utc)
        rows = [
            (
                issue.validator_id,
                issue.severidad,
                issue.mensaje,
                issue.codigo,
                issue.frase_idx,
                issue.emocion_idx,
                json.dumps(issue.contexto, ensure_ascii=False, default=str),
                now,
            )
            for issue in issues
        ]
        with self._db.transaction() as cur:
            cur.executemany(
                """
                INSERT INTO validation_issues (
                    validator_id, severidad, mensaje, codigo,
                    frase_idx, emocion_idx, contexto, run_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                rows,
            )

    def delete_issues_for_codigo(self, codigo: str) -> None:
        """Borra todas las issues de un discurso."""
        with self._db.transaction() as cur:
            cur.execute(
                "DELETE FROM validation_issues WHERE codigo = ?",
                (codigo,),
            )

    def delete_all(self) -> None:
        """Borra todas las issues."""
        with self._db.transaction() as cur:
            cur.execute("DELETE FROM validation_issues")

    # ── Lectura ──────────────────────────────────────────────────────────────

    def list_issues(
        self,
        codigo: str | None = None,
        validator_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """Lista issues con filtros opcionales."""
        conditions: list[str] = []
        params: list[Any] = []

        if codigo is not None:
            conditions.append("codigo = ?")
            params.append(codigo)
        if validator_id is not None:
            conditions.append("validator_id = ?")
            params.append(validator_id)

        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        rows = self._db.execute(
            f"""
            SELECT
                id, validator_id, severidad, mensaje, codigo,
                frase_idx, emocion_idx, contexto, run_at
            FROM validation_issues
            {where}
            ORDER BY codigo, frase_idx, emocion_idx, validator_id
            """,
            tuple(params),
        ).fetchall()

        result: list[dict[str, Any]] = []
        for row in rows:
            contexto_str = row["contexto"]
            try:
                contexto = json.loads(contexto_str) if contexto_str else {}
            except (json.JSONDecodeError, TypeError):
                contexto = {}

            result.append({
                "id": row["id"],
                "validator_id": row["validator_id"],
                "severidad": row["severidad"],
                "mensaje": row["mensaje"],
                "codigo": row["codigo"],
                "frase_idx": row["frase_idx"],
                "emocion_idx": row["emocion_idx"],
                "contexto": contexto,
                "run_at": row["run_at"],
            })

        return result

    def count_by_validator(self) -> dict[str, int]:
        """Cuenta issues agrupadas por validator_id."""
        rows = self._db.execute(
            """
            SELECT validator_id, COUNT(*) as cnt
            FROM validation_issues
            GROUP BY validator_id
            ORDER BY cnt DESC
            """
        ).fetchall()
        return {row["validator_id"]: row["cnt"] for row in rows}

    def count_total(self) -> int:
        """Total de issues en la tabla."""
        row = self._db.execute(
            "SELECT COUNT(*) as cnt FROM validation_issues"
        ).fetchone()
        return row["cnt"] if row else 0
