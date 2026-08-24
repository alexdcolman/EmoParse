"""Contratos del launcher y del diagnóstico de llama-server."""

from __future__ import annotations

import argparse
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from emoparse.config import RunConfig
from emoparse.core.backend.exceptions import BackendConfigError, BackendUnavailableError
from emoparse.core.backend.llama_server import LlamaServerBackend
from emoparse.core.backend.server_launch import build_llama_server_launch_profile


def _config(*, cpu_moe: bool = False, n_cpu_moe: int | None = None) -> RunConfig:
    return RunConfig.model_validate(
        {
            "models": {
                "srv": {
                    "backend": "llama_server",
                    "path": "models/model.gguf",
                    "base_url": "http://127.0.0.1:9090",
                    "context_length": 4096,
                    "n_gpu_layers": -1,
                    "server_parallel": 4,
                    "cont_batching": True,
                    "cache_reuse": 256,
                    "cache_type_k": "f16",
                    "cache_type_v": "f16",
                    "cpu_moe": cpu_moe,
                    "n_cpu_moe": n_cpu_moe,
                    "timeout": 180,
                }
            },
            "pipeline": {
                "parallel": 3,
                "stages": {"emotions": "srv"},
            },
        }
    )


def test_launch_profile_builds_current_llama_server_flags() -> None:
    profile = build_llama_server_launch_profile(_config(cpu_moe=True), "srv")

    assert profile.parallel == 4
    assert profile.context_per_slot == 4096
    assert profile.context_total == 16384
    assert profile.host == "127.0.0.1"
    assert profile.port == 9090
    assert profile.command() == [
        "llama-server",
        "--model",
        "models/model.gguf",
        "--host",
        "127.0.0.1",
        "--port",
        "9090",
        "--ctx-size",
        "16384",
        "--n-gpu-layers",
        "all",
        "--parallel",
        "4",
        "--cont-batching",
        "--cache-prompt",
        "--cache-type-k",
        "f16",
        "--cache-type-v",
        "f16",
        "--slots",
        "--cache-reuse",
        "256",
        "--cpu-moe",
    ]


def test_launch_profile_supports_partial_cpu_moe() -> None:
    profile = build_llama_server_launch_profile(_config(n_cpu_moe=12), "srv")
    command = profile.command()

    assert "--cpu-moe" not in command
    assert command[-2:] == ["--n-cpu-moe", "12"]


def test_launch_profile_rejects_non_root_or_non_http_base_url() -> None:
    cfg = _config()
    cfg.models["srv"].base_url = "http://127.0.0.1:9090/v1"
    with pytest.raises(BackendConfigError, match="sin path"):
        build_llama_server_launch_profile(cfg, "srv")

    cfg.models["srv"].base_url = "https://127.0.0.1:9090"
    with pytest.raises(BackendConfigError, match="http://host"):
        build_llama_server_launch_profile(cfg, "srv")


def test_runtime_profile_reads_health_slots_and_props() -> None:
    backend = LlamaServerBackend("srv", {"base_url": "http://test", "timeout": 1})

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/health":
            return httpx.Response(200, json={"status": "ok"})
        if request.url.path == "/slots":
            return httpx.Response(200, json=[{"n_ctx": 4096}, {"n_ctx": 4096}])
        if request.url.path == "/props":
            return httpx.Response(200, json={"model_path": "/models/model.gguf"})
        return httpx.Response(404)

    backend._http.close()
    backend._http = httpx.Client(
        base_url="http://test",
        transport=httpx.MockTransport(handler),
        timeout=1,
    )
    try:
        observed = backend.runtime_profile()
    finally:
        backend.close()

    assert observed == {
        "base_url": "http://test",
        "health": "ok",
        "parallel_slots": 2,
        "slot_context_lengths": [4096],
        "model_path": "/models/model.gguf",
        "slots_observed": True,
        "props_observed": True,
    }


def test_runtime_profile_falls_back_to_props_for_slots_and_context() -> None:
    backend = LlamaServerBackend("srv", {"base_url": "http://test", "timeout": 1})

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/health":
            return httpx.Response(200, json={"status": "ok"})
        if request.url.path == "/slots":
            return httpx.Response(501, json={"error": "disabled"})
        if request.url.path == "/props":
            return httpx.Response(
                200,
                json={
                    "total_slots": 3,
                    "model_path": "/models/model.gguf",
                    "default_generation_settings": {"n_ctx": 2048},
                },
            )
        return httpx.Response(404)

    backend._http.close()
    backend._http = httpx.Client(
        base_url="http://test",
        transport=httpx.MockTransport(handler),
        timeout=1,
    )
    try:
        observed = backend.runtime_profile()
    finally:
        backend.close()

    assert observed["parallel_slots"] == 3
    assert observed["slot_context_lengths"] == [2048]
    assert observed["slots_observed"] is False
    assert observed["props_observed"] is True


def test_runtime_profile_requires_ready_health() -> None:
    backend = LlamaServerBackend("srv", {"base_url": "http://test", "timeout": 1})
    backend._http.close()
    backend._http = httpx.Client(
        base_url="http://test",
        transport=httpx.MockTransport(lambda _request: httpx.Response(503, text="loading")),
        timeout=1,
    )
    try:
        with pytest.raises(BackendUnavailableError, match="no está listo"):
            backend.runtime_profile()
    finally:
        backend.close()


def test_runtime_snapshot_records_declared_observed_and_effective_parallel() -> None:
    from emoparse.pipeline.runtime_config import (
        attach_llm_runtime,
        record_server_observed,
        record_stage_effective_parallel,
    )

    cfg = _config(cpu_moe=True)
    snapshot = attach_llm_runtime(
        cfg.model_dump(exclude_none=True),
        cfg,
        ["emotions"],
        token_budget_active=False,
    )

    llm = snapshot["_emoparse"]["llm"]
    assert llm["pipeline_parallel_requested"] == 3
    assert llm["llama_servers"]["srv"]["configured"]["server_parallel"] == 4
    assert llm["llama_servers"]["srv"]["configured"]["cpu_moe"] is True

    record_server_observed(snapshot, "srv", {"parallel_slots": 4, "health": "ok"})
    record_stage_effective_parallel(snapshot, "emotions", 3)

    assert llm["llama_servers"]["srv"]["observed"]["parallel_slots"] == 4
    assert llm["stage_routing"]["emotions"]["effective_parallel"] == 3


def test_server_cli_dry_run_does_not_start_process(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from emoparse.cli.commands import server_cmd

    model = tmp_path / "model.gguf"
    model.write_text("placeholder", encoding="utf-8")
    config = tmp_path / "config.yaml"
    config.write_text(
        f"""
models:
  srv:
    backend: llama_server
    path: {model}
    base_url: http://127.0.0.1:8080
    server_parallel: 2
    context_length: 2048
pipeline:
  parallel: 2
""",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        server_cmd.subprocess,
        "run",
        lambda *_args, **_kwargs: pytest.fail("dry-run no debe iniciar procesos"),
    )
    args = argparse.Namespace(
        config=str(config),
        model="srv",
        binary=None,
        dry_run=True,
        check=False,
    )

    assert server_cmd.handle(args) == 0
    out = capsys.readouterr().out
    assert "--parallel 2" in out
    assert "--ctx-size 4096" in out


def test_server_cli_check_rejects_slot_mismatch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from emoparse.cli.commands import server_cmd

    config = tmp_path / "config.yaml"
    config.write_text(
        """
models:
  srv:
    backend: llama_server
    path: models/model.gguf
    server_parallel: 4
pipeline:
  parallel: 4
""",
        encoding="utf-8",
    )

    class _Backend:
        def __init__(self, *args: object, **kwargs: object) -> None:
            pass

        def runtime_profile(self) -> dict[str, object]:
            return {"parallel_slots": 2, "health": "ok"}

        def close(self) -> None:
            pass

    monkeypatch.setattr(server_cmd, "LlamaServerBackend", _Backend)
    args = argparse.Namespace(
        config=str(config),
        model="srv",
        binary=None,
        dry_run=False,
        check=True,
    )

    with pytest.raises(BackendConfigError, match="expone 2 slot"):
        server_cmd.handle(args)


def test_effective_parallel_caps_to_observed_server_slots() -> None:
    # Se construye sólo la porción mínima del runner requerida por este contrato.
    from emoparse.pipeline.runner import PipelineRunner

    runner = object.__new__(PipelineRunner)
    runner._token_budget = None
    runner._cfg = SimpleNamespace(
        pipeline=SimpleNamespace(parallel=4, stages={"emotions": "srv"}),
        models={"srv": SimpleNamespace(backend="llama_server", server_parallel=4)},
    )
    runner._server_runtime_profiles = {"srv": {"parallel_slots": 2}}
    runner._record_effective_parallel = lambda _stage, _effective: None

    assert runner._effective_parallel("emotions") == 2
