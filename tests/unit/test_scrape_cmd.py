# ══════════════════════════════════════════════════════════════════════════════
#  tests/unit/test_scrape_cmd.py
#
#  Tests del subcomando `emoparse scrape`. Se mockea el adapter en el
#  registry para que el comando no toque la red.
# ══════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

import csv
from collections.abc import Iterator
from datetime import date
from pathlib import Path

import pytest

from emoparse.cli.commands import scrape_cmd
from emoparse.acquisition import SOURCES
from emoparse.acquisition.base import DiscursoRecord, SourceAdapter


class _FakeAdapter(SourceAdapter):
    source_id = "fake"
    requires_selenium = False

    def __init__(self, **kwargs: object) -> None:
        self._urls = [
            f"https://fake.example.com/d/{i}" for i in range(1, 6)
        ]
        self._records = {
            url: DiscursoRecord(
                codigo=f"fake_{i}",
                url=url,
                titulo=f"Discurso {i}",
                fecha=f"2024-0{i}-01",
                contenido=f"contenido del discurso {i}.",
                fuente="fake",
            )
            for i, url in enumerate(self._urls, start=1)
        }

    def list_discursos(
        self,
        *,
        max_items: int | None = None,
        from_date: date | None = None,
        to_date: date | None = None,
    ) -> Iterator[str]:
        for url in self._urls[: max_items if max_items else None]:
            yield url

    def fetch_discurso(self, url: str) -> DiscursoRecord | None:
        return self._records.get(url)


@pytest.fixture
def fake_source_registered() -> Iterator[None]:
    """Inyecta `_FakeAdapter` en el registry durante el test."""
    SOURCES["fake"] = _FakeAdapter
    try:
        yield
    finally:
        SOURCES.pop("fake", None)


def _build_args(**overrides: object) -> object:
    """argparse.Namespace compatible con scrape_cmd.run."""
    import argparse
    return argparse.Namespace(
        source=overrides.get("source", "fake"),
        output=overrides["output"],
        max=overrides.get("max", None),
        from_date=overrides.get("from_date", None),
        to_date=overrides.get("to_date", None),
        mode=overrides.get("mode", "auto"),
        timeout=overrides.get("timeout", 20.0),
    )


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def test_scrape_basico(tmp_path: Path, fake_source_registered: None) -> None:
    out = tmp_path / "out.csv"
    rc = scrape_cmd.run(_build_args(output=out))
    assert rc == 0
    rows = _read_csv(out)
    assert len(rows) == 5
    assert rows[0]["codigo"] == "fake_1"


def test_scrape_max_corta_a_n(tmp_path: Path, fake_source_registered: None) -> None:
    out = tmp_path / "out.csv"
    rc = scrape_cmd.run(_build_args(output=out, max=2))
    assert rc == 0
    rows = _read_csv(out)
    assert len(rows) == 2


def test_scrape_filtro_de_fechas(tmp_path: Path, fake_source_registered: None) -> None:
    out = tmp_path / "out.csv"
    # Solo los discursos de marzo en adelante (fake_3, fake_4, fake_5).
    rc = scrape_cmd.run(_build_args(
        output=out,
        from_date=date(2024, 3, 1),
    ))
    assert rc == 0
    rows = _read_csv(out)
    codigos = {r["codigo"] for r in rows}
    assert codigos == {"fake_3", "fake_4", "fake_5"}


def test_scrape_es_resumable(tmp_path: Path, fake_source_registered: None) -> None:
    """Una segunda corrida sobre el mismo CSV no duplica filas."""
    out = tmp_path / "out.csv"
    scrape_cmd.run(_build_args(output=out, max=3))
    scrape_cmd.run(_build_args(output=out))
    rows = _read_csv(out)
    assert len(rows) == 5


def test_scrape_source_desconocido(tmp_path: Path) -> None:
    out = tmp_path / "out.csv"
    import argparse
    args = argparse.Namespace(
        source="no_existe", output=out,
        max=None, from_date=None, to_date=None,
        mode="auto", timeout=20.0,
    )
    rc = scrape_cmd.run(args)
    assert rc != 0
    assert not out.exists()
