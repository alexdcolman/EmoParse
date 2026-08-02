"""Smoke test opt-in de generación estructurada con un backend real."""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from pydantic import BaseModel

from emoparse.config import load_config
from emoparse.core.backend.registry import BackendRegistry


class _ProbeSchema(BaseModel):
    ok: bool


def _required_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        pytest.skip(f"Definí {name} para ejecutar la integración LLM")
    return value


def test_real_backend_returns_valid_structured_response() -> None:
    config_path = Path(_required_env("EMOPARSE_LLM_TEST_CONFIG"))
    alias = _required_env("EMOPARSE_LLM_TEST_MODEL")
    config = load_config(config_path)
    registry = BackendRegistry({alias: config.model_config_for_alias(alias)})

    try:
        backend = registry.get(alias)
        response = backend.generate(
            "Respondé únicamente con el JSON solicitado.",
            "Indicá que la prueba está operativa.",
            schema=_ProbeSchema,
            max_tokens=32,
            temperature=0.0,
            seed=1,
        )
    finally:
        registry.unload_all()

    assert isinstance(response.parsed, _ProbeSchema)
