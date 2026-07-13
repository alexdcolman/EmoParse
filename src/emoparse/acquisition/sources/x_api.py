# ══════════════════════════════════════════════════════════════════════════════
#  emoparse.acquisition.sources.x_api
#
#  Adapter de la API oficial de X (v2) para posts.
#
#  Requiere un Bearer Token de un proyecto con tier de lectura (el tier
#  gratuito es solo de escritura). La búsqueda usa /2/tweets/search/recent
#  (últimos 7 días); el archivo completo (/search/all) solo está disponible
#  en los tiers superiores y se habilita con `archive=True`. No usa
#  dependencias extra: el cliente HTTP es httpx (dependencia core).
# ══════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

import os
import time
from datetime import date
from typing import Any, Iterator

import httpx
from loguru import logger

from emoparse.acquisition.base_posts import PostSourceAdapter, PostSourceError
from emoparse.acquisition.post_record import PostRecord

_BASE = "https://api.x.com/2"

#: Campos y expansiones pedidos en cada request.
_TWEET_FIELDS = (
    "id,text,author_id,created_at,lang,conversation_id,"
    "public_metrics,referenced_tweets,entities,attachments"
)
_USER_FIELDS = "id,username,name,description,verified,public_metrics"
_MEDIA_FIELDS = "media_key,type,url,preview_image_url,alt_text"
_EXPANSIONS = (
    "author_id,referenced_tweets.id,referenced_tweets.id.author_id,"
    "attachments.media_keys"
)

#: Máximo de resultados por página que acepta la API de búsqueda.
_PAGE_SIZE = 100


class XApiAdapter(PostSourceAdapter):
    """Fuente de posts de X vía API oficial v2."""

    source_id = "x_api"

    def __init__(
        self,
        bearer_token: str | None = None,
        archive: bool = False,
        timeout: float = 20.0,
    ) -> None:
        token = bearer_token or os.environ.get("X_BEARER_TOKEN")
        if not token:
            raise PostSourceError(
                "La API de X requiere un Bearer Token: definí X_BEARER_TOKEN "
                "o pasalo por parámetro."
            )
        self._archive = archive
        self._http = httpx.Client(
            timeout=timeout,
            headers={"Authorization": f"Bearer {token}"},
        )

    def close(self) -> None:
        """Cierra el cliente HTTP."""
        self._http.close()

    # ── Modos ────────────────────────────────────────────────────────────────

    def search(
        self,
        query: str,
        max_items: int | None = None,
        from_date: date | None = None,
        to_date: date | None = None,
        lang: str | None = None,
    ) -> Iterator[PostRecord]:
        """Itera resultados de búsqueda, paginando por next_token."""
        q = query if not lang else f"({query}) lang:{lang}"
        params: dict[str, Any] = {"query": q, "max_results": _PAGE_SIZE}
        if from_date:
            params["start_time"] = from_date.isoformat() + "T00:00:00Z"
        if to_date:
            params["end_time"] = to_date.isoformat() + "T23:59:59Z"
        endpoint = "/tweets/search/all" if self._archive else "/tweets/search/recent"
        yield from self._paginate(endpoint, params, max_items)

    def fetch_thread(self, root_id: str) -> Iterator[PostRecord]:
        """Itera los posts de una conversación por conversation_id.

        Con el endpoint /search/recent solo recupera la conversación si sus
        posts están dentro de la ventana de 7 días; para hilos más viejos se
        necesita `archive=True` (tier con acceso a /search/all).
        """
        params = {"query": f"conversation_id:{root_id}", "max_results": _PAGE_SIZE}
        endpoint = "/tweets/search/all" if self._archive else "/tweets/search/recent"
        # La búsqueda por conversation_id no devuelve la raíz: pedirla aparte.
        yield from self._fetch_by_ids([root_id])
        yield from self._paginate(endpoint, params, max_items=None)

    def fetch_user(
        self,
        handle: str,
        max_items: int | None = None,
        from_date: date | None = None,
        to_date: date | None = None,
    ) -> Iterator[PostRecord]:
        """Itera la timeline de una cuenta (/2/users/:id/tweets)."""
        user_id = self._resolve_user_id(handle)
        params: dict[str, Any] = {"max_results": _PAGE_SIZE}
        if from_date:
            params["start_time"] = from_date.isoformat() + "T00:00:00Z"
        if to_date:
            params["end_time"] = to_date.isoformat() + "T23:59:59Z"
        yield from self._paginate(f"/users/{user_id}/tweets", params, max_items)

    # ── HTTP + paginación ────────────────────────────────────────────────────

    def _get(self, endpoint: str, params: dict[str, Any]) -> dict[str, Any]:
        """GET con los fields/expansions estándar y manejo de rate limit."""
        full = dict(params)
        full.update({
            "tweet.fields": _TWEET_FIELDS,
            "user.fields": _USER_FIELDS,
            "media.fields": _MEDIA_FIELDS,
            "expansions": _EXPANSIONS,
        })
        while True:
            resp = self._http.get(_BASE + endpoint, params=full)
            if resp.status_code == 429:
                reset = resp.headers.get("x-rate-limit-reset")
                wait = max(5.0, float(reset) - time.time()) if reset else 60.0
                logger.warning(
                    f"[x_api] Rate limit; espero {wait:.0f}s antes de reintentar."
                )
                time.sleep(min(wait, 900.0))
                continue
            if resp.status_code in (401, 403):
                raise PostSourceError(
                    f"[x_api] Acceso denegado ({resp.status_code}): verificá "
                    "el token y el tier del proyecto. "
                    f"Detalle: {resp.text[:200]}"
                )
            resp.raise_for_status()
            return resp.json()

    def _paginate(
        self,
        endpoint: str,
        params: dict[str, Any],
        max_items: int | None,
    ) -> Iterator[PostRecord]:
        n = 0
        next_token: str | None = None
        while True:
            page = dict(params)
            if next_token:
                page["next_token" if "search" in endpoint else "pagination_token"] = next_token
            payload = self._get(endpoint, page)
            data = payload.get("data") or []
            includes = payload.get("includes") or {}
            if not data:
                return
            for tweet in data:
                yield map_v2_tweet(tweet, includes)
                n += 1
                if max_items is not None and n >= max_items:
                    return
            next_token = (payload.get("meta") or {}).get("next_token")
            if not next_token:
                return

    def _fetch_by_ids(self, ids: list[str]) -> Iterator[PostRecord]:
        """Recupera posts puntuales por id (/2/tweets?ids=...)."""
        payload = self._get("/tweets", {"ids": ",".join(ids)})
        includes = payload.get("includes") or {}
        for tweet in payload.get("data") or []:
            yield map_v2_tweet(tweet, includes)

    def _resolve_user_id(self, handle: str) -> str:
        payload = self._get(f"/users/by/username/{handle.lstrip('@')}", {})
        data = payload.get("data") or {}
        user_id = data.get("id")
        if not user_id:
            raise PostSourceError(f"[x_api] Cuenta no encontrada: {handle}")
        return str(user_id)


# ══════════════════════════════════════════════════════════════════════════════
#  Mapeo tweet v2 → PostRecord (compartido con jsonl_import)
# ══════════════════════════════════════════════════════════════════════════════

def map_v2_tweet(
    tweet: dict[str, Any],
    includes: dict[str, Any] | None = None,
) -> PostRecord:
    """Mapea un objeto tweet del formato API v2 a PostRecord.

    `includes` (users/media/tweets expandidos) es opcional: sin él, el handle
    cae al author_id y los adjuntos quedan sin URL.
    """
    includes = includes or {}
    users = {u.get("id"): u for u in includes.get("users") or []}
    media_by_key = {m.get("media_key"): m for m in includes.get("media") or []}

    author = users.get(tweet.get("author_id")) or {}
    handle = str(author.get("username") or tweet.get("author_id") or "")

    en_respuesta_a = cita_a = reposteo_a = None
    for ref in tweet.get("referenced_tweets") or []:
        ref_type, ref_id = ref.get("type"), str(ref.get("id") or "")
        if ref_type == "replied_to":
            en_respuesta_a = ref_id
        elif ref_type == "quoted":
            cita_a = ref_id
        elif ref_type == "retweeted":
            reposteo_a = ref_id

    if reposteo_a:
        tipo = "repost"
        texto = ""  # el "RT @...: ..." no es texto propio; el crudo queda en raw
    elif en_respuesta_a:
        tipo, texto = "reply", str(tweet.get("text") or "")
    elif cita_a:
        tipo, texto = "quote", str(tweet.get("text") or "")
    else:
        tipo, texto = "original", str(tweet.get("text") or "")

    media = []
    for key in (tweet.get("attachments") or {}).get("media_keys") or []:
        m = media_by_key.get(key) or {}
        media.append({
            "tipo": {"photo": "imagen", "video": "video", "animated_gif": "gif"}.get(
                str(m.get("type")), "otro"
            ),
            "url": m.get("url") or m.get("preview_image_url"),
            "alt": m.get("alt_text"),
        })

    metrics = tweet.get("public_metrics") or {}
    tweet_id = str(tweet.get("id") or "")
    user_metrics = author.get("public_metrics") or {}

    return PostRecord(
        id=tweet_id,
        plataforma="x",
        autor_handle=handle,
        autor_display=author.get("name"),
        autor_bio=author.get("description"),
        autor_seguidores=user_metrics.get("followers_count"),
        autor_siguiendo=user_metrics.get("following_count"),
        autor_verificado=author.get("verified"),
        texto=texto,
        fecha=tweet.get("created_at"),
        lang=tweet.get("lang"),
        tipo=tipo,
        conversacion_id=str(tweet.get("conversation_id") or "") or None,
        en_respuesta_a=en_respuesta_a,
        cita_a=cita_a,
        reposteo_a=reposteo_a,
        url=f"https://x.com/{handle}/status/{tweet_id}" if handle and tweet_id else None,
        metricas={
            "likes": metrics.get("like_count", 0),
            "reposts": metrics.get("retweet_count", 0),
            "replies": metrics.get("reply_count", 0),
            "quotes": metrics.get("quote_count", 0),
            "views": metrics.get("impression_count"),
        },
        media=tuple(media),
        raw=tweet,
    )
