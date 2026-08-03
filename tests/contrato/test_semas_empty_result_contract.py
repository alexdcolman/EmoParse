"""Contratos de estado para referentes procesados sin semas."""

from __future__ import annotations

import importlib.util
import sqlite3
import sys
from pathlib import Path
from types import ModuleType


def _load_status_module() -> ModuleType:
    pipeline_dir = Path(__file__).parents[2] / "src" / "emoparse" / "pipeline"
    package_name = "emoparse.pipeline"
    module_name = "emoparse.pipeline.status"
    previous_package = sys.modules.get(package_name)
    previous_module = sys.modules.get(module_name)
    package = ModuleType(package_name)
    package.__path__ = [str(pipeline_dir)]  # type: ignore[attr-defined]
    try:
        sys.modules[package_name] = package
        spec = importlib.util.spec_from_file_location(
            module_name,
            pipeline_dir / "status.py",
        )
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        spec.loader.exec_module(module)
        return module
    finally:
        if previous_package is None:
            sys.modules.pop(package_name, None)
        else:
            sys.modules[package_name] = previous_package
        if previous_module is None:
            sys.modules.pop(module_name, None)
        else:
            sys.modules[module_name] = previous_module


def test_zero_semas_is_completed_not_pending() -> None:
    status_module = _load_status_module()
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE menciones (
            id INTEGER PRIMARY KEY,
            codigo TEXT NOT NULL
        );
        CREATE TABLE mencion_canonico (
            mencion_id INTEGER NOT NULL,
            canonical_id TEXT NOT NULL,
            semas_version TEXT,
            semas_error TEXT
        );
        CREATE TABLE canonico_semas (
            canonical_id TEXT NOT NULL,
            sema TEXT NOT NULL
        );
        INSERT INTO menciones VALUES (1, 'discurso_1');
        INSERT INTO menciones VALUES (2, 'discurso_1');
        INSERT INTO mencion_canonico VALUES (1, 'sin_semas', 'v47', NULL);
        INSERT INTO mencion_canonico VALUES (2, 'con_semas', 'v47', NULL);
        INSERT INTO canonico_semas VALUES ('con_semas', 'institucion');
        """
    )

    try:
        status = status_module._referente_stage(conn, "semas", True)
    finally:
        conn.close()

    assert status.completed == 2
    assert status.pending == 0
    assert status.failed == 0
