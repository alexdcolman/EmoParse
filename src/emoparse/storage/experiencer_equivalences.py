# ══════════════════════════════════════════════════════════════════════════════
# emoparse.storage.experiencer_equivalences
#
# Repositorio de equivalencias de experienciador (por discurso).
# ══════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal

from emoparse.storage.db import Database


EquivalenceStatus = Literal["pending", "accepted", "rejected", "applied"]
ClaseExperienciador = Literal[
    "enunciador", "enunciatario", "actor", "otro", "literal"
]


class ExperiencerEquivalencesRepository:
    """Repositorio de equivalencias de experienciador (por discurso).

    Una fila = una propuesta de normalización para un experienciador crudo de
    un discurso, más su decisión de triage. El `apply` (en CLI) materializa las
    aceptadas escribiendo `emociones.experienciador_canonico`.
    """

    def __init__(self, db: Database) -> None:
        self._db = db

    # ── Propuestas (escritas por la stage) ────────────────────────────────────

    def list_existing_raw(self, codigo: str) -> set[str]:
        """Experienciadores crudos del discurso que ya tienen propuesta."""
        rows = self._db.execute(
            "SELECT raw_experienciador FROM experiencer_equivalences "
            "WHERE codigo = ?",
            (codigo,),
        ).fetchall()
        return {row["raw_experienciador"] for row in rows}

    def upsert_proposal(
        self,
        codigo: str,
        raw_experienciador: str,
        *,
        canonical_sugerido: str | None,
        clase: ClaseExperienciador,
        confianza: str,
        justificacion: str | None,
        ocurrencias: int,
    ) -> None:
        """Inserta o refresca una propuesta.

        Idempotente y seguro ante re-ejecución: si la fila ya fue revisada
        (accepted/rejected/applied) no se toca; si sigue pending, se refresca
        la sugerencia y el conteo de ocurrencias.
        """
        with self._db.transaction() as cur:
            cur.execute(
                """
                INSERT INTO experiencer_equivalences (
                    codigo, raw_experienciador, canonical_sugerido,
                    clase, confianza, justificacion, ocurrencias
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(codigo, raw_experienciador) DO UPDATE SET
                    canonical_sugerido = excluded.canonical_sugerido,
                    clase              = excluded.clase,
                    confianza          = excluded.confianza,
                    justificacion      = excluded.justificacion,
                    ocurrencias        = excluded.ocurrencias
                WHERE experiencer_equivalences.status = 'pending'
                """,
                (
                    codigo, raw_experienciador, canonical_sugerido,
                    clase, confianza, justificacion, ocurrencias,
                ),
            )

    # ── Lookup ─────────────────────────────────────────────────────────────────

    def find(self, equivalence_id: int) -> dict[str, Any] | None:
        row = self._db.execute(
            "SELECT * FROM experiencer_equivalences WHERE id = ?",
            (equivalence_id,),
        ).fetchone()
        return dict(row) if row else None

    def list_by_status(
        self,
        status: EquivalenceStatus | None = "pending",
        codigo: str | None = None,
    ) -> list[dict[str, Any]]:
        sql = "SELECT * FROM experiencer_equivalences"
        clauses: list[str] = []
        params: list[Any] = []
        if status is not None:
            clauses.append("status = ?")
            params.append(status)
        if codigo is not None:
            clauses.append("codigo = ?")
            params.append(codigo)
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY codigo ASC, ocurrencias DESC, raw_experienciador ASC"
        rows = self._db.execute(sql, tuple(params)).fetchall()
        return [dict(r) for r in rows]

    def list_pending_review(
        self,
        codigo: str | None = None,
    ) -> list[dict[str, Any]]:
        return self.list_by_status("pending", codigo)

    def list_accepted_unapplied(self) -> list[dict[str, Any]]:
        return self.list_by_status("accepted", None)

    def count_by_status(
        self,
        status: EquivalenceStatus = "pending",
        codigo: str | None = None,
    ) -> int:
        sql = "SELECT COUNT(*) AS n FROM experiencer_equivalences WHERE status = ?"
        params: list[Any] = [status]
        if codigo is not None:
            sql += " AND codigo = ?"
            params.append(codigo)
        row = self._db.execute(sql, tuple(params)).fetchone()
        return int(row["n"]) if row else 0

    # ── Triage (decisiones) ────────────────────────────────────────────────────

    def accept(
        self,
        equivalence_id: int,
        *,
        canonical: str | None = None,
        origin: str = "cli",
    ) -> None:
        """Acepta una equivalencia, fijando su `canonical_final`.

        El destino se resuelve, en orden: `canonical` explícito → sugerido →
        el propio crudo si la clase es 'literal'. Si no hay destino posible se
        rechaza con ValueError (la propuesta es ambigua: rechazá o pasá uno).
        Solo se puede decidir sobre filas no aplicadas.
        """
        row = self.find(equivalence_id)
        if row is None:
            raise ValueError(f"Equivalencia {equivalence_id} no existe.")
        if row["status"] == "applied":
            raise ValueError(
                f"Equivalencia {equivalence_id} ya fue aplicada; no se "
                f"re-decide."
            )
        destino = canonical or row["canonical_sugerido"]
        if not destino and row["clase"] == "literal":
            destino = row["raw_experienciador"]
        if not destino:
            raise ValueError(
                f"Equivalencia {equivalence_id} (clase={row['clase']}) no "
                f"tiene canónico sugerido; pasá --canonical o rechazala."
            )
        with self._db.transaction() as cur:
            cur.execute(
                """
                UPDATE experiencer_equivalences SET
                    status          = 'accepted',
                    canonical_final = ?,
                    origin          = ?,
                    reviewed_at     = ?
                WHERE id = ?
                """,
                (destino, origin, datetime.now(timezone.utc), equivalence_id),
            )

    def reject(self, equivalence_id: int, *, origin: str = "cli") -> None:
        """Rechaza una equivalencia (el experienciador queda sin canónico)."""
        row = self.find(equivalence_id)
        if row is None:
            raise ValueError(f"Equivalencia {equivalence_id} no existe.")
        if row["status"] == "applied":
            raise ValueError(
                f"Equivalencia {equivalence_id} ya fue aplicada; no se "
                f"re-decide."
            )
        with self._db.transaction() as cur:
            cur.execute(
                """
                UPDATE experiencer_equivalences SET
                    status          = 'rejected',
                    canonical_final = NULL,
                    origin          = ?,
                    reviewed_at     = ?
                WHERE id = ?
                """,
                (origin, datetime.now(timezone.utc), equivalence_id),
            )

    def reset_to_pending(self, equivalence_id: int) -> None:
        """Deshace una decisión no aplicada, volviéndola a pending."""
        row = self.find(equivalence_id)
        if row is None:
            return
        if row["status"] == "applied":
            raise ValueError(
                f"Equivalencia {equivalence_id} ya aplicada; no se deshace "
                f"desde acá."
            )
        with self._db.transaction() as cur:
            cur.execute(
                """
                UPDATE experiencer_equivalences SET
                    status          = 'pending',
                    canonical_final = NULL,
                    reviewed_at     = NULL
                WHERE id = ?
                """,
                (equivalence_id,),
            )

    def mark_applied(self, equivalence_id: int) -> None:
        """Marca una equivalencia aceptada como aplicada."""
        with self._db.transaction() as cur:
            cur.execute(
                """
                UPDATE experiencer_equivalences SET
                    status     = 'applied',
                    applied_at = ?
                WHERE id = ?
                """,
                (datetime.now(timezone.utc), equivalence_id),
            )
