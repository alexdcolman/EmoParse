"""Contratos de integración de backends API con runner y métricas."""

from __future__ import annotations

from typing import Any

import pytest

from emoparse.config import RunConfig
from emoparse.core.backend.base import LLMBackend, LLMResponse, TokenUsage
from emoparse.core.backend.exceptions import SchemaViolationError
from emoparse.pipeline.runner import PipelineRunner, _MeteredBackend
from emoparse.storage.metrics import StageMetricsAccumulator, StageMetricsSnapshot


class _UsageErrorBackend(LLMBackend):
    alias = "remote"

    def generate(self, *_args: Any, **_kwargs: Any) -> LLMResponse:
        err = SchemaViolationError("bad output")
        err.attach_usage(TokenUsage(prompt_tokens=9, completion_tokens=4), latency_ms=12.5)
        raise err

    def healthcheck(self) -> bool:
        return True


def test_metered_backend_keeps_billable_usage_from_structured_error() -> None:
    accumulator = StageMetricsAccumulator()
    metered = _MeteredBackend(_UsageErrorBackend(), accumulator)
    with pytest.raises(SchemaViolationError):
        metered.generate("system", "user")
    snap = accumulator.snapshot()
    assert snap.total_prompt_tokens == 9
    assert snap.total_completion_tokens == 4
    assert snap.cache_misses == 1
    assert snap.total_latency_ms == 12.5


def test_cost_estimate_uses_new_tokens() -> None:
    cfg = RunConfig.model_validate(
        {
            "models": {
                "oa": {
                    "backend": "openai",
                    "model_id": "gpt-x",
                    "precio_input": 2.0,
                    "precio_output": 8.0,
                }
            },
            "pipeline": {"stages": {"metadata": "oa"}},
        }
    )
    runner = object.__new__(PipelineRunner)
    runner._cfg = cfg
    snap = StageMetricsSnapshot(total_prompt_tokens=1_000_000, total_completion_tokens=500_000)
    assert runner._estimated_cost_usd("metadata", snap) == pytest.approx(6.0)


def test_remote_backend_can_use_requested_pipeline_parallelism() -> None:
    cfg = RunConfig.model_validate(
        {
            "models": {"oa": {"backend": "openai", "model_id": "gpt-x"}},
            "pipeline": {"parallel": 4, "stages": {"metadata": "oa"}},
        }
    )
    runner = object.__new__(PipelineRunner)
    runner._cfg = cfg
    runner._token_budget = None
    runner._record_effective_parallel = lambda _stage, _effective: None
    assert runner._effective_parallel("metadata") == 4
