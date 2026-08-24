"""Contratos de los backends remotos OpenAI y Anthropic (3.2A)."""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest
from pydantic import BaseModel, Field, RootModel

from emoparse.config.secrets import sanitize_config_snapshot
from emoparse.core.backend.anthropic_api import AnthropicBackend
from emoparse.core.backend.base import TokenUsage
from emoparse.core.backend.exceptions import (
    BackendConfigError,
    BackendUnavailableError,
    ContextLengthExceededError,
    SchemaViolationError,
)
from emoparse.core.backend.http_api import raise_api_http_error
from emoparse.core.backend.openai_api import OpenAIBackend
from emoparse.core.backend.registry import build_backend
from emoparse.core.cache.backend import CachedBackend
from emoparse.core.cache.repository import CacheRepository
from emoparse.storage.db import Database
from emoparse.storage.metrics import MetricsRepository, StageMetricsSnapshot
from emoparse.storage.models import RunContext
from emoparse.storage.runs import RunsRepository


class Item(BaseModel):
    codigo: str = Field(min_length=3)
    valor: int = Field(ge=1)


class Batch(RootModel[list[Item]]):
    pass


def _replace_http(backend: Any, handler: Any) -> None:
    headers = dict(backend._http.headers)
    backend._http.close()
    backend._http = httpx.Client(
        base_url="http://test",
        headers=headers,
        transport=httpx.MockTransport(handler),
        timeout=1,
    )


def test_openai_uses_strict_json_schema_and_reports_usage(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "secret-openai")
    seen: dict[str, Any] = {}
    backend = OpenAIBackend(
        "oa",
        {"backend": "openai", "model_id": "model-x", "base_url": "http://test"},
    )

    def handler(request: httpx.Request) -> httpx.Response:
        seen["authorization"] = request.headers.get("authorization")
        seen["payload"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "model": "model-x",
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {
                            "content": '[{"codigo":"abc","valor":1},{"codigo":"def","valor":2}]'
                        },
                    }
                ],
                "usage": {"prompt_tokens": 11, "completion_tokens": 7},
            },
        )

    _replace_http(backend, handler)
    try:
        response = backend.generate("system", "user", schema=Batch, max_items=2)
    finally:
        backend.close()

    payload = seen["payload"]
    schema = payload["response_format"]["json_schema"]
    assert schema["strict"] is True
    assert schema["schema"]["minItems"] == 2
    assert schema["schema"]["maxItems"] == 2
    assert seen["authorization"] == "Bearer secret-openai"
    assert isinstance(response.parsed, Batch)
    assert response.usage == TokenUsage(prompt_tokens=11, completion_tokens=7)
    assert response.extra["provider"] == "openai"


def test_anthropic_uses_native_output_config_and_postvalidates_constraints(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "secret-anthropic")
    seen: dict[str, Any] = {}
    backend = AnthropicBackend(
        "claude",
        {"backend": "anthropic", "model_id": "claude-x", "base_url": "http://test"},
    )

    def handler(request: httpx.Request) -> httpx.Response:
        seen["key"] = request.headers.get("x-api-key")
        seen["payload"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "model": "claude-x",
                "stop_reason": "end_turn",
                "content": [{"type": "text", "text": '{"codigo":"abc","valor":1}'}],
                "usage": {"input_tokens": 13, "output_tokens": 5},
            },
        )

    _replace_http(backend, handler)
    try:
        response = backend.generate("system", "user", schema=Item)
    finally:
        backend.close()

    payload = seen["payload"]
    out_schema = payload["output_config"]["format"]["schema"]
    assert payload["output_config"]["format"]["type"] == "json_schema"
    assert out_schema["additionalProperties"] is False
    # Anthropic no compila estas restricciones: EmoParse las valida después.
    assert "minLength" not in json.dumps(out_schema)
    assert "minimum" not in json.dumps(out_schema)
    assert seen["key"] == "secret-anthropic"
    assert isinstance(response.parsed, Item)
    assert response.usage == TokenUsage(prompt_tokens=13, completion_tokens=5)


def test_anthropic_rejects_response_that_violates_original_pydantic_schema(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "secret")
    backend = AnthropicBackend(
        "claude",
        {"backend": "anthropic", "model_id": "claude-x", "base_url": "http://test"},
    )
    _replace_http(
        backend,
        lambda _request: httpx.Response(
            200,
            json={
                "stop_reason": "end_turn",
                "content": [{"type": "text", "text": '{"codigo":"x","valor":0}'}],
                "usage": {"input_tokens": 10, "output_tokens": 4},
            },
        ),
    )
    try:
        with pytest.raises(SchemaViolationError) as captured:
            backend.generate("", "user", schema=Item)
    finally:
        backend.close()

    assert captured.value.prompt_tokens == 10
    assert captured.value.completion_tokens == 4


def test_anthropic_enforces_dynamic_batch_cardinality_after_generation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "secret")
    backend = AnthropicBackend(
        "claude",
        {"backend": "anthropic", "model_id": "claude-x", "base_url": "http://test"},
    )
    _replace_http(
        backend,
        lambda _request: httpx.Response(
            200,
            json={
                "stop_reason": "end_turn",
                "content": [
                    {
                        "type": "text",
                        "text": '[{"codigo":"abc","valor":1}]',
                    }
                ],
                "usage": {"input_tokens": 10, "output_tokens": 4},
            },
        ),
    )
    try:
        with pytest.raises(SchemaViolationError, match="cardinalidad"):
            backend.generate("", "user", schema=Batch, max_items=2)
    finally:
        backend.close()


def test_api_http_error_maps_retry_after_auth_context_and_schema() -> None:
    with pytest.raises(BackendUnavailableError) as rate:
        raise_api_http_error(
            "OpenAI",
            httpx.Response(429, headers={"Retry-After": "7"}, json={"error": {"message": "rate"}}),
            max_tokens=100,
        )
    assert rate.value.retry_after_seconds == 7.0

    with pytest.raises(BackendConfigError):
        raise_api_http_error(
            "OpenAI", httpx.Response(401, json={"error": "bad key"}), max_tokens=100
        )

    with pytest.raises(ContextLengthExceededError):
        raise_api_http_error(
            "OpenAI",
            httpx.Response(400, json={"error": {"message": "maximum context length exceeded"}}),
            max_tokens=100,
        )

    with pytest.raises(SchemaViolationError):
        raise_api_http_error(
            "Anthropic",
            httpx.Response(400, json={"error": {"message": "invalid output_config schema"}}),
            max_tokens=100,
        )


def test_registry_builds_remote_backends_without_vendor_sdks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "oa")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "an")
    oa = build_backend("oa", {"backend": "openai", "model_id": "gpt-x"})
    an = build_backend("an", {"backend": "anthropic", "model_id": "claude-x"})
    try:
        assert isinstance(oa, OpenAIBackend)
        assert isinstance(an, AnthropicBackend)
    finally:
        oa.close()
        an.close()


def test_config_snapshot_never_persists_api_key() -> None:
    raw = {
        "models": {
            "oa": {
                "backend": "openai",
                "model_id": "gpt-x",
                "api_key": "TOP-SECRET",
                "api_key_env": "OPENAI_API_KEY",
            }
        },
        "nested": [{"Authorization": "Bearer secret", "ok": 1}],
    }
    clean = sanitize_config_snapshot(raw)
    serialized = json.dumps(clean)
    assert "TOP-SECRET" not in serialized
    assert "Bearer secret" not in serialized
    assert clean["models"]["oa"]["api_key_env"] == "OPENAI_API_KEY"


def test_cached_remote_call_hits_provider_only_once(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "secret")
    backend = OpenAIBackend(
        "oa",
        {"backend": "openai", "model_id": "model-x", "base_url": "http://test"},
    )
    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {"content": '{"codigo":"abc","valor":1}'},
                    }
                ],
                "usage": {"prompt_tokens": 8, "completion_tokens": 3},
            },
        )

    _replace_http(backend, handler)
    db = Database(tmp_path / "cache.sqlite")
    ctx = RunContext(run_id="api-cache")
    RunsRepository(db).bootstrap(ctx)
    cached = CachedBackend(backend, CacheRepository(db), ctx)
    try:
        first = cached.generate("system", "same", schema=Item)
        second = cached.generate("system", "same", schema=Item)
    finally:
        cached.close()

    assert calls == 1
    assert first.cache_hit is False
    assert second.cache_hit is True


def test_additive_migration_adds_estimated_cost_to_historical_run_metrics(tmp_path) -> None:
    db = Database(tmp_path / "legacy.sqlite")
    db.execute(
        """
        CREATE TABLE run_metrics (
            run_id TEXT NOT NULL,
            stage_name TEXT NOT NULL,
            n_items_ok INTEGER NOT NULL DEFAULT 0,
            n_items_failed INTEGER NOT NULL DEFAULT 0,
            total_latency_ms REAL NOT NULL DEFAULT 0.0,
            p50_latency_ms REAL,
            p99_latency_ms REAL,
            total_prompt_tokens INTEGER NOT NULL DEFAULT 0,
            total_completion_tokens INTEGER NOT NULL DEFAULT 0,
            cache_hits INTEGER NOT NULL DEFAULT 0,
            cache_misses INTEGER NOT NULL DEFAULT 0,
            recorded_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (run_id, stage_name, recorded_at)
        )
        """
    )
    RunsRepository(db).bootstrap(RunContext(run_id="legacy"))
    columns = {row["name"] for row in db.execute("PRAGMA table_info(run_metrics)").fetchall()}
    assert "model_alias" in columns
    assert "estimated_cost_usd" in columns


def test_cost_value_persists_and_sums(tmp_path) -> None:
    snap = StageMetricsSnapshot(total_prompt_tokens=1_000_000, total_completion_tokens=500_000)
    db = Database(tmp_path / "metrics.sqlite")
    RunsRepository(db).bootstrap(RunContext(run_id="cost"))
    repo = MetricsRepository(db)
    repo.insert("cost", "metadata", snap, model_alias="oa", estimated_cost_usd=6.0)
    row = repo.list_for_run("cost")[0]
    assert row["estimated_cost_usd"] == pytest.approx(6.0)
    assert repo.total_estimated_cost_for_run("cost") == pytest.approx(6.0)
