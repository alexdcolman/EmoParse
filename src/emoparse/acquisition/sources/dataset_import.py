# ══════════════════════════════════════════════════════════════════════════════
#  emoparse.acquisition.sources.dataset_import
#
#  Importador de datasets tabulares (CSV) de posts publicados por terceros.
#
#  Los datasets académicos de tuits vienen con nombres de columna dispares;
#  el mapping por defecto cubre los más comunes y puede reemplazarse con un
#  JSON `{campo_normalizado: nombre_de_columna}` vía `--mapping` en el CLI.
# ══════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any, Iterator

import pandas as pd

from emoparse.acquisition.base_posts import PostSourceAdapter, PostSourceError
from emoparse.acquisition.post_record import PostRecord

#: Mapping por defecto: campo normalizado → candidatos de columna, en orden.
_DEFAULT_CANDIDATES: dict[str, tuple[str, ...]] = {
    "id": ("id", "tweet_id", "status_id", "post_id"),
    "texto": ("texto", "text", "tweet", "content", "full_text"),
    "autor_handle": ("autor_handle", "username", "user", "screen_name",
                     "user_screen_name", "author"),
    "autor_display": ("autor_display", "name", "user_name"),
    "fecha": ("fecha", "created_at", "date", "timestamp"),
    "lang": ("lang", "language"),
    "conversacion_id": ("conversacion_id", "conversation_id"),
    "en_respuesta_a": ("en_respuesta_a", "in_reply_to_status_id",
                       "in_reply_to_id", "reply_to_id"),
    "cita_a": ("cita_a", "quoted_status_id", "quoted_id"),
    "reposteo_a": ("reposteo_a", "retweeted_status_id", "retweeted_id"),
    "url": ("url", "link", "tweet_url"),
}


class CsvImportAdapter(PostSourceAdapter):
    """Importa posts desde un CSV con mapping de columnas configurable."""

    source_id = "csv"

    def __init__(
        self,
        path: str,
        mapping: str | None = None,
        plataforma: str = "x",
    ) -> None:
        self._path = Path(path).expanduser().resolve()
        if not self._path.is_file():
            raise PostSourceError(f"Archivo no encontrado: {self._path}")
        self._plataforma = plataforma
        self._mapping = self._load_mapping(mapping)

    def _load_mapping(self, mapping_path: str | None) -> dict[str, str] | None:
        if mapping_path is None:
            return None
        p = Path(mapping_path).expanduser().resolve()
        try:
            obj = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as e:
            raise PostSourceError(f"Mapping inválido en {p}: {e}") from e
        if not isinstance(obj, dict):
            raise PostSourceError(
                f"El mapping de {p} debe ser un objeto "
                "{campo_normalizado: columna}."
            )
        return {str(k): str(v) for k, v in obj.items()}

    # ── Modos ────────────────────────────────────────────────────────────────

    def search(
        self,
        query: str,
        max_items: int | None = None,
        from_date: date | None = None,
        to_date: date | None = None,
        lang: str | None = None,
    ) -> Iterator[PostRecord]:
        """Itera todos los posts del CSV (los filtros los aplica el CLI)."""
        n = 0
        for record in self._iter_all():
            yield record
            n += 1
            if max_items is not None and n >= max_items:
                return

    def fetch_thread(self, root_id: str) -> Iterator[PostRecord]:
        """Emite los posts del CSV que pertenecen a la conversación."""
        for record in self._iter_all():
            if record.conversacion_id == root_id or record.id == root_id:
                yield record

    def fetch_user(
        self,
        handle: str,
        max_items: int | None = None,
        from_date: date | None = None,
        to_date: date | None = None,
    ) -> Iterator[PostRecord]:
        """Emite los posts del CSV cuyo autor es `handle`."""
        n = 0
        wanted = handle.lstrip("@").lower()
        for record in self._iter_all():
            if record.autor_handle.lstrip("@").lower() != wanted:
                continue
            yield record
            n += 1
            if max_items is not None and n >= max_items:
                return

    # ── Lectura y mapeo ──────────────────────────────────────────────────────

    def _iter_all(self) -> Iterator[PostRecord]:
        try:
            df = pd.read_csv(self._path, encoding="utf-8", dtype=str)
        except (UnicodeDecodeError, pd.errors.EmptyDataError,
                pd.errors.ParserError) as e:
            raise PostSourceError(f"CSV ilegible en {self._path}: {e}") from e

        columns = self._resolve_columns(list(df.columns))
        for row in df.to_dict(orient="records"):
            record = self._map_row(row, columns)
            if record is not None:
                yield record

    def _resolve_columns(self, present: list[str]) -> dict[str, str]:
        """Resuelve campo normalizado → columna presente en el CSV."""
        resolved: dict[str, str] = {}
        if self._mapping is not None:
            for field, column in self._mapping.items():
                if column in present:
                    resolved[field] = column
        else:
            lower = {c.lower(): c for c in present}
            for field, candidates in _DEFAULT_CANDIDATES.items():
                for cand in candidates:
                    if cand in lower:
                        resolved[field] = lower[cand]
                        break
        for required in ("id", "texto", "autor_handle"):
            if required not in resolved:
                raise PostSourceError(
                    f"No encontré columna para '{required}' en {self._path}. "
                    f"Columnas presentes: {present}. Pasá un mapping con "
                    "--mapping (JSON {campo: columna})."
                )
        return resolved

    def _map_row(
        self, row: dict[str, Any], columns: dict[str, str]
    ) -> PostRecord | None:
        def get(field: str) -> str | None:
            column = columns.get(field)
            if column is None:
                return None
            value = row.get(column)
            if value is None or (isinstance(value, float) and pd.isna(value)):
                return None
            s = str(value).strip()
            return s or None

        post_id = get("id")
        texto = get("texto") or ""
        handle = get("autor_handle")
        if not post_id or not handle:
            return None

        reposteo_a = get("reposteo_a")
        cita_a = get("cita_a")
        en_respuesta_a = get("en_respuesta_a")
        if reposteo_a:
            tipo, texto = "repost", ""
        elif en_respuesta_a:
            tipo = "reply"
        elif cita_a:
            tipo = "quote"
        else:
            tipo = "original"

        return PostRecord(
            id=post_id,
            plataforma=self._plataforma,
            autor_handle=handle.lstrip("@"),
            autor_display=get("autor_display"),
            texto=texto,
            fecha=get("fecha"),
            lang=get("lang"),
            tipo=tipo,
            conversacion_id=get("conversacion_id"),
            en_respuesta_a=en_respuesta_a,
            cita_a=cita_a,
            reposteo_a=reposteo_a,
            url=get("url"),
            raw={k: v for k, v in row.items() if v is not None},
        )
