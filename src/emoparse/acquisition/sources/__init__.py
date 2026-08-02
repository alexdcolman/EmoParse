# ══════════════════════════════════════════════════════════════════════════════
#  emoparse.acquisition.sources
#
#  Registro de adapters disponibles.
# ══════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

from emoparse.acquisition.base import SourceAdapter
from emoparse.acquisition.sources.casarosada import CasaRosadaAdapter
from emoparse.acquisition.sources.pagina12 import Pagina12Adapter


#: Registro de adapters por source_id.
SOURCES: dict[str, type[SourceAdapter]] = {
    CasaRosadaAdapter.source_id: CasaRosadaAdapter,
    Pagina12Adapter.source_id: Pagina12Adapter,
}


def get_source(source_id: str, **kwargs: object) -> SourceAdapter:
    """Devuelve un adapter instanciado para el source_id dado."""
    if source_id not in SOURCES:
        available = sorted(SOURCES.keys())
        raise ValueError(
            f"Source '{source_id}' desconocido. Disponibles: {available}"
        )
    return SOURCES[source_id](**kwargs)


__all__ = ["SOURCES", "get_source"]
