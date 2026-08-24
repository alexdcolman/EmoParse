"""Metadata de ejecución derivada y persistida junto al config del run."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from emoparse.config.models import RunConfig
from emoparse.core.backend.server_launch import configured_server_runtime
from emoparse.genres.presentation import RUNTIME_CONFIG_KEY


def attach_llm_runtime(
    config: Mapping[str, Any],
    run_config: RunConfig,
    enabled_stages: Iterable[str],
    *,
    token_budget_active: bool,
) -> dict[str, Any]:
    """Agrega routing y perfil server declarados sin alterar el config fuente."""
    out = dict(config)
    runtime_raw = out.get(RUNTIME_CONFIG_KEY)
    runtime = dict(runtime_raw) if isinstance(runtime_raw, Mapping) else {}

    stage_routing: dict[str, dict[str, Any]] = {}
    server_aliases: set[str] = set()
    for stage in enabled_stages:
        alias = run_config.pipeline.stages.get(stage)
        if alias is None or alias not in run_config.models:
            continue
        model = run_config.models[alias]
        stage_routing[stage] = {
            "alias": alias,
            "backend": model.backend,
        }
        if model.backend == "llama_server":
            server_aliases.add(alias)

    servers = {
        alias: {
            "configured": configured_server_runtime(run_config, alias),
            "observed": None,
        }
        for alias in sorted(server_aliases)
    }
    runtime["llm"] = {
        "pipeline_parallel_requested": int(run_config.pipeline.parallel),
        "token_budget_forces_sequential": bool(token_budget_active),
        "stage_routing": stage_routing,
        "llama_servers": servers,
    }
    out[RUNTIME_CONFIG_KEY] = runtime
    return out


def record_server_observed(
    config: dict[str, Any],
    alias: str,
    observed: Mapping[str, Any],
) -> None:
    """Registra el estado observado de un alias server en el snapshot mutable."""
    runtime = config.setdefault(RUNTIME_CONFIG_KEY, {})
    if not isinstance(runtime, dict):
        return
    llm = runtime.setdefault("llm", {})
    if not isinstance(llm, dict):
        return
    servers = llm.setdefault("llama_servers", {})
    if not isinstance(servers, dict):
        return
    entry = servers.setdefault(alias, {})
    if not isinstance(entry, dict):
        return
    entry["observed"] = dict(observed)


def record_stage_effective_parallel(
    config: dict[str, Any],
    stage_name: str,
    effective_parallel: int,
) -> None:
    """Persiste el paralelismo realmente usado por una stage cuando aplica."""
    runtime = config.get(RUNTIME_CONFIG_KEY)
    if not isinstance(runtime, dict):
        return
    llm = runtime.get("llm")
    if not isinstance(llm, dict):
        return
    routing = llm.get("stage_routing")
    if not isinstance(routing, dict):
        return
    stage = routing.get(stage_name)
    if isinstance(stage, dict):
        stage["effective_parallel"] = int(effective_parallel)
