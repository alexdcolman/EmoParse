# ══════════════════════════════════════════════════════════════════════════════
#  emoparse.storage.hashtags
#
#  Repositorio de la tabla `hashtags` (caracterización a nivel corpus).
# ══════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

import json
from typing import Any

from emoparse.storage.db import Database


class HashtagsRepository:
    """Repositorio de `hashtags`."""

    def __init__(self, db: Database) -> None:
        self._db = db

    def sync_counts(self, counts: list[tuple[str, int]]) -> int:
        """Upserta los conteos de uso (desde tecno_entidades), sin tocar
        el análisis existente."""
        with self._db.transaction() as cur:
            for valor_norm, n in counts:
                cur.execute(
                    """
                    INSERT INTO hashtags (valor_norm, n_usos)
                    VALUES (?, ?)
                    ON CONFLICT(valor_norm) DO UPDATE SET
                        n_usos = excluded.n_usos,
                        updated_at = CURRENT_TIMESTAMP
                    """,
                    (valor_norm, int(n)),
                )
        return len(counts)

    def list_pending_analisis(self, min_usos: int = 3) -> list[dict[str, Any]]:
        """Hashtags con usos suficientes y sin análisis (ni error)."""
        rows = self._db.execute(
            "SELECT * FROM hashtags WHERE n_usos >= ? "
            "AND analisis_payload IS NULL AND analisis_error IS NULL "
            "ORDER BY n_usos DESC, valor_norm",
            (min_usos,),
        ).fetchall()
        return [dict(r) for r in rows]

    def set_analisis(
        self,
        valor_norm: str,
        payload: dict[str, Any],
        version: str | None = None,
    ) -> None:
        """Registra el análisis semiótico de un hashtag."""
        with self._db.transaction() as cur:
            cur.execute(
                """
                UPDATE hashtags SET
                    funcion          = ?,
                    acoplamiento     = ?,
                    foria_entorno    = ?,
                    justificacion    = ?,
                    analisis_payload = ?,
                    analisis_version = ?,
                    analisis_error   = NULL,
                    updated_at       = CURRENT_TIMESTAMP
                WHERE valor_norm = ?
                """,
                (
                    payload.get("funcion"),
                    payload.get("acoplamiento"),
                    payload.get("foria_entorno"),
                    payload.get("justificacion"),
                    json.dumps(payload, ensure_ascii=False),
                    version,
                    valor_norm,
                ),
            )

    def set_analisis_error(self, valor_norm: str, error: str) -> None:
        """Registra un error de análisis para reintento posterior."""
        with self._db.transaction() as cur:
            cur.execute(
                "UPDATE hashtags SET analisis_error = ?, "
                "updated_at = CURRENT_TIMESTAMP WHERE valor_norm = ?",
                (error[:500], valor_norm),
            )

    def list_analizados(self) -> list[dict[str, Any]]:
        """Hashtags con análisis, los más usados primero."""
        rows = self._db.execute(
            "SELECT * FROM hashtags WHERE analisis_payload IS NOT NULL "
            "ORDER BY n_usos DESC, valor_norm"
        ).fetchall()
        return [dict(r) for r in rows]
