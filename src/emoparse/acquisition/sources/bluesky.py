# ══════════════════════════════════════════════════════════════════════════════
#  emoparse.acquisition.sources.bluesky
#
#  Adapter de Bluesky (AT Protocol) para posts.
#
#  Usa el SDK oficial `atproto` (extra `bluesky`). La búsqueda y la lectura de
#  hilos requieren sesión: crear un App Password en la configuración de la
#  cuenta y exponerlo vía BLUESKY_HANDLE / BLUESKY_APP_PASSWORD (o pasarlo por
#  parámetro). Nunca usar la contraseña principal de la cuenta.
# ══════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

import os
from datetime import date
from typing import Any, Iterator

from loguru import logger

from emoparse.acquisition.base_posts import PostSourceAdapter, PostSourceError
from emoparse.acquisition.post_record import PostRecord

#: Tamaño de página de la API (máximo permitido: 100).
_PAGE_SIZE = 100

#: Profundidad máxima pedida al leer un hilo.
_THREAD_DEPTH = 100


class BlueskyAdapter(PostSourceAdapter):
    """Fuente de posts de Bluesky vía AT Protocol."""

    source_id = "bluesky"
    supports_author_profile = True

    def __init__(
        self,
        handle: str | None = None,
        app_password: str | None = None,
        service: str = "https://bsky.social",
    ) -> None:
        try:
            from atproto import Client
        except ImportError as e:
            raise PostSourceError(
                "El SDK atproto no está instalado. "
                'Instalá el extra: pip install -e ".[bluesky]"'
            ) from e

        handle = handle or os.environ.get("BLUESKY_HANDLE")
        app_password = app_password or os.environ.get("BLUESKY_APP_PASSWORD")
        if not handle or not app_password:
            raise PostSourceError(
                "Bluesky requiere sesión: definí BLUESKY_HANDLE y "
                "BLUESKY_APP_PASSWORD (App Password, no la contraseña "
                "principal) o pasalos por parámetro."
            )
        self._client = Client(base_url=service)
        self._client.login(handle, app_password)

    # ── Modos ────────────────────────────────────────────────────────────────

    def search(
        self,
        query: str,
        max_items: int | None = None,
        from_date: date | None = None,
        to_date: date | None = None,
        lang: str | None = None,
    ) -> Iterator[PostRecord]:
        """Itera resultados de app.bsky.feed.searchPosts, paginando."""
        params: dict[str, Any] = {"q": query, "limit": _PAGE_SIZE}
        if from_date:
            params["since"] = from_date.isoformat() + "T00:00:00Z"
        if to_date:
            params["until"] = to_date.isoformat() + "T23:59:59Z"
        if lang:
            params["lang"] = lang

        n = 0
        cursor: str | None = None
        while True:
            if cursor:
                params["cursor"] = cursor
            resp = self._client.app.bsky.feed.search_posts(params=params)
            posts = getattr(resp, "posts", None) or []
            if not posts:
                return
            for post_view in posts:
                record = self._map_post_view(post_view)
                if record is None:
                    continue
                yield record
                n += 1
                if max_items is not None and n >= max_items:
                    return
            cursor = getattr(resp, "cursor", None)
            if not cursor:
                return

    def fetch_thread(self, root_id: str) -> Iterator[PostRecord]:
        """Itera los posts de un hilo (app.bsky.feed.getPostThread).

        `root_id` es la URI AT del post raíz (at://did:plc:.../app.bsky.feed.post/...).
        Recorre recursivamente padres y respuestas hasta la profundidad
        pedida a la API.
        """
        resp = self._client.app.bsky.feed.get_post_thread(
            params={"uri": root_id, "depth": _THREAD_DEPTH, "parent_height": _THREAD_DEPTH}
        )
        thread = getattr(resp, "thread", None)
        yield from self._walk_thread(thread)

    def fetch_user(
        self,
        handle: str,
        max_items: int | None = None,
        from_date: date | None = None,
        to_date: date | None = None,
    ) -> Iterator[PostRecord]:
        """Itera el feed de una cuenta (app.bsky.feed.getAuthorFeed).

        Incluye los reposts de la cuenta como registros de tipo 'repost'
        (texto vacío, `reposteo_a` apuntando al original). El filtro por fecha
        se aplica en el CLI, post-fetch.
        """
        n = 0
        cursor: str | None = None
        while True:
            params: dict[str, Any] = {"actor": handle.lstrip("@"), "limit": _PAGE_SIZE}
            if cursor:
                params["cursor"] = cursor
            resp = self._client.app.bsky.feed.get_author_feed(params=params)
            feed = getattr(resp, "feed", None) or []
            if not feed:
                return
            for item in feed:
                post_view = getattr(item, "post", None)
                reason = getattr(item, "reason", None)
                if reason is not None and _is_repost_reason(reason):
                    record = self._map_repost(post_view, reason, handle)
                else:
                    record = self._map_post_view(post_view)
                if record is None:
                    continue
                yield record
                n += 1
                if max_items is not None and n >= max_items:
                    return
            cursor = getattr(resp, "cursor", None)
            if not cursor:
                return

    def fetch_author_profile(self, handle: str) -> dict[str, Any] | None:
        """Perfil completo del autor vía app.bsky.actor.getProfile (llamada extra, no viene en el PostView)."""
        try:
            profile = self._client.app.bsky.actor.get_profile(params={"actor": handle})
        except Exception as e:
            logger.debug(f"[bluesky] No pude traer el perfil de {handle!r}: {e}")
            return None
        return {
            "autor_bio": _str_or_none(getattr(profile, "description", None)),
            "autor_seguidores": _int_or_none(getattr(profile, "followers_count", None)),
            "autor_siguiendo": _int_or_none(getattr(profile, "follows_count", None)),
            "autor_verificado": _verified_status(getattr(profile, "verification", None)),
        }

    # ── Mapeo AT Protocol → PostRecord ───────────────────────────────────────

    def _walk_thread(self, node: Any) -> Iterator[PostRecord]:
        """Recorre un ThreadViewPost (padre primero, luego respuestas)."""
        if node is None:
            return
        parent = getattr(node, "parent", None)
        if parent is not None:
            yield from self._walk_thread(parent)
        post_view = getattr(node, "post", None)
        record = self._map_post_view(post_view)
        if record is not None:
            yield record
        for reply in getattr(node, "replies", None) or []:
            yield from self._walk_reply(reply)

    def _walk_reply(self, node: Any) -> Iterator[PostRecord]:
        """Recorre solo hacia abajo (las respuestas ya tienen el padre arriba)."""
        if node is None:
            return
        record = self._map_post_view(getattr(node, "post", None))
        if record is not None:
            yield record
        for reply in getattr(node, "replies", None) or []:
            yield from self._walk_reply(reply)

    def _map_post_view(self, post_view: Any) -> PostRecord | None:
        """Mapea un PostView de la API a PostRecord."""
        if post_view is None:
            return None
        uri = getattr(post_view, "uri", None)
        record_obj = getattr(post_view, "record", None)
        author = getattr(post_view, "author", None)
        if not uri or record_obj is None or author is None:
            logger.debug("[bluesky] PostView incompleto, lo salteo.")
            return None

        texto = str(getattr(record_obj, "text", "") or "")
        handle = str(getattr(author, "handle", "") or "")

        reply_ref = getattr(record_obj, "reply", None)
        en_respuesta_a = _ref_uri(getattr(reply_ref, "parent", None))
        conversacion_id = _ref_uri(getattr(reply_ref, "root", None))

        cita_a = _quoted_uri(getattr(record_obj, "embed", None))
        tipo = "reply" if en_respuesta_a else ("quote" if cita_a else "original")

        langs = getattr(record_obj, "langs", None) or []
        media = tuple(_map_images(getattr(post_view, "embed", None)))

        return PostRecord(
            id=str(uri),
            plataforma="bluesky",
            autor_handle=handle,
            autor_display=_str_or_none(getattr(author, "display_name", None)),
            texto=texto,
            fecha=_str_or_none(getattr(record_obj, "created_at", None)),
            lang=str(langs[0]) if langs else None,
            tipo=tipo,
            conversacion_id=conversacion_id,
            en_respuesta_a=en_respuesta_a,
            cita_a=cita_a,
            url=_web_url(str(uri), handle),
            metricas={
                "likes": int(getattr(post_view, "like_count", 0) or 0),
                "reposts": int(getattr(post_view, "repost_count", 0) or 0),
                "replies": int(getattr(post_view, "reply_count", 0) or 0),
                "quotes": int(getattr(post_view, "quote_count", 0) or 0),
            },
            media=media,
            raw=_raw_dict(post_view),
        )

    def _map_repost(
        self, post_view: Any, reason: Any, reposter_handle: str
    ) -> PostRecord | None:
        """Mapea un repost del feed de un autor a un registro de circulación."""
        original_uri = getattr(post_view, "uri", None)
        if not original_uri:
            return None
        indexed_at = _str_or_none(getattr(reason, "indexed_at", None))
        handle = reposter_handle.lstrip("@")
        return PostRecord(
            id=f"repost:{handle}:{original_uri}",
            plataforma="bluesky",
            autor_handle=handle,
            texto="",
            fecha=indexed_at,
            tipo="repost",
            reposteo_a=str(original_uri),
        )


# ══════════════════════════════════════════════════════════════════════════════
#  Helpers de mapeo
# ══════════════════════════════════════════════════════════════════════════════

def _str_or_none(value: Any) -> str | None:
    """String no vacío o None."""
    s = str(value).strip() if value is not None else ""
    return s or None


def _int_or_none(value: Any) -> int | None:
    """Entero o None, tolerante a tipos raros del SDK."""
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _verified_status(verification: Any) -> bool | None:
    """True/False si el perfil trae `verification.verifiedStatus`, None si el SDK no lo expone."""
    if verification is None:
        return None
    status = getattr(verification, "verified_status", None)
    if status is None:
        return None
    return str(status) == "valid"


def _raw_dict(obj: Any) -> dict[str, Any] | None:
    """Serializa el objeto crudo del SDK para auditoría/reprocesamiento."""
    if obj is None:
        return None
    for method in ("model_dump", "dict"):
        dump = getattr(obj, method, None)
        if callable(dump):
            try:
                return dump(mode="json") if method == "model_dump" else dump()
            except TypeError:
                try:
                    return dump()
                except Exception:
                    continue
            except Exception:
                continue
    return None


def _ref_uri(ref: Any) -> str | None:
    """URI de una referencia strongRef (reply.parent / reply.root)."""
    if ref is None:
        return None
    return _str_or_none(getattr(ref, "uri", None))


def _quoted_uri(embed: Any) -> str | None:
    """URI del post citado, si el embed es un record (quote post)."""
    if embed is None:
        return None
    # app.bsky.embed.record → embed.record.uri
    rec = getattr(embed, "record", None)
    uri = getattr(rec, "uri", None) if rec is not None else None
    if uri:
        return str(uri)
    # app.bsky.embed.recordWithMedia → embed.record.record.uri
    inner = getattr(rec, "record", None) if rec is not None else None
    uri = getattr(inner, "uri", None) if inner is not None else None
    return str(uri) if uri else None


def _map_images(embed_view: Any) -> list[dict[str, Any]]:
    """Extrae imágenes del embed hidratado del PostView."""
    if embed_view is None:
        return []
    images = getattr(embed_view, "images", None)
    if images is None:
        media_part = getattr(embed_view, "media", None)
        images = getattr(media_part, "images", None) if media_part is not None else None
    result: list[dict[str, Any]] = []
    for img in images or []:
        result.append({
            "tipo": "imagen",
            "url": _str_or_none(getattr(img, "fullsize", None)),
            "alt": _str_or_none(getattr(img, "alt", None)),
        })
    return result


def _is_repost_reason(reason: Any) -> bool:
    """True si el reason del feed item es un repost."""
    py_type = str(getattr(reason, "py_type", "") or type(reason).__name__)
    return "reasonRepost" in py_type or "ReasonRepost" in py_type


def _web_url(uri: str, handle: str) -> str | None:
    """URL web del post a partir de la URI AT."""
    rkey = uri.rsplit("/", 1)[-1] if "/" in uri else ""
    if not rkey or not handle:
        return None
    return f"https://bsky.app/profile/{handle}/post/{rkey}"
