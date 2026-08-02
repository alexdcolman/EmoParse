# ══════════════════════════════════════════════════════════════════════════════
#  tests/andamio/test_compatibility_aliases
#
#  Los paths históricos deben delegar en las implementaciones canónicas.
# ══════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

import importlib.util

import pytest


@pytest.mark.unit
def test_backend_grammar_reexports_canonical_objects() -> None:
    from emoparse.core import grammar as canonical
    from emoparse.core.backend import grammar as compatibility

    assert compatibility.GrammarError is canonical.GrammarError
    assert compatibility.PRIMITIVE_RULES is canonical.PRIMITIVE_RULES
    assert compatibility.schema_to_gbnf is canonical.schema_to_gbnf


@pytest.mark.unit
def test_scraping_modules_reexport_acquisition_objects() -> None:
    if importlib.util.find_spec("tenacity") is None:
        pytest.skip("tenacity no está disponible en el entorno")

    from emoparse.acquisition import base as base_canonical
    from emoparse.acquisition import normalize as normalize_canonical
    from emoparse.acquisition import persist as persist_canonical
    from emoparse.scraping import base as base_compatibility
    from emoparse.scraping import normalize as normalize_compatibility
    from emoparse.scraping import persist as persist_compatibility

    assert base_compatibility.DiscursoRecord is base_canonical.DiscursoRecord
    assert base_compatibility.SourceAdapter is base_canonical.SourceAdapter
    assert normalize_compatibility.clean_whitespace is normalize_canonical.clean_whitespace
    assert normalize_compatibility.normalize_date is normalize_canonical.normalize_date
    assert persist_compatibility.CsvAppender is persist_canonical.CsvAppender
