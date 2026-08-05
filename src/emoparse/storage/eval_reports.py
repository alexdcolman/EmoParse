# ══════════════════════════════════════════════════════════════════════════════
#  emoparse.storage.eval_reports
#
#  Persistencia de reportes estructurados de evaluación por run.
# ══════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

import json
from typing import Any

from emoparse.storage.db import Database


class EvalReportsRepository:
    """Repositorio de la tabla ``eval_reports``."""

    def __init__(self, db: Database) -> None:
        self._db = db

    def insert(
        self,
        *,
        run_id: str,
        golden_version: str,
        payload: dict[str, Any],
    ) -> int:
        """Persiste un reporte y devuelve su identificador."""
        encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
        with self._db.transaction() as cursor:
            cursor.execute(
                """
                INSERT INTO eval_reports (run_id, golden_version, payload)
                VALUES (?, ?, ?)
                """,
                (run_id, golden_version, encoded),
            )
            report_id = cursor.lastrowid
        if report_id is None:
            raise RuntimeError("SQLite no devolvió report_id para el reporte persistido.")
        return int(report_id)

    def list_for_run(self, run_id: str) -> list[dict[str, Any]]:
        """Lista los reportes del run, del más reciente al más antiguo."""
        rows = self._db.execute(
            """
            SELECT report_id, run_id, golden_version, recorded_at, payload
            FROM eval_reports
            WHERE run_id = ?
            ORDER BY recorded_at DESC, report_id DESC
            """,
            (run_id,),
        ).fetchall()
        output: list[dict[str, Any]] = []
        for row in rows:
            item = dict(row)
            try:
                payload = json.loads(str(item["payload"]))
            except (json.JSONDecodeError, TypeError):
                payload = {}
            item["payload"] = payload if isinstance(payload, dict) else {}
            output.append(item)
        return output

    def latest_for_run(self, run_id: str) -> dict[str, Any] | None:
        """Devuelve el último reporte persistido para el run."""
        reports = self.list_for_run(run_id)
        return reports[0] if reports else None
