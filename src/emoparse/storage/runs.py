# ══════════════════════════════════════════════════════════════════════════════
#  emoparse.storage.runs
#
#  Repositorio de la tabla `runs` + bootstrap del esquema completo.
# ══════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from emoparse.storage.db import Database
from emoparse.storage.models import RunContext, Versions
from emoparse.storage.schema import ALL_TABLES_DDL


class RunsRepository:
    """Repositorio de la tabla runs e inicialización del esquema."""

    def __init__(self, db: Database) -> None:
        self._db = db

    # ── Bootstrap ────────────────────────────────────────────────────────────

    def bootstrap(self, ctx: RunContext) -> None:
        """Inicializa la DB para un run nuevo."""
        with self._db.transaction() as cur:
            for ddl in ALL_TABLES_DDL:
                cur.execute(ddl)

        self._apply_additive_migrations()

        existing = self._db.execute("SELECT run_id FROM runs").fetchone()
        if existing is not None:
            existing_id = existing["run_id"]
            if existing_id != ctx.run_id:
                raise RuntimeError(
                    f"La DB ya contiene el run '{existing_id}' y se intentó "
                    f"abrir como '{ctx.run_id}'. Una DB = un run. "
                    f"Usá un archivo distinto."
                )
            return

        with self._db.transaction() as cur:
            cur.execute(
                """
                INSERT INTO runs (
                    run_id, started_at, status,
                    knowledge_version, prompt_version,
                    ontology_version, schema_version,
                    config, notes
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    ctx.run_id,
                    ctx.started_at,
                    "running",
                    ctx.versions.knowledge,
                    ctx.versions.prompt,
                    ctx.versions.ontology,
                    ctx.versions.schema,
                    json.dumps(ctx.config, ensure_ascii=False, default=str),
                    ctx.notes,
                ),
            )

    # ── Migraciones additive ─────────────────────────────────────────────────

    def _apply_additive_migrations(self) -> None:
        """Agrega columnas nuevas a tablas preexistentes.

        Convención de versionado: cuando se agrega una columna a un
        schema, también se registra acá. Las DBs nuevas obtienen la
        columna vía CREATE TABLE; las existentes, vía ALTER TABLE.
        """
        self._add_column_if_missing(
            table="frases",
            column="emociones_pass2_payload",
            type_def="TEXT",
        )
        self._add_column_if_missing(
            table="frases",
            column="emociones_pass2_version",
            type_def="TEXT",
        )
        self._add_column_if_missing(
            table="frases",
            column="emociones_pass2_error",
            type_def="TEXT",
        )
        self._add_column_if_missing(
            table="llm_cache",
            column="latency_ms",
            type_def="REAL",
        )
        self._add_column_if_missing(
            table="emociones",
            column="tipo_emocion_canonico",
            type_def="TEXT",
        )
        self._add_column_if_missing(
            table="emociones",
            column="normalize_emotions_version",
            type_def="TEXT",
        )
        self._add_column_if_missing(
            table="emociones",
            column="experienciador_canonico",
            type_def="TEXT",
        )
        self._add_column_if_missing(
            table="emociones",
            column="normalize_experiencers_version",
            type_def="TEXT",
        )
        self._add_column_if_missing(
            table="emociones",
            column="tipo_configuracion",
            type_def="TEXT",
        )
        self._add_column_if_missing(
            table="frases",
            column="actores_canonicos_payload",
            type_def="TEXT",
        )
        self._add_column_if_missing(
            table="frases",
            column="actores_canonicos_version",
            type_def="TEXT",
        )
        self._add_column_if_missing(
            table="frases",
            column="actores_canonicos_error",
            type_def="TEXT",
        )
        self._add_column_if_missing(
            table="emociones",
            column="actantes_payload",
            type_def="TEXT",
        )
        self._add_column_if_missing(
            table="emociones",
            column="actantes_version",
            type_def="TEXT",
        )
        self._add_column_if_missing(
            table="emociones",
            column="actantes_error",
            type_def="TEXT",
        )

    def _add_column_if_missing(
        self,
        table: str,
        column: str,
        type_def: str,
    ) -> None:
        """Agrega una columna si no existe."""
        existing = {
            row["name"]
            for row in self._db.execute(
                f"PRAGMA table_info({table})"
            ).fetchall()
        }
        if column in existing:
            return
        with self._db.transaction() as cur:
            cur.execute(f"ALTER TABLE {table} ADD COLUMN {column} {type_def}")

    # ── Lookup ───────────────────────────────────────────────────────────────

    def get_run(self) -> RunContext | None:
        """Devuelve el RunContext de la DB, o None si no se inicializó."""
        if not self._db.table_exists("runs"):
            return None
        row = self._db.execute(
            "SELECT * FROM runs LIMIT 1"
        ).fetchone()
        if row is None:
            return None
        config_str = row["config"]
        config: dict[str, Any] = json.loads(config_str) if config_str else {}
        return RunContext(
            run_id=row["run_id"],
            versions=Versions(
                knowledge=row["knowledge_version"],
                prompt=row["prompt_version"],
                ontology=row["ontology_version"],
                schema=row["schema_version"],
            ),
            started_at=row["started_at"],
            config=config,
            notes=row["notes"] or "",
        )

    # ── Status updates ───────────────────────────────────────────────────────

    def mark_completed(self) -> None:
        """Marca el run como completado exitosamente."""
        with self._db.transaction() as cur:
            cur.execute(
                """
                UPDATE runs SET
                    status = 'completed',
                    finished_at = ?
                """,
                (datetime.now(timezone.utc),),
            )

    def mark_failed(self, reason: str = "") -> None:
        """Marca el run como fallido y concatena reason a notes."""
        with self._db.transaction() as cur:
            cur.execute(
                """
                UPDATE runs SET
                    status = 'failed',
                    finished_at = ?,
                    notes = COALESCE(notes, '') || ? || ?
                """,
                (
                    datetime.now(timezone.utc),
                    "\n\n[FAILED] " if reason else "",
                    reason,
                ),
            )
