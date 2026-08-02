# ══════════════════════════════════════════════════════════════════════════════
#  tests/andamio/test_optional_scraping_import
#
#  El extra de scraping no debe ser necesario para importar el registro.
# ══════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

import ast
from pathlib import Path

import pytest


@pytest.mark.unit
@pytest.mark.parametrize("module_name", ["casarosada", "pagina12"])
def test_article_sources_do_not_import_bs4_at_module_level(
    module_name: str,
) -> None:
    source = (
        Path(__file__).parents[2]
        / "src"
        / "emoparse"
        / "acquisition"
        / "sources"
        / f"{module_name}.py"
    )
    tree = ast.parse(source.read_text(encoding="utf-8"))

    eager_imports = []
    for node in tree.body:
        if isinstance(node, ast.Import):
            eager_imports.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            eager_imports.append(node.module)

    assert "bs4" not in eager_imports
