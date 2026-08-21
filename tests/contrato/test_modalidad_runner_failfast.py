"""Regresión del backend explícito de modalidad: nunca fallback silencioso."""

from __future__ import annotations

import pytest

from emoparse.pipeline.runner import PipelineRunner


def test_modalidad_propaga_error_de_inicializacion_del_backend() -> None:
    runner = object.__new__(PipelineRunner)

    def _boom(_stage: str):
        raise RuntimeError("backend-modalidad-no-carga")

    runner._get_backend = _boom  # type: ignore[method-assign]

    with pytest.raises(RuntimeError, match="backend-modalidad-no-carga"):
        runner._build_stage("modalidad")
