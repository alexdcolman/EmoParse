# ══════════════════════════════════════════════════════════════════════════════
#  emoparse.acquisition.sources.mastodon
#
#  Adapter de Mastodon para posts.
#
#  Usa la API pública de la instancia: las timelines de hashtag
#  (/api/v1/timelines/tag/<tag>), los hilos (/api/v1/statuses/<id>/context) y
#  los perfiles no requieren autenticación para contenido público en la
#  mayoría de las instancias. La búsqueda de texto libre (/api/v2/search con
#  type=statuses) sí suele exigir sesión: si la instancia la rechaza, definí
#  MASTODON_ACCESS_TOKEN (token de aplicación de solo lectura) o buscá por
#  hashtag. La instancia se elige con el parámetro `instance` o la variable
#  MASTODON_INSTANCE (default: https://mastodon.social). No usa dependencias
#  extra: el cliente HTTP es httpx (dependencia core).
# ══════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

import os
import time
from datetime import date, datetime, timezone
from html.parser import HTMLParser
from typing import Any, Iterator
from urllib.parse import urlparse

import httpx
from loguru import logger

from emoparse.acquisition.base_posts import PostSourceAdapter, PostSourceError
from emoparse.acquisition.post_record import PostRecord

#: Tamaño de página de las timelines y la búsqueda (máximo permitido: 40).
_PAGE_SIZE = 40

#: Tope de espera ante rate limit, en segundos.
_MAX_RATE_WAIT = 900.0


class MastodonAdapter(PostSourceAdapter):
    """Fuente de posts de Mastodon vía la API pública de una instancia."""

    source_id = "mastodon"
    supports_author_profile = True

    def __init__(
        self,
        instance: str | None = None,
        access_token: str | None = None,
        timeout: float = 20.0,
    ) -> None:
        base = (
            instance
            or os.environ.get("MASTODON_INSTANCE")
            or "https://mastodon.social"
        ).strip().rstrip("/")
        if not base.startswith(("http://", "https://")):
            base = "https://" + base
        self._base = base
        self._host = urlparse(base).netloc
        token = access_token or os.environ.get("MASTODON_ACCESS_TOKEN")
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        self._http = httpx.Client(timeout=timeout, headers=headers)

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
        """Itera posts públicos que matchean una búsqueda.

        Las queries de hashtag ('#tag') usan la timeline pública del hashtag;
        las de texto libre usan /api/v2/search (type=statuses), que muchas
        instancias restringen a sesiones autenticadas. Los filtros de fecha e
        idioma se aplican del lado del cliente (la API pública no los
        expone); en la timeline de hashtag, `from_date` corta el recorrido al
        cruzar la fecha (el orden es cronológico inverso).
        """
        q = query.strip()
        if q.startswith("#"):
            yield from self._search_tag(
                q.lstrip("#"), max_items, from_date, to_date, lang
            )
        else:
            yield from self._search_statuses(
                q, max_items, from_date, to_date, lang
            )

    def fetch_thread(self, root_id: str) -> Iterator[PostRecord]:
        """Itera los posts de un hilo (status + su contexto).

        `root_id` es el id del status en la instancia configurada. La API
        devuelve ancestros y descendientes completos del status pedido, así
        que sirve cualquier post del hilo como punto de entrada.
        """
        status = self._get(f"/api/v1/statuses/{root_id}", {})
        context = self._get(f"/api/v1/statuses/{root_id}/context", {})
        ancestros = context.get("ancestors") or [] if isinstance(context, dict) else []
        descendientes = context.get("descendants") or [] if isinstance(context, dict) else []
        for s in [*ancestros, status, *descendientes]:
            record = self._map_status(s)
            if record is not None:
                yield record

    def fetch_user(
        self,
        handle: str,
        max_items: int | None = None,
        from_date: date | None = None,
        to_date: date | None = None,
    ) -> Iterator[PostRecord]:
        """Itera los posts públicos de una cuenta (/api/v1/accounts/:id/statuses).

        Incluye los boosts de la cuenta como registros de tipo 'repost'
        (texto vacío, `reposteo_a` apuntando al original). El filtro por
        fecha se aplica en el CLI, post-fetch.
        """
        cuenta = self._lookup_account(handle)
        account_id = str(cuenta.get("id"))
        n = 0
        max_id: str | None = None
        while True:
            params: dict[str, Any] = {"limit": _PAGE_SIZE}
            if max_id:
                params["max_id"] = max_id
            statuses = self._get(f"/api/v1/accounts/{account_id}/statuses", params)
            if not isinstance(statuses, list) or not statuses:
                return
            for s in statuses:
                record = self._map_status(s)
                if record is None:
                    continue
                yield record
                n += 1
                if max_items is not None and n >= max_items:
                    return
            max_id = _str_or_none((statuses[-1] or {}).get("id"))
            if not max_id:
                return

    def fetch_author_profile(self, handle: str) -> dict[str, Any] | None:
        """Perfil completo del autor vía /api/v1/accounts/lookup (llamada extra)."""
        try:
            cuenta = self._lookup_account(handle)
        except Exception as e:
            logger.debug(f"[mastodon] No pude traer el perfil de {handle!r}: {e}")
            return None
        return {
            "autor_bio": _str_or_none(_html_to_text(str(cuenta.get("note") or ""))),
            "autor_seguidores": _int_or_none(cuenta.get("followers_count")),
            "autor_siguiendo": _int_or_none(cuenta.get("following_count")),
            # Mastodon no tiene verificación de plataforma (solo verificación
            # de links por rel=me, que no equivale a una insignia).
            "autor_verificado": None,
        }

    # ── Búsqueda ─────────────────────────────────────────────────────────────

    def _search_tag(
        self,
        tag: str,
        max_items: int | None,
        from_date: date | None,
        to_date: date | None,
        lang: str | None,
    ) -> Iterator[PostRecord]:
        """Itera la timeline pública de un hashtag, paginando por max_id."""
        n = 0
        max_id: str | None = None
        while True:
            params: dict[str, Any] = {"limit": _PAGE_SIZE}
            if max_id:
                params["max_id"] = max_id
            statuses = self._get(f"/api/v1/timelines/tag/{tag}", params)
            if not isinstance(statuses, list) or not statuses:
                return
            for s in statuses:
                fecha = _fecha_date((s or {}).get("created_at"))
                if from_date and fecha and fecha < from_date:
                    # Timeline cronológica inversa: de acá hacia atrás todo
                    # es anterior al rango pedido.
                    return
                if to_date and fecha and fecha > to_date:
                    continue
                if lang and str((s or {}).get("language") or "") != lang:
                    continue
                record = self._map_status(s)
                if record is None:
                    continue
                yield record
                n += 1
                if max_items is not None and n >= max_items:
                    return
            max_id = _str_or_none((statuses[-1] or {}).get("id"))
            if not max_id:
                return

    def _search_statuses(
        self,
        query: str,
        max_items: int | None,
        from_date: date | None,
        to_date: date | None,
        lang: str | None,
    ) -> Iterator[PostRecord]:
        """Itera /api/v2/search (type=statuses), paginando por offset.

        El orden de los resultados no está garantizado como cronológico, así
        que los filtros de fecha descartan sin cortar el recorrido.
        """
        n = 0
        offset = 0
        while True:
            payload = self._get(
                "/api/v2/search",
                {
                    "q": query,
                    "type": "statuses",
                    "limit": _PAGE_SIZE,
                    "offset": offset,
                },
            )
            statuses = payload.get("statuses") or [] if isinstance(payload, dict) else []
            if not statuses:
                return
            offset += len(statuses)
            for s in statuses:
                fecha = _fecha_date((s or {}).get("created_at"))
                if from_date and fecha and fecha < from_date:
                    continue
                if to_date and fecha and fecha > to_date:
                    continue
                if lang and str((s or {}).get("language") or "") != lang:
                    continue
                record = self._map_status(s)
                if record is None:
                    continue
                yield record
                n += 1
                if max_items is not None and n >= max_items:
                    return

    # ── HTTP ─────────────────────────────────────────────────────────────────

    def _get(self, endpoint: str, params: dict[str, Any]) -> Any:
        """GET con manejo de rate limit (429 → espera y reintento)."""
        while True:
            resp = self._http.get(self._base + endpoint, params=params)
            if resp.status_code == 429:
                wait = _rate_limit_wait(resp.headers.get("X-RateLimit-Reset"))
                logger.warning(
                    f"[mastodon] Rate limit en {self._host}; espero "
                    f"{wait:.0f}s antes de reintentar."
                )
                time.sleep(min(wait, _MAX_RATE_WAIT))
                continue
            if resp.status_code in (401, 403):
                raise PostSourceError(
                    f"[mastodon] Acceso denegado ({resp.status_code}) en "
                    f"{self._host}{endpoint}: la instancia exige sesión para "
                    "esta operación (la búsqueda de texto libre suele "
                    "requerirla). Definí MASTODON_ACCESS_TOKEN o buscá por "
                    f"hashtag. Detalle: {resp.text[:200]}"
                )
            resp.raise_for_status()
            return resp.json()

    def _lookup_account(self, handle: str) -> dict[str, Any]:
        """Resuelve un handle a su cuenta (/api/v1/accounts/lookup)."""
        acct = handle.lstrip("@").strip()
        try:
            payload = self._get("/api/v1/accounts/lookup", {"acct": acct})
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                raise PostSourceError(
                    f"[mastodon] Cuenta no encontrada en {self._host}: {handle}"
                ) from e
            raise
        if not isinstance(payload, dict) or not payload.get("id"):
            raise PostSourceError(
                f"[mastodon] Cuenta no encontrada en {self._host}: {handle}"
            )
        return payload

    # ── Mapeo status → PostRecord ────────────────────────────────────────────

    def _map_status(self, status: Any) -> PostRecord | None:
        """Mapea un status de la API a PostRecord."""
        if not isinstance(status, dict):
            return None
        status_id = _str_or_none(status.get("id"))
        cuenta = status.get("account") or {}
        handle = self._qualify_handle(str(cuenta.get("acct") or ""))
        if not status_id or not handle:
            logger.debug("[mastodon] Status incompleto, lo salteo.")
            return None

        reblog = status.get("reblog")
        if isinstance(reblog, dict) and reblog.get("id"):
            # Boost: registro de circulación sin texto propio.
            return PostRecord(
                id=status_id,
                plataforma="mastodon",
                autor_handle=handle,
                texto="",
                fecha=_str_or_none(status.get("created_at")),
                tipo="repost",
                reposteo_a=str(reblog["id"]),
            )

        texto = _html_to_text(str(status.get("content") or ""))
        en_respuesta_a = _str_or_none(status.get("in_reply_to_id"))
        tipo = "reply" if en_respuesta_a else "original"
        media = tuple(_map_attachments(status.get("media_attachments")))

        return PostRecord(
            id=status_id,
            plataforma="mastodon",
            autor_handle=handle,
            autor_display=_str_or_none(cuenta.get("display_name")),
            texto=texto,
            fecha=_str_or_none(status.get("created_at")),
            lang=_str_or_none(status.get("language")),
            tipo=tipo,
            # La API pública no expone la raíz de la conversación; la
            # reconstruye thread_builder a partir de en_respuesta_a.
            conversacion_id=None,
            en_respuesta_a=en_respuesta_a,
            # Mastodon no tiene citas nativas.
            cita_a=None,
            url=_str_or_none(status.get("url")),
            metricas={
                "likes": int(status.get("favourites_count") or 0),
                "reposts": int(status.get("reblogs_count") or 0),
                "replies": int(status.get("replies_count") or 0),
            },
            media=media,
            raw=status,
        )

    def _qualify_handle(self, acct: str) -> str:
        """Handle global usuario@dominio.

        Los `acct` de cuentas locales de la instancia vienen sin dominio; se
        les agrega el host para que no colisionen entre instancias en un
        corpus mixto (las cuentas remotas ya vienen calificadas).
        """
        acct = acct.lstrip("@").strip()
        if not acct or "@" in acct:
            return acct
        return f"{acct}@{self._host}"


# ══════════════════════════════════════════════════════════════════════════════
#  Helpers de mapeo
# ══════════════════════════════════════════════════════════════════════════════

class _HtmlText(HTMLParser):
    """Extrae el texto plano del HTML de un status (párrafos y br → saltos)."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "br":
            self._parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag == "p":
            self._parts.append("\n")

    def text(self) -> str:
        return "".join(self._parts).strip()

    def handle_data(self, data: str) -> None:
        self._parts.append(data)


def _html_to_text(html: str) -> str:
    """Texto plano del `content` HTML de Mastodon."""
    if not html:
        return ""
    parser = _HtmlText()
    parser.feed(html)
    parser.close()
    return parser.text()


def _str_or_none(value: Any) -> str | None:
    """String no vacío o None."""
    s = str(value).strip() if value is not None else ""
    return s or None


def _int_or_none(value: Any) -> int | None:
    """Entero o None, tolerante a tipos raros de la API."""
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _fecha_date(value: Any) -> date | None:
    """Fecha (date) de un created_at ISO-8601, None si no parsea."""
    s = str(value or "").strip()
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).date()
    except ValueError:
        return None


def _rate_limit_wait(reset_header: str | None) -> float:
    """Segundos a esperar según X-RateLimit-Reset (epoch o ISO-8601)."""
    if not reset_header:
        return 60.0
    try:
        return max(5.0, float(reset_header) - time.time())
    except ValueError:
        pass
    try:
        dt = datetime.fromisoformat(reset_header.replace("Z", "+00:00"))
        return max(5.0, (dt - datetime.now(timezone.utc)).total_seconds())
    except ValueError:
        return 60.0


def _map_attachments(attachments: Any) -> list[dict[str, Any]]:
    """Extrae los adjuntos de un status al formato de media normalizado."""
    result: list[dict[str, Any]] = []
    for m in attachments or []:
        if not isinstance(m, dict):
            continue
        tipo = {"image": "imagen", "video": "video", "gifv": "gif"}.get(
            str(m.get("type")), "otro"
        )
        result.append({
            "tipo": tipo,
            "url": _str_or_none(m.get("url") or m.get("preview_url")),
            "alt": _str_or_none(m.get("description")),
        })
    return result
