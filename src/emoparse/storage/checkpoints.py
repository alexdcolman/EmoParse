# ══════════════════════════════════════════════════════════════════════════════
#  emoparse.storage.checkpoints
#
#  Checkpoints persistentes para stages sin payload propio.
# ══════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

from datetime import UTC, datetime

from emoparse.storage.db import Database


class StageCheckpointsRepository:
    """Estado de completitud idempotente por stage y unidad de alcance.

    Se usa sólo cuando una stage no tiene una columna de payload/error cuya
    presencia permita decidir si queda trabajo pendiente. El fingerprint
    representa exactamente las entradas que gobiernan la materialización.
    """

    def __init__(self, db: Database) -> None:
        self._db = db

    def is_current(
        self,
        stage_name: str,
        scope_key: str,
        input_fingerprint: str,
        *,
        stage_version: str | None = None,
    ) -> bool:
        """True si existe un checkpoint para estas entradas y versión."""
        row = self._db.execute(
            "SELECT input_fingerprint, stage_version FROM stage_checkpoints "
            "WHERE stage_name = ? AND scope_key = ?",
            (stage_name, scope_key),
        ).fetchone()
        if row is None or row["input_fingerprint"] != input_fingerprint:
            return False
        if stage_version is None:
            return True
        return (row["stage_version"] or "") == stage_version

    def mark_completed(
        self,
        stage_name: str,
        scope_key: str,
        input_fingerprint: str,
        *,
        stage_version: str | None = None,
    ) -> None:
        """Registra una ejecución completada para las entradas indicadas."""
        with self._db.transaction() as cur:
            cur.execute(
                """
                INSERT INTO stage_checkpoints (
                    stage_name, scope_key, input_fingerprint, stage_version, completed_at
                ) VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(stage_name, scope_key) DO UPDATE SET
                    input_fingerprint = excluded.input_fingerprint,
                    stage_version = excluded.stage_version,
                    completed_at = excluded.completed_at
                """,
                (
                    stage_name,
                    scope_key,
                    input_fingerprint,
                    stage_version,
                    datetime.now(UTC),
                ),
            )

    def invalidate(self, stage_name: str, scope_key: str) -> None:
        """Elimina el checkpoint de una unidad de alcance."""
        with self._db.transaction() as cur:
            cur.execute(
                "DELETE FROM stage_checkpoints WHERE stage_name = ? AND scope_key = ?",
                (stage_name, scope_key),
            )
