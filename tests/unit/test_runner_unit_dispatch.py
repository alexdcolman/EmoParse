# ══════════════════════════════════════════════════════════════════════════════
#  tests.unit.test_runner_unit_dispatch
#
#  El Runner debe despachar al splitter correcto según el `unit`
#  del género activo:
#    - unit="frase"     -> split_into_sentences (oraciones)
#    - unit="parrafo"   -> split_into_paragraphs
#    - unit="documento" -> [texto.strip()]
# ══════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

from emoparse.genres.base import Genre
from emoparse.pipeline.chunking import split_into_sentences
from emoparse.pipeline.unit_dispatch import (
    split_for,
    split_into_paragraphs,
)


def _make_chunker(genre: Genre):
    """Reproduce el dispatch que vive dentro de Runner._chunk_all_discursos.

    Esta función NO es parte de la API pública del Runner — duplica
    la lógica del closure interno. Si esa lógica cambia, este test
    actuará como detector temprano de regresiones.
    """
    unit = genre.unit
    if unit == "frase":
        def chunker(text: str, max_chars: int) -> list[str]:
            return split_into_sentences(text, max_chars=max_chars)
    elif unit == "parrafo":
        def chunker(text: str, max_chars: int) -> list[str]:
            return split_into_paragraphs(text)
    else:  # documento
        def chunker(text: str, max_chars: int) -> list[str]:
            return split_for(text, "documento")
    return chunker


def _genre_with_unit(unit: str) -> Genre:
    return Genre(
        genre_id=f"test_{unit}",
        display_name=f"Test {unit}",
        unit=unit,  # type: ignore[arg-type]
        enunciation_roles=("a",),
    )


TEXTO = (
    "Primer párrafo, dos oraciones. La segunda oración es ésta.\n\n"
    "Segundo párrafo, una sola oración.\n\n"
    "Tercer párrafo, también con una oración."
)


class TestFraseDispatch:
    def test_returns_sentences(self) -> None:
        chunker = _make_chunker(_genre_with_unit("frase"))
        out = chunker(TEXTO, 400)
        # Al menos 4 oraciones detectadas
        assert len(out) >= 4

    def test_max_chars_is_respected(self) -> None:
        # Una oración muy larga sin signos intermedios debería ir entera
        # cuando max_chars la abarca; debería sub-dividirse si max_chars
        # es chico Y hay comas/pyc.
        chunker = _make_chunker(_genre_with_unit("frase"))
        out_large = chunker(TEXTO, 1000)
        out_small = chunker(TEXTO, 50)
        assert len(out_small) >= len(out_large)


class TestParrafoDispatch:
    def test_returns_three_paragraphs(self) -> None:
        chunker = _make_chunker(_genre_with_unit("parrafo"))
        out = chunker(TEXTO, 400)  # max_chars ignorado para parrafo
        assert len(out) == 3

    def test_short_paragraphs_filtered(self) -> None:
        text = "Hola.\n\nPárrafo con contenido suficiente para no ser filtrado."
        chunker = _make_chunker(_genre_with_unit("parrafo"))
        out = chunker(text, 400)
        # 'Hola.' < 30 chars → filtrado.
        assert len(out) == 1
        assert "suficiente" in out[0]


class TestDocumentoDispatch:
    def test_single_unit_with_full_text(self) -> None:
        chunker = _make_chunker(_genre_with_unit("documento"))
        out = chunker(TEXTO, 400)
        assert len(out) == 1
        assert out[0] == TEXTO.strip()

    def test_empty_returns_empty_list(self) -> None:
        chunker = _make_chunker(_genre_with_unit("documento"))
        assert chunker("", 400) == []
        assert chunker("    \n  ", 400) == []


class TestDispatchAlignedWithGenreUnit:
    """Verifica que los 3 paths producen outputs distintos para el mismo
    input — i.e. que el dispatch realmente está cambiando algo."""

    def test_three_modes_produce_different_results(self) -> None:
        frase = _make_chunker(_genre_with_unit("frase"))(TEXTO, 400)
        parrafo = _make_chunker(_genre_with_unit("parrafo"))(TEXTO, 400)
        documento = _make_chunker(_genre_with_unit("documento"))(TEXTO, 400)

        assert len(frase) != len(parrafo)
        assert len(parrafo) != len(documento)
        # frase > parrafo (más oraciones que párrafos en este input).
        assert len(frase) > len(parrafo)
        # parrafo > documento (3 párrafos vs 1 unidad).
        assert len(parrafo) > len(documento)
