# ══════════════════════════════════════════════════════════════════════════════
#  tests.unit.test_unit_dispatch
#
#  Dispatch del chunker según genre.unit.
# ══════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

import pytest

from emoparse.pipeline.unit_dispatch import (
    split_for,
    split_into_paragraphs,
)


SAMPLE_TEXT = (
    "Este es el primer párrafo. Tiene dos oraciones.\n\n"
    "Segundo párrafo, una sola oración.\n\n"
    "Tercer párrafo, también con dos oraciones. La segunda."
)


class TestSplitForFrase:
    def test_returns_sentence_list(self) -> None:
        units = split_for(SAMPLE_TEXT, "frase")
        assert len(units) >= 4  # al menos 4 oraciones
        assert all(isinstance(u, str) for u in units)
        assert all(u.strip() for u in units)


class TestSplitForParrafo:
    def test_returns_three_paragraphs(self) -> None:
        units = split_for(SAMPLE_TEXT, "parrafo")
        assert len(units) == 3

    def test_no_double_newlines_returns_single_unit(self) -> None:
        text = "Un texto sin marcadores de párrafo. Solo oraciones."
        units = split_for(text, "parrafo")
        assert units == [text.strip()]

    def test_empty_text_returns_empty(self) -> None:
        assert split_for("", "parrafo") == []
        assert split_for("   \n\n  ", "parrafo") == []

    def test_filters_very_short_paragraphs(self) -> None:
        text = "Hola.\n\nEste sí es un párrafo con suficiente contenido."
        units = split_into_paragraphs(text, min_chars=30)
        # "Hola." se filtra; queda solo el largo.
        assert len(units) == 1
        assert "suficiente contenido" in units[0]


class TestSplitForDocumento:
    def test_returns_full_text_stripped(self) -> None:
        text = "  un tuit corto.  "
        units = split_for(text, "documento")
        assert units == ["un tuit corto."]

    def test_multiline_treated_as_single_unit(self) -> None:
        text = "línea 1.\n\nlínea 2.\n\nlínea 3."
        units = split_for(text, "documento")
        assert len(units) == 1

    def test_empty_returns_empty(self) -> None:
        assert split_for("", "documento") == []
        assert split_for("   ", "documento") == []


class TestInvalidUnit:
    def test_unknown_unit_raises(self) -> None:
        with pytest.raises(ValueError, match="unit desconocido"):
            split_for("x", "capitulo")  # type: ignore[arg-type]
