# ══════════════════════════════════════════════════════════════════════════════
#  tests/unit/test_scraping_normalize.py
# ══════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

import pytest

from emoparse.acquisition import normalize


# ── clean_whitespace ─────────────────────────────────────────────────────

def test_clean_whitespace_collapses_horizontal() -> None:
    assert normalize.clean_whitespace("hola   mundo") == "hola mundo"


def test_clean_whitespace_preserves_double_newline() -> None:
    out = normalize.clean_whitespace("a\n\nb")
    assert out == "a\n\nb"


def test_clean_whitespace_collapses_multiple_blank_lines() -> None:
    out = normalize.clean_whitespace("a\n\n\n\n\nb")
    assert out == "a\n\nb"


def test_clean_whitespace_handles_nbsp() -> None:
    assert normalize.clean_whitespace("hola\u00a0mundo") == "hola mundo"


def test_clean_whitespace_empty_input() -> None:
    assert normalize.clean_whitespace("") == ""
    assert normalize.clean_whitespace("   \n\n  ") == ""


def test_clean_whitespace_strips_outer() -> None:
    assert normalize.clean_whitespace("\n\nhola\n\n") == "hola"


# ── strip_boilerplate ────────────────────────────────────────────────────

def test_strip_boilerplate_removes_known_lines() -> None:
    text = "Discurso bla bla.\n\nCompartir\nImprimir\n\nMás contenido."
    out = normalize.strip_boilerplate(text)
    assert "Compartir" not in out
    assert "Imprimir" not in out
    assert "Discurso bla bla." in out
    assert "Más contenido." in out


def test_strip_boilerplate_case_insensitive() -> None:
    out = normalize.strip_boilerplate("texto\nCOMPARTIR\nfin")
    assert "COMPARTIR" not in out


def test_strip_boilerplate_empty_string() -> None:
    assert normalize.strip_boilerplate("") == ""


# ── normalize_date ───────────────────────────────────────────────────────

@pytest.mark.parametrize("raw,expected", [
    ("2024-12-15", "2024-12-15"),
    ("2024-12-15T10:30:00", "2024-12-15"),
    ("2024-12-15T10:30:00-03:00", "2024-12-15"),
    ("15-12-2024", "2024-12-15"),
    ("15/12/2024", "2024-12-15"),
    ("Lunes 15 de diciembre de 2024", "2024-12-15"),
    ("15 de diciembre de 2024", "2024-12-15"),
    ("Martes, 15 de Diciembre, 2024", "2024-12-15"),
    ("15 de febrero de 2025", "2025-02-15"),
])
def test_normalize_date_parses(raw: str, expected: str) -> None:
    assert normalize.normalize_date(raw) == expected


@pytest.mark.parametrize("raw", [
    "",
    "no es fecha",
    "32 de febrero de 2024",  # día imposible
])
def test_normalize_date_returns_empty(raw: str) -> None:
    assert normalize.normalize_date(raw) == ""


def test_normalize_date_handles_setiembre_variant() -> None:
    """Variante regional sin 'p'."""
    assert normalize.normalize_date("15 de setiembre de 2024") == "2024-09-15"


# ── normalize_url ────────────────────────────────────────────────────────

def test_normalize_url_passes_absolute_through() -> None:
    assert normalize.normalize_url("https://x.com/foo") == "https://x.com/foo"


def test_normalize_url_resolves_relative() -> None:
    assert normalize.normalize_url("/foo", "https://x.com") == "https://x.com/foo"


def test_normalize_url_resolves_relative_no_slash() -> None:
    assert normalize.normalize_url("foo", "https://x.com") == "https://x.com/foo"


def test_normalize_url_strips_trailing_slash_in_base() -> None:
    assert normalize.normalize_url("/foo", "https://x.com/") == "https://x.com/foo"


def test_normalize_url_empty() -> None:
    assert normalize.normalize_url("") == ""
