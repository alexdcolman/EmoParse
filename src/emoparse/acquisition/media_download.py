# ══════════════════════════════════════════════════════════════════════════════
#  emoparse.acquisition.media_download
#
#  Descarga opcional de media adjunta durante la adquisición (--with-media).
#
#  Solo imágenes, con tope de tamaño y nombres content-addressed (hash de la
#  URL): re-adquirir no re-descarga. La retención de media es responsabilidad
#  del investigador (ver README del paquete: minimización de datos).
# ══════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

import hashlib
from dataclasses import replace
from pathlib import Path

import httpx
from loguru import logger

from emoparse.acquisition.post_record import PostRecord

#: Tope de descarga por archivo.
_MAX_BYTES = 8 * 1024 * 1024

#: Content-types aceptados → extensión.
_IMAGE_TYPES = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "image/gif": ".gif",
}


class MediaDownloader:
    """Descarga las imágenes de un PostRecord a un directorio local."""

    def __init__(self, media_dir: Path | str, timeout: float = 20.0) -> None:
        self._dir = Path(media_dir).expanduser().resolve()
        self._dir.mkdir(parents=True, exist_ok=True)
        self._http = httpx.Client(timeout=timeout, follow_redirects=True)

    def apply(self, record: PostRecord) -> PostRecord:
        """Devuelve el record con `path_local` en cada imagen descargada."""
        if not record.media:
            return record
        media_out = []
        for m in record.media:
            m = dict(m)
            url = m.get("url")
            if m.get("tipo") == "imagen" and url and not m.get("path_local"):
                path = self._download(str(url))
                if path is not None:
                    m["path_local"] = str(path)
            media_out.append(m)
        return replace(record, media=tuple(media_out))

    def _download(self, url: str) -> Path | None:
        """Descarga una imagen (idempotente por hash de URL)."""
        stem = hashlib.sha256(url.encode("utf-8")).hexdigest()[:20]
        for ext in _IMAGE_TYPES.values():
            existente = self._dir / f"{stem}{ext}"
            if existente.is_file():
                return existente
        try:
            resp = self._http.get(url)
            resp.raise_for_status()
        except httpx.HTTPError as e:
            logger.warning(f"[media] No pude descargar {url}: {e}")
            return None
        ctype = resp.headers.get("content-type", "").split(";")[0].strip()
        ext = _IMAGE_TYPES.get(ctype)
        if ext is None:
            logger.debug(f"[media] Content-type no soportado ({ctype}): {url}")
            return None
        if len(resp.content) > _MAX_BYTES:
            logger.warning(f"[media] {url} excede {_MAX_BYTES} bytes; se omite.")
            return None
        path = self._dir / f"{stem}{ext}"
        path.write_bytes(resp.content)
        return path

    def close(self) -> None:
        """Cierra el cliente HTTP."""
        self._http.close()
