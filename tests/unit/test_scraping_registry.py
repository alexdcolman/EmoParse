# ══════════════════════════════════════════════════════════════════════════════
#  tests/unit/test_scraping_registry.py
# ══════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

import pytest

from emoparse.scraping import SOURCES, get_source
from emoparse.scraping.sources.casarosada import CasaRosadaAdapter


def test_casarosada_registrado() -> None:
    assert "casarosada" in SOURCES
    assert SOURCES["casarosada"] is CasaRosadaAdapter


def test_get_source_devuelve_instancia() -> None:
    adapter = get_source("casarosada", mode="http")
    assert isinstance(adapter, CasaRosadaAdapter)
    adapter.close()


def test_get_source_pasa_kwargs() -> None:
    adapter = get_source("casarosada", mode="selenium", timeout=10.0)
    assert adapter._mode == "selenium"
    adapter.close()


def test_get_source_unknown() -> None:
    with pytest.raises(ValueError, match="desconocido"):
        get_source("no_existe")


def test_source_id_estable() -> None:
    """El source_id de cada adapter debe coincidir con la key del registry."""
    for sid, cls in SOURCES.items():
        assert cls.source_id == sid
