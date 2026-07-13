# ══════════════════════════════════════════════════════════════════════════════
# emoparse.acquisition.author_enrichment
#
# Clase para completar información de perfil (bio, seguidores, siguiendo, verificado)
# en un PostRecord, usando un PostSourceAdapter.
# ══════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

import dataclasses
from typing import Any

from emoparse.acquisition.base_posts import PostSourceAdapter
from emoparse.acquisition.post_record import PostRecord


class AuthorEnricher:
    """Completa autor_bio/autor_seguidores/autor_siguiendo/autor_verificado.

    Requiere una llamada extra por autor (`adapter.fetch_author_profile`);
    cachea por handle para no repetirla dentro de la misma corrida.
    """

    def __init__(self, adapter: PostSourceAdapter) -> None:
        self._adapter = adapter
        self._cache: dict[str, dict[str, Any] | None] = {}

    def apply(self, record: PostRecord) -> PostRecord:
        handle = record.autor_handle
        if not handle:
            return record
        if handle not in self._cache:
            self._cache[handle] = self._adapter.fetch_author_profile(handle)
        profile = self._cache[handle]
        if not profile:
            return record
        return dataclasses.replace(record, **profile)
