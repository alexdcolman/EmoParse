"""Contratos de presupuesto acumulado de tokens y pausa controlada."""

from __future__ import annotations

import argparse
from types import SimpleNamespace
from typing import Any

import pytest

from emoparse.cli.commands.run_cmd import _positive_int
from emoparse.core.backend.base import LLMResponse, TokenUsage
from emoparse.core.backend.exceptions import SchemaViolationError
from emoparse.core.cache.backend import CachedBackend
from emoparse.core.cache.repository import CacheRepository
from emoparse.pipeline.runner import PipelineRunner
from emoparse.pipeline.token_budget import BudgetedBackend, TokenBudget, TokenBudgetReached
from emoparse.storage.db import Database
from emoparse.storage.metrics import (
    MetricsRepository,
    StageMetricsAccumulator,
    StageMetricsSnapshot,
)
from emoparse.storage.models import RunContext
from emoparse.storage.runs import RunsRepository
from tests.factories import FakeBackend


def _response(prompt: int = 3, completion: int = 2) -> LLMResponse:
    return LLMResponse(
        parsed=None,
        raw="ok",
        usage=TokenUsage(prompt_tokens=prompt, completion_tokens=completion),
        latency_ms=1.0,
        model_alias="fake",
        cache_hit=False,
        finish_reason="stop",
    )


def test_budget_allows_finishing_crossing_call_then_blocks_next_real_call() -> None:
    raw = FakeBackend(responses=[_response(), _response()])
    budget = TokenBudget(4)
    backend = BudgetedBackend(raw, budget)

    first = backend.generate("system", "uno")

    assert first.raw == "ok"
    assert budget.spent == 5
    assert len(raw.calls) == 1
    with pytest.raises(TokenBudgetReached) as captured:
        backend.generate("system", "dos")
    assert captured.value.spent == 5
    assert captured.value.limit == 4
    assert len(raw.calls) == 1


class _BillableFailureBackend(FakeBackend):
    def generate(self, *_args: Any, **_kwargs: Any) -> LLMResponse:
        err = SchemaViolationError("structured output inválido")
        err.attach_usage(TokenUsage(prompt_tokens=6, completion_tokens=3), latency_ms=5.0)
        raise err


def test_budget_counts_usage_attached_to_billable_backend_error() -> None:
    budget = TokenBudget(20)
    backend = BudgetedBackend(_BillableFailureBackend(), budget)
    with pytest.raises(SchemaViolationError):
        backend.generate("system", "user")
    assert budget.spent == 9


def test_budget_signal_is_control_flow_not_item_error() -> None:
    assert issubclass(TokenBudgetReached, BaseException)
    assert not issubclass(TokenBudgetReached, Exception)


def test_cache_hit_costs_zero_and_can_replay_after_budget_is_exhausted(tmp_path) -> None:
    db = Database(tmp_path / "run.sqlite")
    ctx = RunContext(run_id="budget-cache")
    RunsRepository(db).bootstrap(ctx)
    raw = FakeBackend(responses=[_response(prompt=4, completion=1)])
    budget = TokenBudget(5)
    cached = CachedBackend(BudgetedBackend(raw, budget), CacheRepository(db), ctx)

    first = cached.generate("system", "mismo")
    replay = cached.generate("system", "mismo")

    assert first.cache_hit is False
    assert replay.cache_hit is True
    assert budget.spent == 5
    assert len(raw.calls) == 1
    with pytest.raises(TokenBudgetReached):
        cached.generate("system", "nuevo")
    assert len(raw.calls) == 1


def test_metrics_sum_is_cumulative_across_stage_executions(tmp_path) -> None:
    db = Database(tmp_path / "run.sqlite")
    RunsRepository(db).bootstrap(RunContext(run_id="budget-metrics"))
    repo = MetricsRepository(db)
    repo.insert(
        "budget-metrics",
        "metadata",
        StageMetricsSnapshot(total_prompt_tokens=7, total_completion_tokens=3),
    )
    repo.insert(
        "budget-metrics",
        "metadata",
        StageMetricsSnapshot(total_prompt_tokens=5, total_completion_tokens=2),
    )

    assert repo.total_tokens_for_run("budget-metrics") == 17
    resumed = TokenBudget(20, initial_spent=repo.total_tokens_for_run("budget-metrics"))
    assert resumed.spent == 17
    assert resumed.remaining == 3


def test_runs_repository_distinguishes_budget_pause_from_failure(tmp_path) -> None:
    db = Database(tmp_path / "run.sqlite")
    repo = RunsRepository(db)
    repo.bootstrap(RunContext(run_id="budget-status"))

    repo.mark_budget_paused(spent=101, limit=100)
    row = db.execute("SELECT status, finished_at, notes FROM runs").fetchone()
    assert row is not None
    assert row["status"] == "paused_budget"
    assert row["finished_at"] is None
    assert "[PAUSED_BUDGET] tokens=101 limit=100" in str(row["notes"])

    repo.mark_running_if_paused()
    row = db.execute("SELECT status, finished_at FROM runs").fetchone()
    assert row is not None
    assert row["status"] == "running"
    assert row["finished_at"] is None


class _MetricsSink:
    def __init__(self) -> None:
        self.snapshots: list[StageMetricsSnapshot] = []

    def insert(self, **kwargs: Any) -> None:
        self.snapshots.append(kwargs["snapshot"])


class _Scope:
    @staticmethod
    def scope_for(_stage: str) -> None:
        return None


class _PausingStage:
    def __init__(self) -> None:
        self.metrics = StageMetricsAccumulator()
        self.validate_contracts = True

    def set_selector_scope(self, _scope: object) -> None:
        return None

    def run_pending(self) -> int:
        self.metrics.record_llm_call(
            latency_ms=1.0,
            prompt_tokens=8,
            completion_tokens=2,
            cache_hit=False,
        )
        raise TokenBudgetReached(spent=10, limit=10)


def test_runner_persists_partial_stage_metrics_before_budget_pause(monkeypatch) -> None:
    runner = object.__new__(PipelineRunner)
    sink = _MetricsSink()
    runner._metrics_repo = sink
    runner._run_id = "budget-partial"
    runner._payload_selection = _Scope()
    runner._validate_contracts = True
    runner._cfg = SimpleNamespace(pipeline=SimpleNamespace(stages={"metadata": "fake"}))
    monkeypatch.setattr(runner, "_build_stage", lambda _name: _PausingStage())

    with pytest.raises(TokenBudgetReached):
        runner._run_one_stage("metadata")

    assert len(sink.snapshots) == 1
    assert sink.snapshots[0].total_prompt_tokens == 8
    assert sink.snapshots[0].total_completion_tokens == 2


def test_budget_forces_sequential_llm_calls_when_parallel_requested() -> None:
    runner = object.__new__(PipelineRunner)
    runner._token_budget = TokenBudget(100)
    runner._cfg = SimpleNamespace(pipeline=SimpleNamespace(parallel=4, stages={}))
    runner._record_effective_parallel = lambda _stage, _effective: None

    assert runner._effective_parallel("emotions") == 1


class _RunState:
    def __init__(self) -> None:
        self.running = 0
        self.paused: list[tuple[int, int]] = []
        self.failed: list[str] = []
        self.completed = 0

    def mark_running_if_paused(self) -> None:
        self.running += 1

    def mark_budget_paused(self, *, spent: int, limit: int) -> None:
        self.paused.append((spent, limit))

    def mark_failed(self, reason: str = "") -> None:
        self.failed.append(reason)

    def mark_completed(self) -> None:
        self.completed += 1


class _PreparedSelection:
    @staticmethod
    def prepare() -> None:
        return None


def test_runner_marks_budget_pause_without_marking_run_failed(monkeypatch) -> None:
    runner = object.__new__(PipelineRunner)
    state = _RunState()
    runner._runs_repo = state
    runner._payload_selection = _PreparedSelection()
    runner._enabled_stages = ("metadata",)
    monkeypatch.setattr(runner, "_frases_exist", lambda: True)

    def _pause(_stage: str) -> int:
        raise TokenBudgetReached(spent=12, limit=10)

    monkeypatch.setattr(runner, "_run_one_stage", _pause)

    with pytest.raises(TokenBudgetReached):
        runner.run()

    assert state.running == 1
    assert state.paused == [(12, 10)]
    assert state.failed == []
    assert state.completed == 0


def test_budget_cli_value_must_be_positive() -> None:
    assert _positive_int("25") == 25
    with pytest.raises(argparse.ArgumentTypeError):
        _positive_int("0")
    with pytest.raises(argparse.ArgumentTypeError):
        _positive_int("no")
