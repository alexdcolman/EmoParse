# ══════════════════════════════════════════════════════════════════════════════
#  emoparse.storage.metrics
#
#  Repositorio de la tabla `run_metrics`: telemetría por stage del run.
# ══════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from emoparse.storage.db import Database


@dataclass
class StageMetricsSnapshot:
    """Snapshot inmutable de métricas de una stage."""

    n_items_ok: int = 0
    n_items_failed: int = 0
    total_latency_ms: float = 0.0
    p50_latency_ms: float | None = None
    p99_latency_ms: float | None = None
    total_prompt_tokens: int = 0
    total_completion_tokens: int = 0
    cache_hits: int = 0
    cache_misses: int = 0


@dataclass
class StageMetricsAccumulator:
    """Acumulador mutable de métricas durante la ejecución de una stage."""

    n_items_ok: int = 0
    n_items_failed: int = 0
    total_prompt_tokens: int = 0
    total_completion_tokens: int = 0
    cache_hits: int = 0
    cache_misses: int = 0
    _latencies: list[float] = field(default_factory=list)

    # ── API para _MeteredBackend ─────────────────────────────────────────────

    def record_llm_call(
        self,
        latency_ms: float,
        prompt_tokens: int,
        completion_tokens: int,
        cache_hit: bool,
    ) -> None:
        """Registra una llamada al backend."""
        self._latencies.append(latency_ms)
        if cache_hit:
            self.cache_hits += 1
        else:
            self.cache_misses += 1
            self.total_prompt_tokens += prompt_tokens
            self.total_completion_tokens += completion_tokens

    # ── API para el Stage ────────────────────────────────────────────────────

    def record_item_ok(self) -> None:
        self.n_items_ok += 1

    def record_item_failed(self) -> None:
        self.n_items_failed += 1

    # ── Snapshot ─────────────────────────────────────────────────────────────

    def snapshot(self) -> StageMetricsSnapshot:
        """Computa percentiles y devuelve el snapshot inmutable."""
        total_latency = sum(self._latencies)
        p50, p99 = _compute_percentiles(self._latencies)
        return StageMetricsSnapshot(
            n_items_ok=self.n_items_ok,
            n_items_failed=self.n_items_failed,
            total_latency_ms=total_latency,
            p50_latency_ms=p50,
            p99_latency_ms=p99,
            total_prompt_tokens=self.total_prompt_tokens,
            total_completion_tokens=self.total_completion_tokens,
            cache_hits=self.cache_hits,
            cache_misses=self.cache_misses,
        )


def _compute_percentiles(values: list[float]) -> tuple[float | None, float | None]:
    """Computa (p50, p99) de una lista de floats."""
    n = len(values)
    if n == 0:
        return None, None
    if n == 1:
        v = values[0]
        return v, v
    sorted_v = sorted(values)
    if n < 100:
        p50 = sorted_v[n // 2]
        p99 = sorted_v[-1]
        return p50, p99
    quantiles = statistics.quantiles(sorted_v, n=100, method="inclusive")
    return quantiles[49], quantiles[98]


# ══════════════════════════════════════════════════════════════════════════════
#  Repositorio
# ══════════════════════════════════════════════════════════════════════════════

class MetricsRepository:
    """Repositorio de métricas de run."""

    def __init__(self, db: Database) -> None:
        self._db = db

    def insert(
        self,
        run_id: str,
        stage_name: str,
        snapshot: StageMetricsSnapshot,
    ) -> None:
        """Persiste un snapshot de métricas."""
        with self._db.transaction() as cur:
            cur.execute(
                """
                INSERT INTO run_metrics (
                    run_id, stage_name,
                    n_items_ok, n_items_failed,
                    total_latency_ms, p50_latency_ms, p99_latency_ms,
                    total_prompt_tokens, total_completion_tokens,
                    cache_hits, cache_misses,
                    recorded_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    stage_name,
                    snapshot.n_items_ok,
                    snapshot.n_items_failed,
                    snapshot.total_latency_ms,
                    snapshot.p50_latency_ms,
                    snapshot.p99_latency_ms,
                    snapshot.total_prompt_tokens,
                    snapshot.total_completion_tokens,
                    snapshot.cache_hits,
                    snapshot.cache_misses,
                    datetime.now(timezone.utc),
                ),
            )

    def list_for_run(self, run_id: str) -> list[dict[str, Any]]:
        """Todas las métricas de un run, ordenadas por recorded_at."""
        rows = self._db.execute(
            """
            SELECT
                run_id, stage_name,
                n_items_ok, n_items_failed,
                total_latency_ms, p50_latency_ms, p99_latency_ms,
                total_prompt_tokens, total_completion_tokens,
                cache_hits, cache_misses,
                recorded_at
            FROM run_metrics
            WHERE run_id = ?
            ORDER BY recorded_at ASC
            """,
            (run_id,),
        ).fetchall()
        return [dict(row) for row in rows]

    def list_latest_per_stage(self, run_id: str) -> list[dict[str, Any]]:
        """Última métrica de cada stage para un run."""
        rows = self._db.execute(
            """
            SELECT m.*
            FROM run_metrics m
            INNER JOIN (
                SELECT stage_name, MAX(recorded_at) AS max_at
                FROM run_metrics
                WHERE run_id = ?
                GROUP BY stage_name
            ) latest
                ON m.stage_name = latest.stage_name
                AND m.recorded_at = latest.max_at
            WHERE m.run_id = ?
            ORDER BY m.recorded_at ASC
            """,
            (run_id, run_id),
        ).fetchall()
        return [dict(row) for row in rows]
