# ══════════════════════════════════════════════════════════════════════════════
#  emoparse.storage.hilos
#
#  Repositorio de la tabla `hilos` (conversaciones del corpus de posts).
# ══════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

import json
from typing import Any

from emoparse.storage.db import Database


class HilosRepository:
    """Repositorio de `hilos`."""

    def __init__(self, db: Database) -> None:
        self._db = db

    def upsert_hilos(self, rows: list[dict[str, Any]]) -> int:
        """Upsertea hilos por `conversacion_id`."""
        n = 0
        with self._db.transaction() as cur:
            for r in rows:
                participantes = r.get("participantes")
                if isinstance(participantes, list):
                    participantes = json.dumps(participantes, ensure_ascii=False)
                cur.execute(
                    """
                    INSERT INTO hilos (
                        conversacion_id, post_raiz, n_posts, profundidad_max,
                        participantes, fecha_inicio, fecha_fin
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(conversacion_id) DO UPDATE SET
                        post_raiz       = excluded.post_raiz,
                        n_posts         = excluded.n_posts,
                        profundidad_max = excluded.profundidad_max,
                        participantes   = excluded.participantes,
                        fecha_inicio    = excluded.fecha_inicio,
                        fecha_fin       = excluded.fecha_fin,
                        updated_at      = CURRENT_TIMESTAMP
                    """,
                    (
                        r["conversacion_id"], r["post_raiz"],
                        int(r.get("n_posts", 1)),
                        int(r.get("profundidad_max", 0)),
                        participantes, r.get("fecha_inicio"), r.get("fecha_fin"),
                    ),
                )
                n += 1
        return n

    def get_hilo(self, conversacion_id: str) -> dict[str, Any] | None:
        """Devuelve un hilo por conversación, con participantes parseados."""
        row = self._db.execute(
            "SELECT * FROM hilos WHERE conversacion_id = ?", (conversacion_id,)
        ).fetchone()
        if row is None:
            return None
        d = dict(row)
        raw = d.get("participantes")
        if isinstance(raw, str) and raw:
            try:
                d["participantes"] = json.loads(raw)
            except json.JSONDecodeError:
                pass
        return d

    def list_hilos(self, min_posts: int = 1) -> list[dict[str, Any]]:
        """Hilos del corpus, los más largos primero."""
        rows = self._db.execute(
            "SELECT * FROM hilos WHERE n_posts >= ? "
            "ORDER BY n_posts DESC, conversacion_id",
            (min_posts,),
        ).fetchall()
        return [dict(r) for r in rows]
