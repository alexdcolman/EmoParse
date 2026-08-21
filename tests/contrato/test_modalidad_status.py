"""Contrato de status para modalidad link-aware y revisión upstream."""

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
        spec = importlib.util.spec_from_file_location(module_name, pipeline_dir / "status.py")
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


def test_modalidad_mantiene_pendiente_real_y_cuenta_revision_como_resuelta() -> None:
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
            status TEXT NOT NULL DEFAULT 'accepted',
            modalidad TEXT,
            modalidad_review_reason TEXT
        );
        CREATE TABLE run_metrics (
            stage_name TEXT NOT NULL
        );
        INSERT INTO menciones VALUES (1, 'D1');
        INSERT INTO menciones VALUES (2, 'D1');
        INSERT INTO menciones VALUES (3, 'D1');
        INSERT INTO mencion_canonico VALUES (1, 'resuelto', 'accepted', 'designacion', NULL);
        INSERT INTO mencion_canonico VALUES (2, 'revisar', 'accepted', NULL, 'vinculo no sostenido');
        INSERT INTO mencion_canonico VALUES (3, 'pendiente', 'accepted', NULL, NULL);
        INSERT INTO run_metrics VALUES ('modalidad');
        """
    )
    try:
        status = status_module._referente_stage(conn, "modalidad", True)
    finally:
        conn.close()

    assert status.completed == 2
    assert status.pending == 1
    assert status.no_aplica == 0
