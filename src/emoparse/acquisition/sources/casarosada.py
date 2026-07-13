# ══════════════════════════════════════════════════════════════════════════════
#  emoparse.acquisition.sources.casarosada
#
#  Adapter para casarosada.gob.ar/informacion/discursos.
# ══════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

from collections.abc import Iterator
from datetime import date
from typing import Any, Literal

import requests
from bs4 import BeautifulSoup
from loguru import logger

from emoparse.acquisition.base import DiscursoRecord, SourceAdapter
from emoparse.acquisition.http_client import HttpClient
from emoparse.acquisition.normalize import (
    clean_whitespace,
    normalize_date,
    normalize_url,
    strip_boilerplate,
)


Mode = Literal["http", "selenium", "auto"]


#: Selectores.
_BASE_DOMAIN = "https://www.casarosada.gob.ar"
_LISTING_PATH = "/informacion/discursos"

# Listado: links a discursos individuales.
_LISTING_LINK_SELECTOR = 'a[href*="/informacion/discursos/"]'

# Selectores de la página individual.
_TITULO_SELECTORS = ("article h2", "article h1", "h2.title", "h1.title")
_FECHA_SELECTORS = ("article time", "time")
_CONTENIDO_SELECTOR = "article p"

# Paginación.
_NEXT_LINK_SELECTOR = (
    'li.pagination-next a, a[rel="next"], a.next, '
    'a:-soup-contains("Siguiente")'
)
_NEXT_BUTTON_XPATH = (
    '//li[contains(@class,"pagination-next")]/a | //a[contains(.,"Siguiente")]'
)


class CasaRosadaAdapter(SourceAdapter):
    """Adapter para discursos presidenciales argentinos."""

    source_id = "casarosada"
    requires_selenium = False

    def __init__(
        self,
        *,
        mode: Mode = "auto",
        listing_url: str | None = None,
        timeout: float = 20.0,
        max_retries: int = 3,
    ) -> None:
        """
        Args:
            mode: "http" | "selenium" | "auto" (default).
            listing_url: URL del listado. Default: /informacion/discursos.
            timeout: Timeout por request HTTP en segundos.
            max_retries: Reintentos en errores transitorios.
        """
        self._mode: Mode = mode
        self._listing_url = listing_url or f"{_BASE_DOMAIN}{_LISTING_PATH}"
        self._http = HttpClient(timeout=timeout, max_retries=max_retries)
        self._selenium: Any = None
        self._stuck_on_selenium = (mode == "selenium")

    # ── Listado de URLs ──────────────────────────────────────────────────

    def list_discursos(
        self,
        *,
        max_items: int | None = None,
        from_date: date | None = None,
        to_date: date | None = None,
    ) -> Iterator[str]:
        """Itera URLs de discursos, paginando hasta max_items."""
        seen: set[str] = set()
        emitted = 0
        url = self._listing_url
        page = 1
        max_pages = 200  # Safety net contra loops infinitos.

        while url and page <= max_pages:
            logger.info(f"[CasaRosada] Listado página {page} | acumulados: {emitted}")
            html = self._fetch_html(url)
            if not html:
                break

            soup = BeautifulSoup(html, "lxml")
            new_count = 0
            for a in soup.select(_LISTING_LINK_SELECTOR):
                href = a.get("href", "").strip()
                if not href:
                    continue
                full = normalize_url(href, _BASE_DOMAIN)
                if full.rstrip("/").endswith(_LISTING_PATH.rstrip("/")):
                    continue
                if full in seen:
                    continue
                seen.add(full)
                yield full
                emitted += 1
                new_count += 1
                if max_items is not None and emitted >= max_items:
                    return

            logger.debug(f"[CasaRosada] +{new_count} URLs en pág {page}")

            if new_count == 0:
                logger.info("[CasaRosada] Página sin links nuevos. Fin.")
                break

            next_url = self._find_next_page_url(soup)
            if not next_url:
                logger.info("[CasaRosada] Sin botón 'Siguiente'. Fin.")
                break
            url = normalize_url(next_url, _BASE_DOMAIN)
            page += 1

    def _find_next_page_url(self, soup: BeautifulSoup) -> str | None:
        """Devuelve href del botón 'Siguiente'."""
        a = soup.select_one(_NEXT_LINK_SELECTOR)
        if a and a.get("href"):
            return str(a["href"]).strip()
        return None

    # ── Fetch de un discurso ─────────────────────────────────────────────

    def fetch_discurso(self, url: str) -> DiscursoRecord | None:
        """Descarga y parsea un discurso. None si vacío."""
        html = self._fetch_html(url)
        if not html:
            return None

        soup = BeautifulSoup(html, "lxml")

        titulo = self._select_first_text(soup, _TITULO_SELECTORS) or "Sin título"
        fecha = self._extract_fecha(soup)
        contenido = self._extract_contenido(soup)

        if not contenido or contenido == "[Contenido no encontrado]":
            logger.warning(f"[CasaRosada] Sin contenido en {url}")
            return None

        codigo = self._codigo_from_url(url)

        return DiscursoRecord(
            codigo=codigo,
            url=url,
            titulo=titulo,
            fecha=fecha,
            contenido=contenido,
            fuente=self.source_id,
            extras=(("scrape_mode", self._current_mode_label()),),
        )

    def _extract_fecha(self, soup: BeautifulSoup) -> str:
        """Extrae fecha del discurso, normalizada si posible."""
        for sel in _FECHA_SELECTORS:
            el = soup.select_one(sel)
            if el is None:
                continue
            raw = el.get("datetime") or el.get_text(strip=True)
            if not raw:
                continue
            normalized = normalize_date(raw)
            if normalized:
                return normalized
            return raw
        return ""

    def _extract_contenido(self, soup: BeautifulSoup) -> str:
        """Concatena párrafos, limpia whitespace y boilerplate."""
        parrafos = soup.select(_CONTENIDO_SELECTOR)
        textos = [p.get_text(separator=" ", strip=True) for p in parrafos]
        textos = [t for t in textos if t]
        if not textos:
            return ""
        joined = "\n\n".join(textos)
        joined = clean_whitespace(joined)
        joined = strip_boilerplate(joined)
        return joined

    @staticmethod
    def _select_first_text(soup: BeautifulSoup, selectors: tuple[str, ...]) -> str:
        for sel in selectors:
            el = soup.select_one(sel)
            if el is not None:
                txt = el.get_text(strip=True)
                if txt:
                    return txt
        return ""

    @staticmethod
    def _codigo_from_url(url: str) -> str:
        """Genera código estable a partir del slug de la URL."""
        slug = url.rstrip("/").rsplit("/", 1)[-1]
        # Sanitizar caracteres raros en el slug: solo [\w-].
        import re
        slug = re.sub(r"[^\w\-]", "_", slug)
        return f"casarosada_{slug}" if slug else f"casarosada_{abs(hash(url))}"

    # ── HTTP/Selenium dispatcher ─────────────────────────────────────────

    def _fetch_html(self, url: str) -> str:
        """Devuelve HTML usando HTTP o Selenium según modo."""
        if self._mode == "selenium" or self._stuck_on_selenium:
            return self._fetch_selenium(url)

        if self._mode == "http":
            return self._fetch_http_strict(url)

        # mode == "auto": HTTP con escalada a Selenium.
        try:
            html = self._fetch_http_strict(url)
            if self._is_blocked_response(html):
                logger.warning(
                    f"[CasaRosada] HTTP devolvió respuesta sospechosa para {url}, "
                    f"escalando a Selenium para el resto de la sesión."
                )
                self._stuck_on_selenium = True
                return self._fetch_selenium(url)
            return html
        except (requests.HTTPError, RuntimeError) as e:
            logger.warning(
                f"[CasaRosada] HTTP falló para {url} ({e}), escalando a Selenium."
            )
            self._stuck_on_selenium = True
            return self._fetch_selenium(url)

    def _fetch_http_strict(self, url: str) -> str:
        """HTTP simple. Lanza en 4xx no-retryable."""
        resp = self._http.get(url)
        if resp.status_code >= 400:
            resp.raise_for_status()
        return resp.text

    @staticmethod
    def _is_blocked_response(html: str) -> bool:
        """Detecta respuestas bloqueadas (vacías o challenge)."""
        if not html or len(html) < 200:
            return True
        low = html.lower()
        if "cf-challenge" in low or "checking your browser" in low:
            return True
        if "<title>403" in low or "access denied" in low:
            return True
        return False

    def _fetch_selenium(self, url: str) -> str:
        """Devuelve HTML renderizado vía Selenium."""
        if self._selenium is None:
            from emoparse.acquisition.selenium_client import SeleniumClient
            self._selenium = SeleniumClient(headless=True, page_load_wait=1.5)
            self._selenium.start()
        return self._selenium.get_html(url)

    def _current_mode_label(self) -> str:
        """Etiqueta del modo actual (http/selenium/auto)."""
        if self._mode == "http":
            return "http"
        if self._mode == "selenium" or self._stuck_on_selenium:
            return "selenium"
        return "auto"

    def close(self) -> None:
        """Cierra clientes HTTP y Selenium."""
        self._http.close()
        if self._selenium is not None:
            self._selenium.close()
            self._selenium = None
