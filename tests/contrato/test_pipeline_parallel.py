"""Contratos de paralelismo LLM en stages por discurso."""

from __future__ import annotations

import threading
from types import SimpleNamespace
from unittest.mock import MagicMock

import pandas as pd

from emoparse.pipeline.runner import PipelineRunner
from emoparse.pipeline.stages import SummarizerStage


class _BarrierAgent:
    """Agente mínimo que sólo completa si cuatro llamadas se solapan."""

    def __init__(self) -> None:
        self.barrier = threading.Barrier(4, timeout=1.0)
        self.lock = threading.Lock()
        self.active = 0
        self.max_active = 0

    def run(self, df: pd.DataFrame) -> pd.DataFrame:
        with self.lock:
            self.active += 1
            self.max_active = max(self.max_active, self.active)
        try:
            self.barrier.wait()
            out = df.copy()
            out["resumen_global"] = "ok"
            out["resumen_fragmentos"] = "[]"
            return out
        finally:
            with self.lock:
                self.active -= 1


def test_discurso_stage_parallel_dispatches_multiple_discursos() -> None:
    agent = _BarrierAgent()
    repo = MagicMock()
    repo.list_pending.return_value = ["D1", "D2", "D3", "D4"]
    repo.get_input.side_effect = lambda codigo: {
        "contenido": f"Contenido {codigo}",
    }

    stage = SummarizerStage(agent, repo)
    stage.parallel = 4

    assert stage.run_pending() == 4
    assert agent.max_active == 4
    assert repo.set_payload.call_count == 4
    assert repo.set_error.call_count == 0


def test_runner_assigns_effective_parallel_to_discurso_stage() -> None:
    stage = SummarizerStage(MagicMock(), MagicMock())
    stage._repo.list_pending.return_value = []

    runner = object.__new__(PipelineRunner)
    runner._current_accumulator = None
    runner._build_stage = lambda _stage_name: stage
    runner._payload_selection = SimpleNamespace(scope_for=lambda _stage_name: None)
    runner._validate_contracts = True
    runner._effective_parallel = MagicMock(return_value=4)
    runner._metrics_repo = MagicMock()
    runner._run_id = "parallel-test"
    runner._cfg = SimpleNamespace(
        pipeline=SimpleNamespace(stages={"summarizer": "srv"}),
    )

    assert runner._run_one_stage("summarizer") == 0
    assert stage.parallel == 4
    runner._effective_parallel.assert_called_once_with("summarizer")
