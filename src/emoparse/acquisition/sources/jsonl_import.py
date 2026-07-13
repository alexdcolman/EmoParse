# ══════════════════════════════════════════════════════════════════════════════
#  emoparse.acquisition.sources.jsonl_import
#
#  Importador de dumps JSONL de posts hacia el formato normalizado.
#
#  Acepta tres formas de línea, autodetectadas:
#  - Post ya normalizado (trae `texto`): pasa casi directo.
#  - Objeto tweet del formato API v2 de X (trae `text`): se mapea con
#    `map_v2_tweet`, sin includes (o con los de la página, si vienen).
#  - Página de respuesta v2 ({"data": [...], "includes": {...}}), el formato
#    que producen herramientas académicas de archivo: se mapea cada tweet de
#    `data` con sus includes.
#
#  Es un adapter de "fuente" para poder usar `emoparse acquire --source jsonl`
#  y así aprovechar dedupe, filtros por fecha y seudonimización del CLI al
#  convertir dumps ajenos en corpus propios.
# ══════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any, Iterator

from loguru import logger

from emoparse.acquisition.base_posts import PostSourceAdapter, PostSourceError
from emoparse.acquisition.post_record import PostRecord
from emoparse.acquisition.sources.x_api import map_v2_tweet


class JsonlImportAdapter(PostSourceAdapter):
    """Importa posts desde un archivo JSONL local."""

    source_id = "jsonl"

    def __init__(self, path: str) -> None:
        self._path = Path(path).expanduser().resolve()
        if not self._path.is_file():
            raise PostSourceError(f"Archivo no encontrado: {self._path}")

    # ── Modos ────────────────────────────────────────────────────────────────

    def search(
        self,
        query: str,
        max_items: int | None = None,
        from_date: date | None = None,
        to_date: date | None = None,
        lang: str | None = None,
    ) -> Iterator[PostRecord]:
        """Itera todos los posts del archivo (los filtros los aplica el CLI).

        `query` se ignora: un dump local no es una fuente consultable; se
        importa completo y se filtra después.
        """
        if query:
            logger.info(
                "[jsonl] La query se ignora en importación: se emite el "
                "archivo completo (los filtros de fecha aplican post-fetch)."
            )
        yield from self._iter_all(max_items)

    def fetch_thread(self, root_id: str) -> Iterator[PostRecord]:
        """Emite los posts del archivo que pertenecen a la conversación."""
        for record in self._iter_all(None):
            if record.conversacion_id == root_id or record.id == root_id:
                yield record

    def fetch_user(
        self,
        handle: str,
        max_items: int | None = None,
        from_date: date | None = None,
        to_date: date | None = None,
    ) -> Iterator[PostRecord]:
        """Emite los posts del archivo cuyo autor es `handle`."""
        n = 0
        wanted = handle.lstrip("@").lower()
        for record in self._iter_all(None):
            if record.autor_handle.lstrip("@").lower() != wanted:
                continue
            yield record
            n += 1
            if max_items is not None and n >= max_items:
                return

    # ── Iteración y autodetección ────────────────────────────────────────────

    def _iter_all(self, max_items: int | None) -> Iterator[PostRecord]:
        n = 0
        with self._path.open(encoding="utf-8") as fh:
            for lineno, line in enumerate(fh, start=1):
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    logger.warning(f"[jsonl] Línea {lineno} ilegible, la salteo.")
                    continue
                if not isinstance(obj, dict):
                    logger.warning(f"[jsonl] Línea {lineno} no es objeto, la salteo.")
                    continue
                for record in _map_line(obj):
                    yield record
                    n += 1
                    if max_items is not None and n >= max_items:
                        return


def _map_line(obj: dict[str, Any]) -> Iterator[PostRecord]:
    """Autodetecta la forma de la línea y emite sus PostRecord."""
    if "texto" in obj:
        yield _from_normalized(obj)
        return
    if "text" in obj and "id" in obj:
        yield map_v2_tweet(obj)
        return
    data = obj.get("data")
    if isinstance(data, list):
        includes = obj.get("includes") if isinstance(obj.get("includes"), dict) else {}
        for tweet in data:
            if isinstance(tweet, dict) and "text" in tweet:
                yield map_v2_tweet(tweet, includes)
        return
    logger.warning("[jsonl] Línea con forma desconocida, la salteo.")


def _from_normalized(obj: dict[str, Any]) -> PostRecord:
    """Construye un PostRecord desde una línea ya normalizada."""
    media = obj.get("media")
    metricas = obj.get("metricas")
    return PostRecord(
        id=str(obj.get("id") or ""),
        plataforma=str(obj.get("plataforma") or "desconocida"),
        autor_handle=str(obj.get("autor_handle") or ""),
        autor_display=obj.get("autor_display"),
        autor_bio=obj.get("autor_bio"),
        texto=str(obj.get("texto") or ""),
        fecha=obj.get("fecha"),
        lang=obj.get("lang"),
        tipo=str(obj.get("tipo") or "original"),
        conversacion_id=obj.get("conversacion_id"),
        en_respuesta_a=obj.get("en_respuesta_a"),
        cita_a=obj.get("cita_a"),
        reposteo_a=obj.get("reposteo_a"),
        url=obj.get("url"),
        metricas=metricas if isinstance(metricas, dict) else {},
        media=tuple(m for m in media if isinstance(m, dict)) if isinstance(media, list) else (),
        raw=obj.get("raw") if isinstance(obj.get("raw"), dict) else None,
    )
