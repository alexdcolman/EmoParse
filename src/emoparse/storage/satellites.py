"""Persistencia de corpus satélite y vínculos con el corpus origen."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from emoparse.storage.db import Database

_CREATE_SATELLITES = """
CREATE TABLE IF NOT EXISTS satelites (
    satellite_id        TEXT PRIMARY KEY,
    satellite_path      TEXT NOT NULL,
    source_id           TEXT NOT NULL,
    marco               TEXT NOT NULL,
    profundidad         INTEGER NOT NULL,
    max_items           INTEGER,
    created_at          TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
)
""".strip()

_CREATE_CORPUS_LINKS = """
CREATE TABLE IF NOT EXISTS corpus_vinculos (
    origin_post_id      TEXT NOT NULL,
    source_post_id      TEXT NOT NULL,
    target_post_id      TEXT NOT NULL,
    relation            TEXT NOT NULL,
    generation          INTEGER NOT NULL,
    status              TEXT NOT NULL,
    source_location     TEXT NOT NULL,
    target_location     TEXT NOT NULL,
    position            INTEGER NOT NULL,
    created_at          TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (origin_post_id, source_post_id, target_post_id, relation, generation)
)
""".strip()

_CREATE_CORPUS_LINKS_INDEX = """
CREATE INDEX IF NOT EXISTS idx_corpus_vinculos_origin
    ON corpus_vinculos(origin_post_id, generation, position)
""".strip()


@dataclass(frozen=True, slots=True)
class SatelliteRegistration:
    satellite_id: str
    satellite_path: Path
    source_id: str
    marco: str
    profundidad: int
    max_items: int | None


class SatellitesRepository:
    """DDL y operaciones mínimas para 7.1B."""

    def __init__(self, db: Database) -> None:
        self._db = db

    def ensure_origin_table(self) -> None:
        with self._db.transaction() as cur:
            cur.execute(_CREATE_SATELLITES)

    def ensure_satellite_tables(self) -> None:
        with self._db.transaction() as cur:
            cur.execute(_CREATE_CORPUS_LINKS)
            cur.execute(_CREATE_CORPUS_LINKS_INDEX)
        self._ensure_run_marco_column()

    def register(self, value: SatelliteRegistration) -> None:
        """Crea tabla y registro en una única transacción."""
        with self._db.transaction() as cur:
            cur.execute(_CREATE_SATELLITES)
            cur.execute(
                """
                INSERT INTO satelites (
                    satellite_id, satellite_path, source_id, marco,
                    profundidad, max_items
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    value.satellite_id,
                    str(value.satellite_path),
                    value.source_id,
                    value.marco,
                    value.profundidad,
                    value.max_items,
                ),
            )

    def set_marco(self, marco: str) -> None:
        self._ensure_run_marco_column()
        with self._db.transaction() as cur:
            cur.execute("UPDATE runs SET marco = ?", (marco,))

    def replace_links(self, rows: list[dict[str, Any]]) -> int:
        self.ensure_satellite_tables()
        with self._db.transaction() as cur:
            cur.execute("DELETE FROM corpus_vinculos")
            for row in rows:
                cur.execute(
                    """
                    INSERT INTO corpus_vinculos (
                        origin_post_id, source_post_id, target_post_id,
                        relation, generation, status, source_location,
                        target_location, position
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        row["origin_post_id"],
                        row["source_post_id"],
                        row["target_post_id"],
                        row["relation"],
                        int(row["generation"]),
                        row["status"],
                        row["source_location"],
                        row["target_location"],
                        int(row["position"]),
                    ),
                )
        return len(rows)

    def _ensure_run_marco_column(self) -> None:
        if not self._db.table_exists("runs"):
            return
        cols = {row["name"] for row in self._db.execute("PRAGMA table_info(runs)").fetchall()}
        if "marco" in cols:
            return
        with self._db.transaction() as cur:
            cur.execute("ALTER TABLE runs ADD COLUMN marco TEXT")
