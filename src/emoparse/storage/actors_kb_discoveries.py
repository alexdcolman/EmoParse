# ══════════════════════════════════════════════════════════════════════════════
#  emoparse.storage.actors_kb_discoveries
#
#  Repositorio de las tablas `actors_kb_discoveries` y `actors_kb_decisions`.
# ══════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal

from emoparse.storage.db import Database


#: Tipos de decisión válidos sobre un discovery.
DecisionKind = Literal["promote", "merge", "discard"]
_VALID_DECISIONS: tuple[DecisionKind, ...] = ("promote", "merge", "discard")

#: Estados de aplicación.
DecisionStatus = Literal["pending", "applied", "failed"]


class ActorsKbDiscoveriesRepository:
    """Repositorio para discoveries y decisiones de la KB de actores."""

    def __init__(self, db: Database) -> None:
        self._db = db

    # ── Discoveries: insert / list / mark_reviewed ───────────────────────────

    def insert(
        self,
        codigo: str,
        unit_idx: int,
        actor_mencionado: str,
        confianza: str,
        contexto: str | None = None,
        justificacion: str | None = None,
    ) -> None:
        """Registra un actor nuevo detectado por el agente."""
        with self._db.transaction() as cur:
            cur.execute(
                """
                INSERT INTO actors_kb_discoveries (
                    codigo, unit_idx, actor_mencionado,
                    contexto, confianza, justificacion
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    codigo,
                    unit_idx,
                    actor_mencionado,
                    contexto,
                    confianza,
                    justificacion,
                ),
            )

    def list_pending_review(
        self,
        codigo: str | None = None,
        confianza: str | None = None,
    ) -> list[dict[str, Any]]:
        """Devuelve discoveries no revisados (reviewed=0)."""
        sql = (
            "SELECT id, codigo, unit_idx, actor_mencionado, contexto, "
            "confianza, justificacion, discovered_at "
            "FROM actors_kb_discoveries WHERE reviewed = 0"
        )
        params: list[Any] = []
        if codigo is not None:
            sql += " AND codigo = ?"
            params.append(codigo)
        if confianza is not None:
            sql += " AND confianza = ?"
            params.append(confianza)
        sql += " ORDER BY discovered_at ASC"
        rows = self._db.execute(sql, tuple(params)).fetchall()
        return [dict(row) for row in rows]

    def count_pending_review(self, codigo: str | None = None) -> int:
        """Cuenta discoveries no revisados."""
        sql = "SELECT COUNT(*) AS n FROM actors_kb_discoveries WHERE reviewed = 0"
        params: tuple = ()
        if codigo is not None:
            sql += " AND codigo = ?"
            params = (codigo,)
        row = self._db.execute(sql, params).fetchone()
        return int(row["n"]) if row else 0

    def find_discovery(self, discovery_id: int) -> dict[str, Any] | None:
        """Devuelve un discovery por id, o None si no existe."""
        row = self._db.execute(
            "SELECT id, codigo, unit_idx, actor_mencionado, contexto, "
            "confianza, justificacion, discovered_at, reviewed "
            "FROM actors_kb_discoveries WHERE id = ?",
            (discovery_id,),
        ).fetchone()
        return dict(row) if row else None

    def mark_reviewed(self, discovery_id: int) -> None:
        """Marca un discovery como revisado."""
        with self._db.transaction() as cur:
            cur.execute(
                "UPDATE actors_kb_discoveries SET reviewed = 1 WHERE id = ?",
                (discovery_id,),
            )

    # ── Decisions: upsert / list / mark_applied / mark_failed ────────────────

    def upsert_decision(
        self,
        discovery_id: int,
        decision: DecisionKind,
        *,
        canonical_id: str | None = None,
        display_name: str | None = None,
        tipo: str | None = None,
        rol: str | None = None,
        origin: str = "cli",
    ) -> None:
        """Registra una decisión sobre un discovery.

        Si ya existe una decisión `pending` para el mismo `discovery_id`,
        se sobreescribe. Si la existente está `applied`, se rechaza (no
        re-aplicamos la misma decisión).

        Args:
            discovery_id: ID del discovery sobre el que se decide.
            decision: 'promote' | 'merge' | 'discard'.
            canonical_id: requerido para promote/merge. Para promote es
                el id sugerido (debe ser slug); para merge es el id
                destino (debe existir en la KB).
            display_name: requerido para promote.
            tipo: opcional para promote (default: 'desconocido').
            rol: opcional para promote.
            origin: 'cli' | 'dashboard'.

        Raises:
            ValueError: si decision es inválida, faltan campos requeridos,
                o existe una decisión `applied` previa.
        """
        if decision not in _VALID_DECISIONS:
            raise ValueError(
                f"Decisión inválida: '{decision}'. Válidas: {_VALID_DECISIONS}"
            )
        if decision in ("promote", "merge") and not canonical_id:
            raise ValueError(
                f"Decisión '{decision}' requiere canonical_id."
            )
        if decision == "promote" and not display_name:
            raise ValueError("Decisión 'promote' requiere display_name.")

        existing = self.find_decision(discovery_id)
        if existing is not None and existing["status"] == "applied":
            raise ValueError(
                f"Discovery {discovery_id} ya tiene una decisión aplicada. "
                f"No se sobrescribe."
            )

        with self._db.transaction() as cur:
            cur.execute(
                """
                INSERT INTO actors_kb_decisions (
                    discovery_id, decision, canonical_id,
                    display_name, tipo, rol, status, origin
                ) VALUES (?, ?, ?, ?, ?, ?, 'pending', ?)
                ON CONFLICT(discovery_id) DO UPDATE SET
                    decision      = excluded.decision,
                    canonical_id  = excluded.canonical_id,
                    display_name  = excluded.display_name,
                    tipo          = excluded.tipo,
                    rol           = excluded.rol,
                    status        = 'pending',
                    error_message = NULL,
                    origin        = excluded.origin,
                    applied_at    = NULL
                """,
                (
                    discovery_id, decision, canonical_id,
                    display_name, tipo, rol, origin,
                ),
            )

    def find_decision(self, discovery_id: int) -> dict[str, Any] | None:
        """Devuelve la decisión registrada para un discovery, o None."""
        row = self._db.execute(
            "SELECT discovery_id, decision, canonical_id, display_name, "
            "tipo, rol, status, error_message, origin, created_at, applied_at "
            "FROM actors_kb_decisions WHERE discovery_id = ?",
            (discovery_id,),
        ).fetchone()
        return dict(row) if row else None

    def list_decisions(
        self,
        status: DecisionStatus | None = "pending",
    ) -> list[dict[str, Any]]:
        """Lista decisiones filtradas por estado (default: pending)."""
        sql = (
            "SELECT d.discovery_id, d.decision, d.canonical_id, "
            "d.display_name, d.tipo, d.rol, d.status, d.error_message, "
            "d.origin, d.created_at, d.applied_at, "
            "h.actor_mencionado, h.codigo, h.unit_idx, h.contexto, "
            "h.confianza "
            "FROM actors_kb_decisions d "
            "JOIN actors_kb_discoveries h ON h.id = d.discovery_id"
        )
        params: tuple = ()
        if status is not None:
            sql += " WHERE d.status = ?"
            params = (status,)
        sql += " ORDER BY d.created_at ASC"
        rows = self._db.execute(sql, params).fetchall()
        return [dict(r) for r in rows]

    def count_decisions(self, status: DecisionStatus | None = "pending") -> int:
        """Cuenta decisiones en el estado dado."""
        sql = "SELECT COUNT(*) AS n FROM actors_kb_decisions"
        params: tuple = ()
        if status is not None:
            sql += " WHERE status = ?"
            params = (status,)
        row = self._db.execute(sql, params).fetchone()
        return int(row["n"]) if row else 0

    def mark_decision_applied(self, discovery_id: int) -> None:
        """Marca una decisión como aplicada y el discovery como revisado.

        Se hace en una sola transacción para garantizar consistencia entre
        las dos tablas.
        """
        now = datetime.now(timezone.utc)
        with self._db.transaction() as cur:
            cur.execute(
                "UPDATE actors_kb_decisions SET "
                "status = 'applied', applied_at = ?, error_message = NULL "
                "WHERE discovery_id = ?",
                (now, discovery_id),
            )
            cur.execute(
                "UPDATE actors_kb_discoveries SET reviewed = 1 WHERE id = ?",
                (discovery_id,),
            )

    def mark_decision_failed(
        self,
        discovery_id: int,
        error_message: str,
    ) -> None:
        """Marca una decisión como fallida con el mensaje de error.

        El discovery no se marca como revisado: el usuario debe corregir
        y reintentar.
        """
        with self._db.transaction() as cur:
            cur.execute(
                "UPDATE actors_kb_decisions SET "
                "status = 'failed', error_message = ? "
                "WHERE discovery_id = ?",
                (error_message, discovery_id),
            )

    def delete_decision(self, discovery_id: int) -> None:
        """Borra una decisión (typically usado para deshacer triage)."""
        with self._db.transaction() as cur:
            cur.execute(
                "DELETE FROM actors_kb_decisions WHERE discovery_id = ?",
                (discovery_id,),
            )
