"""La referencia pública del CLI se deriva del parser vigente."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

from emoparse.cli.__main__ import build_parser


def _load_generator(project_root: Path) -> ModuleType:
    path = project_root / "scripts" / "gen_cli_reference.py"
    spec = importlib.util.spec_from_file_location("gen_cli_reference_test", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_generated_cli_reference_is_synchronized(project_root: Path) -> None:
    generator = _load_generator(project_root)

    assert generator.main(["--check"]) == 0


def test_generated_reference_contains_every_registered_command(project_root: Path) -> None:
    generator = _load_generator(project_root)
    markdown = generator.render_markdown(build_parser())

    for command in generator._subcomandos(build_parser()):
        assert f"## `emoparse {command}`" in markdown
