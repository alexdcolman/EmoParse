from __future__ import annotations

from emoparse.app.components.run_selector import _brand_markup
from emoparse.app.main import _results_title
from emoparse.version import __version__


def test_sidebar_brand_uses_canonical_version() -> None:
    markup = _brand_markup()

    assert f"v{__version__}" in markup
    assert "v0.6.5" not in markup


def test_results_title_uses_snapshot_genre_without_inferred_suffix() -> None:
    title = _results_title(
        {
            "genre_id": "articulo_periodistico",
            "genre_display_name": "Artículo periodístico",
            "genre_inferred": False,
        }
    )

    assert title == "# Resultados · Artículo periodístico"


def test_results_title_marks_only_legacy_genre_as_inferred() -> None:
    title = _results_title(
        {
            "genre_id": "articulo_periodistico",
            "genre_display_name": "articulo_periodistico",
            "genre_inferred": True,
        }
    )

    assert title == "# Resultados · articulo_periodistico (inferido)"
