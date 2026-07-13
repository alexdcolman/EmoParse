# ══════════════════════════════════════════════════════════════════════════════
#  tests/unit/test_scraping_persist.py
# ══════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

import csv
from pathlib import Path

import pytest

from emoparse.acquisition.base import DiscursoRecord
from emoparse.acquisition.persist import CsvAppender


def _record(codigo: str, url: str, **extras: object) -> DiscursoRecord:
    return DiscursoRecord(
        codigo=codigo, url=url,
        titulo=f"T-{codigo}", fecha="2024-01-01",
        contenido=f"contenido de {codigo}", fuente="test",
        extras=tuple(extras.items()),
    )


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def test_creates_file_on_first_append(tmp_path: Path) -> None:
    out = tmp_path / "out.csv"
    ap = CsvAppender(out)
    ap.append(_record("a", "https://x.com/a"))
    assert out.exists()
    rows = _read_csv(out)
    assert len(rows) == 1
    assert rows[0]["codigo"] == "a"
    assert rows[0]["url"] == "https://x.com/a"


def test_appends_subsequent_records(tmp_path: Path) -> None:
    out = tmp_path / "out.csv"
    ap = CsvAppender(out)
    ap.append(_record("a", "https://x.com/a"))
    ap.append(_record("b", "https://x.com/b"))
    rows = _read_csv(out)
    assert len(rows) == 2
    assert {r["codigo"] for r in rows} == {"a", "b"}


def test_dedupe_by_url(tmp_path: Path) -> None:
    out = tmp_path / "out.csv"
    ap = CsvAppender(out)
    ap.append(_record("a", "https://x.com/a"))
    # Re-append misma URL: no debería sumar fila.
    ap.append(_record("a-bis", "https://x.com/a"))
    rows = _read_csv(out)
    assert len(rows) == 1


def test_has_url_returns_true_for_appended(tmp_path: Path) -> None:
    out = tmp_path / "out.csv"
    ap = CsvAppender(out)
    ap.append(_record("a", "https://x.com/a"))
    assert ap.has_url("https://x.com/a")
    assert not ap.has_url("https://x.com/b")


def test_resume_picks_up_existing_urls(tmp_path: Path) -> None:
    """Si el CSV ya existe, un appender nuevo carga las URLs existentes."""
    out = tmp_path / "out.csv"
    ap1 = CsvAppender(out)
    ap1.append(_record("a", "https://x.com/a"))

    # Nuevo appender: debe ver la URL ya escrita.
    ap2 = CsvAppender(out)
    assert ap2.has_url("https://x.com/a")
    ap2.append(_record("a-bis", "https://x.com/a"))  # no-op
    rows = _read_csv(out)
    assert len(rows) == 1


def test_extras_become_columns(tmp_path: Path) -> None:
    out = tmp_path / "out.csv"
    ap = CsvAppender(out)
    ap.append(_record("a", "https://x.com/a", orador="presidente"))
    rows = _read_csv(out)
    assert rows[0].get("orador") == "presidente"


def test_extras_with_native_key_get_prefixed(tmp_path: Path) -> None:
    """Si un extra tiene una clave nativa (codigo, url, etc.), se prefija."""
    out = tmp_path / "out.csv"
    ap = CsvAppender(out)
    ap.append(_record("a", "https://x.com/a", titulo="otro"))
    rows = _read_csv(out)
    # `titulo` es nativo → el extra va a `extra__titulo`.
    assert rows[0]["titulo"] == "T-a"  # del campo nativo
    assert rows[0]["extra__titulo"] == "otro"


def test_extends_header_when_new_extras_appear(tmp_path: Path) -> None:
    """Si un record posterior agrega columnas, el CSV se reescribe con
    el header extendido."""
    out = tmp_path / "out.csv"
    ap = CsvAppender(out)
    ap.append(_record("a", "https://x.com/a"))  # sin extras
    ap.append(_record("b", "https://x.com/b", orador="X"))  # con extras
    rows = _read_csv(out)
    assert len(rows) == 2
    # 'a' tiene celda vacía en orador, 'b' tiene 'X'.
    by_codigo = {r["codigo"]: r for r in rows}
    assert by_codigo["a"]["orador"] == ""
    assert by_codigo["b"]["orador"] == "X"


def test_required_columns_always_present(tmp_path: Path) -> None:
    out = tmp_path / "out.csv"
    ap = CsvAppender(out)
    ap.append(_record("a", "https://x.com/a"))
    with out.open("r", encoding="utf-8-sig") as f:
        header = next(csv.reader(f))
    for col in ("codigo", "url", "titulo", "fecha", "contenido", "fuente"):
        assert col in header
