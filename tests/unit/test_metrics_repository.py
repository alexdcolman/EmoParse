# ══════════════════════════════════════════════════════════════════════════════
#  tests.unit.test_metrics_repository
#
#  Tests del MetricsRepository: round-trip básico de snapshots.
# ══════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

from pathlib import Path

import pytest

from emoparse.storage.db import Database
from emoparse.storage.metrics import (
    MetricsRepository,
    StageMetricsAccumulator,
    StageMetricsSnapshot,
    _compute_percentiles,
)
from emoparse.storage.models import RunContext, Versions
from emoparse.storage.runs import RunsRepository


@pytest.fixture
def db(tmp_path: Path) -> Database:
    """DB inicializada con todas las tablas."""
    db = Database(tmp_path / "test.sqlite")
    runs_repo = RunsRepository(db)
    runs_repo.bootstrap(RunContext(run_id="test-run", versions=Versions()))
    return db


class TestStageMetricsAccumulator:

    def test_record_llm_call_hit_does_not_count_tokens(self) -> None:
        """Un cache hit suma a hits + latency, NO a tokens."""
        acc = StageMetricsAccumulator()
        acc.record_llm_call(
            latency_ms=100.0,
            prompt_tokens=50,
            completion_tokens=30,
            cache_hit=True,
        )
        snap = acc.snapshot()
        assert snap.cache_hits == 1
        assert snap.cache_misses == 0
        assert snap.total_prompt_tokens == 0
        assert snap.total_completion_tokens == 0
        assert snap.total_latency_ms == 100.0

    def test_record_llm_call_miss_counts_tokens(self) -> None:
        acc = StageMetricsAccumulator()
        acc.record_llm_call(
            latency_ms=200.0,
            prompt_tokens=50,
            completion_tokens=30,
            cache_hit=False,
        )
        snap = acc.snapshot()
        assert snap.cache_hits == 0
        assert snap.cache_misses == 1
        assert snap.total_prompt_tokens == 50
        assert snap.total_completion_tokens == 30

    def test_items_counters(self) -> None:
        acc = StageMetricsAccumulator()
        for _ in range(3):
            acc.record_item_ok()
        for _ in range(2):
            acc.record_item_failed()
        snap = acc.snapshot()
        assert snap.n_items_ok == 3
        assert snap.n_items_failed == 2

    def test_percentiles_with_real_data(self) -> None:
        """Las latencias acumuladas se reflejan en p50/p99 del snapshot."""
        acc = StageMetricsAccumulator()
        # 100 valores de 1 a 100 ms.
        for ms in range(1, 101):
            acc.record_llm_call(
                latency_ms=float(ms),
                prompt_tokens=10,
                completion_tokens=5,
                cache_hit=False,
            )
        snap = acc.snapshot()
        assert snap.cache_misses == 100
        # p50 cae cerca de 50 (mediana de 1..100).
        assert snap.p50_latency_ms is not None
        assert 45 <= snap.p50_latency_ms <= 55
        # p99 cae cerca del extremo (>=95).
        assert snap.p99_latency_ms is not None
        assert snap.p99_latency_ms >= 95

    def test_empty_snapshot(self) -> None:
        snap = StageMetricsAccumulator().snapshot()
        assert snap.n_items_ok == 0
        assert snap.total_latency_ms == 0.0
        assert snap.p50_latency_ms is None
        assert snap.p99_latency_ms is None


class TestComputePercentiles:

    def test_empty(self) -> None:
        assert _compute_percentiles([]) == (None, None)

    def test_single_value(self) -> None:
        p50, p99 = _compute_percentiles([42.0])
        assert p50 == 42.0
        assert p99 == 42.0

    def test_two_values(self) -> None:
        # Con n<100 se usan cortes nominales: p50 = sorted[n//2], p99 = max.
        p50, p99 = _compute_percentiles([10.0, 20.0])
        assert p99 == 20.0


class TestRoundTrip:

    def test_insert_and_list(self, db: Database) -> None:
        repo = MetricsRepository(db)
        snap = StageMetricsSnapshot(
            n_items_ok=5,
            n_items_failed=1,
            total_latency_ms=1234.5,
            p50_latency_ms=200.0,
            p99_latency_ms=500.0,
            total_prompt_tokens=1000,
            total_completion_tokens=200,
            cache_hits=3,
            cache_misses=3,
        )
        repo.insert("test-run", "summarizer", snap)

        rows = repo.list_for_run("test-run")
        assert len(rows) == 1
        r = rows[0]
        assert r["stage_name"] == "summarizer"
        assert r["n_items_ok"] == 5
        assert r["n_items_failed"] == 1
        assert r["total_latency_ms"] == pytest.approx(1234.5)
        assert r["p50_latency_ms"] == pytest.approx(200.0)
        assert r["p99_latency_ms"] == pytest.approx(500.0)
        assert r["total_prompt_tokens"] == 1000
        assert r["total_completion_tokens"] == 200
        assert r["cache_hits"] == 3
        assert r["cache_misses"] == 3

    def test_list_for_other_run_returns_empty(self, db: Database) -> None:
        repo = MetricsRepository(db)
        repo.insert(
            "test-run", "summarizer",
            StageMetricsSnapshot(n_items_ok=1),
        )
        assert repo.list_for_run("other-run") == []

    def test_multiple_stages(self, db: Database) -> None:
        repo = MetricsRepository(db)
        for stage in ("summarizer", "metadata", "actors"):
            repo.insert("test-run", stage, StageMetricsSnapshot(n_items_ok=1))
        rows = repo.list_for_run("test-run")
        assert {r["stage_name"] for r in rows} == {"summarizer", "metadata", "actors"}

    def test_latest_per_stage_dedupes(self, db: Database) -> None:
        """Si una stage tiene múltiples filas, list_latest_per_stage devuelve solo la última."""
        repo = MetricsRepository(db)
        # Dos inserts para la misma stage.
        repo.insert("test-run", "summarizer", StageMetricsSnapshot(n_items_ok=5))
        import time
        time.sleep(1.05)
        repo.insert("test-run", "summarizer", StageMetricsSnapshot(n_items_ok=10))

        rows = repo.list_latest_per_stage("test-run")
        assert len(rows) == 1
        assert rows[0]["n_items_ok"] == 10

    def test_p50_p99_can_be_null(self, db: Database) -> None:
        """Snapshot sin llamadas LLM tiene p50/p99 NULL."""
        repo = MetricsRepository(db)
        repo.insert(
            "test-run",
            "explode_emociones",
            StageMetricsSnapshot(n_items_ok=10),
        )
        rows = repo.list_for_run("test-run")
        assert rows[0]["p50_latency_ms"] is None
        assert rows[0]["p99_latency_ms"] is None
