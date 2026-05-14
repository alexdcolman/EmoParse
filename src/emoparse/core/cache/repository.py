# ══════════════════════════════════════════════════════════════════════════════
#  emoparse.core.cache.repository
#
#  Repositorio del cache LLM: lectura/escritura sobre tabla llm_cache.
#  Ubicado en core/cache porque la lógica de hit/miss es propia del cache.
# ══════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from loguru import logger

from emoparse.core.cache.keys import CacheKey
from emoparse.storage.db import Database


@dataclass(frozen=True, slots=True)
class CachedEntry:
    """Una entrada del cache. Resultado de un `get()`."""
    raw: str
    finish_reason: str | None
    prompt_tokens: int
    completion_tokens: int
    latency_ms: float | None
    created_at: datetime
    hit_count: int


class CacheRepository:
    """Acceso al cache LLM; provee lectura/escritura, no decide cachear."""

    def __init__(self, db: Database) -> None:
        self._db = db
        # Contadores in-memory para stats(); reinician en cada proceso.
        self._session_hits = 0
        self._session_misses = 0

    # ── Lectura ──────────────────────────────────────────────────────────────

    def get(self, key: CacheKey) -> CachedEntry | None:
        """Busca una entrada por clave. Devuelve None si no existe.

        hit_count se incrementa solo con record_hit().
        """
        row = self._db.execute(
            """
            SELECT raw, finish_reason, prompt_tokens, completion_tokens,
                   latency_ms, created_at, hit_count
            FROM llm_cache
            WHERE cache_key = ?
            """,
            (key.digest,),
        ).fetchone()

        if row is None:
            self._session_misses += 1
            return None

        self._session_hits += 1
        return CachedEntry(
            raw=row["raw"],
            finish_reason=row["finish_reason"],
            prompt_tokens=row["prompt_tokens"] or 0,
            completion_tokens=row["completion_tokens"] or 0,
            latency_ms=row["latency_ms"],   # puede ser None en entradas viejas
            created_at=row["created_at"],
            hit_count=row["hit_count"] or 0,
        )

    def record_hit(self, digest: str) -> None:
        """Marca un hit: incrementa hit_count y actualiza last_hit_at."""
        with self._db.transaction() as cur:
            cur.execute(
                """
                UPDATE llm_cache SET
                    hit_count   = hit_count + 1,
                    last_hit_at = ?
                WHERE cache_key = ?
                """,
                (datetime.now(timezone.utc), digest),
            )

    # ── Escritura ────────────────────────────────────────────────────────────

    def set(
        self,
        key: CacheKey,
        *,
        raw: str,
        finish_reason: str | None = None,
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
        latency_ms: float | None = None,
    ) -> None:
        """Guarda una entrada en el cache.

        No sobrescribe si la clave ya existe (INSERT OR IGNORE).
        """
        with self._db.transaction() as cur:
            cur.execute(
                """
                INSERT OR IGNORE INTO llm_cache (
                    cache_key,
                    model_alias, schema_qualname,
                    knowledge_version, prompt_version,
                    ontology_version, schema_version,
                    raw, finish_reason,
                    prompt_tokens, completion_tokens,
                    latency_ms,
                    created_at, hit_count
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0)
                """,
                (
                    key.digest,
                    key.model_alias,
                    key.schema_qualname,
                    key.knowledge_version,
                    key.prompt_version,
                    key.ontology_version,
                    key.schema_version,
                    raw,
                    finish_reason,
                    prompt_tokens,
                    completion_tokens,
                    latency_ms,
                    datetime.now(timezone.utc),
                ),
            )

    # ── Stats ────────────────────────────────────────────────────────────────

    def stats(self) -> dict[str, Any]:
        """Estadísticas del cache: sesión actual y agregadas de la tabla."""
        total = self._db.execute(
            "SELECT COUNT(*) AS n FROM llm_cache"
        ).fetchone()["n"]

        by_model_rows = self._db.execute(
            """
            SELECT model_alias, COUNT(*) AS n, SUM(hit_count) AS hits
            FROM llm_cache
            GROUP BY model_alias
            """
        ).fetchall()
        by_model = {
            r["model_alias"]: {"entries": r["n"], "lifetime_hits": r["hits"] or 0}
            for r in by_model_rows
        }

        total_lookups = self._session_hits + self._session_misses
        hit_rate = (
            self._session_hits / total_lookups if total_lookups > 0 else 0.0
        )

        return {
            "session_hits": self._session_hits,
            "session_misses": self._session_misses,
            "session_hit_rate": round(hit_rate, 3),
            "total_entries": total,
            "by_model": by_model,
        }

    # ── Cleanup ──────────────────────────────────────────────────────────────

    def purge_by_model(self, model_alias: str) -> int:
        """Borra todas las entradas de un modelo. Retorna cantidad borrada."""
        with self._db.transaction() as cur:
            cur.execute(
                "DELETE FROM llm_cache WHERE model_alias = ?",
                (model_alias,),
            )
            n = cur.rowcount
        logger.info(f"[CacheRepo] Purgadas {n} entradas del modelo '{model_alias}'")
        return n

    def purge_by_versions(
        self,
        *,
        knowledge: str | None = None,
        prompt: str | None = None,
        ontology: str | None = None,
        schema: str | None = None,
    ) -> int:
        """Borra entradas que coincidan con una combinación de versions.

        Pasar None en un campo significa "no filtrar por ese campo".
        Pasar todas None: lanza ValueError (sería purge_all).
        """
        conditions: list[str] = []
        params: list[Any] = []
        for col, val in [
            ("knowledge_version", knowledge),
            ("prompt_version", prompt),
            ("ontology_version", ontology),
            ("schema_version", schema),
        ]:
            if val is not None:
                conditions.append(f"{col} = ?")
                params.append(val)

        if not conditions:
            raise ValueError(
                "purge_by_versions requiere al menos un filtro. "
                "Para borrar todo, usá purge_all()."
            )

        sql = f"DELETE FROM llm_cache WHERE {' AND '.join(conditions)}"
        with self._db.transaction() as cur:
            cur.execute(sql, tuple(params))
            n = cur.rowcount
        logger.info(f"[CacheRepo] Purgadas {n} entradas con filtros: {conditions}")
        return n

    def purge_all(self) -> int:
        """Vacía completamente la tabla. Devuelve cuántas filas borró."""
        with self._db.transaction() as cur:
            cur.execute("DELETE FROM llm_cache")
            n = cur.rowcount
        logger.info(f"[CacheRepo] Cache purgado completo ({n} entradas)")
        return n
