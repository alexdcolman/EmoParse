# ══════════════════════════════════════════════════════════════════════════════
#  emoparse.acquisition.sources.pagina12
#
#  Adapter HTTP para artículos periodísticos de pagina12.com.ar.
# ══════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

import hashlib
import json
import re
import time
import unicodedata
from collections.abc import Iterable, Iterator
from datetime import date
from email.utils import parsedate_to_datetime
from itertools import zip_longest
from typing import TYPE_CHECKING, Any, Literal
from urllib.parse import urlparse
from xml.etree import ElementTree

import requests
from loguru import logger

from emoparse.acquisition.base import DiscursoRecord, SourceAdapter
from emoparse.acquisition.http_client import HttpClient, TransientHttpError
from emoparse.acquisition.normalize import clean_whitespace, normalize_date, strip_boilerplate

if TYPE_CHECKING:
    from bs4 import BeautifulSoup, Tag


Mode = Literal["http", "auto", "selenium"]

_BASE_DOMAIN = "https://www.pagina12.com.ar"
_SITEMAP_URL = f"{_BASE_DOMAIN}/arc/outboundfeeds/breakingnews-sitemap.xml"
_RSS_SECTIONS: dict[str, str] = {
    "el-pais": f"{_BASE_DOMAIN}/arc/outboundfeeds/rss/secciones/el-pais/notas",
    "economia": f"{_BASE_DOMAIN}/arc/outboundfeeds/rss/secciones/economia/notas",
    "sociedad": f"{_BASE_DOMAIN}/arc/outboundfeeds/rss/secciones/sociedad/notas",
    "el-mundo": f"{_BASE_DOMAIN}/arc/outboundfeeds/rss/secciones/el-mundo/notas",
    "deportes": f"{_BASE_DOMAIN}/arc/outboundfeeds/rss/secciones/deportes/notas",
    "cultura": f"{_BASE_DOMAIN}/arc/outboundfeeds/rss/suplementos/cultura-y-espectaculos/notas",
    "universidad": f"{_BASE_DOMAIN}/arc/outboundfeeds/rss/secciones/universidad/notas",
    "ciencia": f"{_BASE_DOMAIN}/arc/outboundfeeds/rss/secciones/ciencia/notas",
    "psicologia": f"{_BASE_DOMAIN}/arc/outboundfeeds/rss/secciones/psicologia/notas",
    "ajedrez": f"{_BASE_DOMAIN}/arc/outboundfeeds/rss/secciones/ajedrez/notas",
    "la-ventana": f"{_BASE_DOMAIN}/arc/outboundfeeds/rss/secciones/la-ventana/notas",
    "dialogos": f"{_BASE_DOMAIN}/arc/outboundfeeds/rss/secciones/dialogos/notas",
    "hoy": f"{_BASE_DOMAIN}/arc/outboundfeeds/rss/secciones/hoy/notas",
    "plastica": f"{_BASE_DOMAIN}/arc/outboundfeeds/rss/secciones/plastica/notas",
    "cartas-de-lectores": (
        f"{_BASE_DOMAIN}/arc/outboundfeeds/rss/secciones/cartas-de-lectores/notas"
    ),
}
_SECTION_DISPLAY_NAMES: dict[str, str] = {
    "el-pais": "El País",
    "economia": "Economía",
    "sociedad": "Sociedad",
    "el-mundo": "El Mundo",
    "deportes": "Deportes",
    "cultura": "Cultura",
    "universidad": "Universidad",
    "ciencia": "Ciencia",
    "psicologia": "Psicología",
    "ajedrez": "Ajedrez",
    "la-ventana": "La Ventana",
    "dialogos": "Diálogos",
    "hoy": "Hoy",
    "plastica": "Plástica",
    "cartas-de-lectores": "Cartas de Lectores",
}
_RSS_FEED_LABELS: dict[str, str] = {
    **_SECTION_DISPLAY_NAMES,
    # Página/12 presenta esta zona al lector como "Cultura", pero su RSS
    # activo está publicado en el catálogo oficial con la etiqueta "Espectáculos".
    "cultura": "Espectáculos",
}

_DEFAULT_RSS_SECTIONS: tuple[str, ...] = (
    "el-pais",
    "economia",
    "sociedad",
    "deportes",
    "el-mundo",
    "cultura",
)
_SECTION_ALIASES: dict[str, str] = {
    "pais": "el-pais",
    "el-pais": "el-pais",
    "mundo": "el-mundo",
    "el-mundo": "el-mundo",
    "economia": "economia",
    "sociedad": "sociedad",
    "deportes": "deportes",
    "cultura": "cultura",
    "espectaculos": "cultura",
    "cultura-y-espectaculos": "cultura",
    "universidad": "universidad",
    "ciencia": "ciencia",
    "psicologia": "psicologia",
    "ajedrez": "ajedrez",
    "la-ventana": "la-ventana",
    "dialogos": "dialogos",
    "hoy": "hoy",
    "plastica": "plastica",
    "cartas-de-lectores": "cartas-de-lectores",
    "cartas": "cartas-de-lectores",
}

_ARTICLE_SUBTYPES: tuple[str, ...] = ("static", "lbp_article")
_ARTICLE_SUBTYPE_ALIASES: dict[str, str] = {
    "static": "static",
    "estatico": "static",
    "estática": "static",
    "estatica": "static",
    "convencional": "static",
    "article": "static",
    "lbp": "lbp_article",
    "lbp-article": "lbp_article",
    "lbp_article": "lbp_article",
    "live": "lbp_article",
    "live-blog": "lbp_article",
}

_DATED_ARTICLE_URL_RE = re.compile(r"/\d{4}/\d{2}/\d{2}/[^/]+/?$")
_LEGACY_ARTICLE_URL_RE = re.compile(r"/\d{5,}-[^/]+/?$")
_URL_DATE_RE = re.compile(r"/(\d{4})/(\d{2})/(\d{2})/")
_FUSION_GLOBAL_CONTENT_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"(?:window\.)?Fusion\.globalContent\s*=\s*"),
    re.compile(r"(?:window\.)?Fusion\[['\"]globalContent['\"]\]\s*=\s*"),
)
_ANS_TEXT_ELEMENT_TYPES = frozenset({"text", "header", "quote", "correction"})
_ANS_UNSUPPORTED_PLACEHOLDER_RE = re.compile(
    r"^unsupported\s+[a-z0-9_-]+(?:\s+with\s+classes\s+\[[^\]]*\])?\s*$",
    re.IGNORECASE,
)
_STANDALONE_EMAIL_RE = re.compile(r"^[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}$", re.IGNORECASE)
_LAYOUT_SEPARATOR_RE = re.compile(r"^[\s_\-=–—·•.]+$")
_PAGE_MARKER_RE = re.compile(r"^(?:p\.?\s*)?\d{1,3}(?:\s*/\s*\d{1,3})?$", re.IGNORECASE)
_BYLINE_MARKER_RE = re.compile(r"^por\s+[^\d]{2,80}$", re.IGNORECASE)
_GENERIC_PUBLISHER_AUTHORS = frozenset(
    {"pagina 12", "pagina12", "pagina|12", "página 12", "página12", "página|12"}
)
_SPANISH_MONTHS: dict[str, int] = {
    "enero": 1,
    "febrero": 2,
    "marzo": 3,
    "abril": 4,
    "mayo": 5,
    "junio": 6,
    "julio": 7,
    "agosto": 8,
    "septiembre": 9,
    "setiembre": 9,
    "octubre": 10,
    "noviembre": 11,
    "diciembre": 12,
}
_SPANISH_WEEKDAYS = r"(?:lunes|martes|miércoles|miercoles|jueves|viernes|sábado|sabado|domingo)"
_DAY_MONTH_RE = re.compile(
    rf"\b(?:{_SPANISH_WEEKDAYS}\s+)?(0?[1-9]|[12]\d|3[01])\s+de\s+"
    rf"({'|'.join(_SPANISH_MONTHS)})\b",
    re.IGNORECASE,
)

_BODY_SELECTORS: tuple[str, ...] = (
    "article [data-testid='article-body'] p",
    "article [itemprop='articleBody'] p",
    "article .article-main-content p",
    "article .article-body p",
    "article .article-text p",
    "article .article-content p",
    "main .article-main-content p",
)

_SECTION_SELECTORS: tuple[str, ...] = (
    "article header h5 a",
    "article header h5",
    ".article-header h5 a",
    ".article-header h5",
)

_VOLANTA_SELECTORS: tuple[str, ...] = (
    "article header h2",
    ".article-header h2",
)

_SUBTITLE_SELECTORS: tuple[str, ...] = (
    "article header h3",
    ".article-header h3",
)

_IMAGE_EPIGRAPH_SELECTORS: tuple[str, ...] = (
    ".c-media-item__title",
    ".c-media-item__caption",
    ".article-main-image__title",
    ".article-main-image__caption",
    ".article-image__title",
    ".article-image__caption",
    "[data-testid='image-caption']",
    "[data-testid='image-title']",
)
_IMAGE_CREDIT_SELECTORS: tuple[str, ...] = (
    ".c-media-item__credit",
    ".article-main-image__credit",
    ".article-image__credit",
    ".photo-credit",
    ".image-credit",
    "[data-testid='image-credit']",
    "[class*='credit']",
)

_AUTHOR_SELECTORS: tuple[str, ...] = (
    "article header .p12Author .author-name .name",
    "article .p12Author .author-name .name",
    ".article-header .p12Author .author-name .name",
    "article header [rel='author']",
    "article header a[href*='/autor/']",
    "article header a[href*='/autores/']",
    "article .article-author",
)


def _parse_html(html: str) -> BeautifulSoup:
    """Construye el parser HTML al utilizar el extra de scraping."""
    try:
        from bs4 import BeautifulSoup, FeatureNotFound
    except ImportError as e:
        raise RuntimeError(
            'Beautiful Soup no está instalado. Instalá el extra: pip install -e ".[scraping]"'
        ) from e

    try:
        return BeautifulSoup(html, "lxml")
    except FeatureNotFound as e:
        raise RuntimeError(
            'El parser lxml no está instalado. Instalá el extra: pip install -e ".[scraping]"'
        ) from e


class Pagina12Adapter(SourceAdapter):
    """Extrae artículos de Página/12 mediante RSS seccional y sitemap.

    El adapter trata cada página como un documento compuesto: primero identifica
    inequívocamente la historia propia de la URL y luego normaliza los campos que
    consume EmoParse. La metadata/parátexto adicional del documento identificado
    se conserva en ``DiscursoRecord.raw`` para auditoría y reprocesamiento.
    """

    source_id = "pagina12"
    requires_selenium = False

    def __init__(
        self,
        *,
        mode: Mode = "auto",
        sitemap_url: str | None = None,
        timeout: float = 20.0,
        max_retries: int = 3,
        request_interval: float = 0.75,
        sections: Iterable[str] | None = None,
        subtypes: Iterable[str] | None = None,
    ) -> None:
        if mode == "selenium":
            raise ValueError("La fuente pagina12 usa únicamente HTTP; elegí --mode http o auto.")
        if request_interval < 0:
            raise ValueError("request_interval no puede ser negativo")
        normalized_sections = _normalize_sections(sections)
        normalized_subtypes = _normalize_article_subtypes(subtypes)
        self._mode = mode
        self._sitemap_url = sitemap_url or _SITEMAP_URL
        self._request_interval = request_interval
        self._last_request_at: float | None = None
        self._http = HttpClient(timeout=timeout, max_retries=max_retries)
        self._sections = normalized_sections
        self._sections_explicit = sections is not None
        self._subtypes = normalized_subtypes
        self._subtypes_explicit = subtypes is not None
        self._discovery_context: dict[str, dict[str, Any]] = {}
        self._discovery_diagnostics: dict[str, dict[str, Any]] = {}

    @classmethod
    def available_sections(cls) -> tuple[str, ...]:
        """Slugs de secciones aceptados por ``sections``/``--section``."""
        return tuple(_RSS_SECTIONS)

    @property
    def sections(self) -> tuple[str, ...]:
        """Secciones efectivas de RSS usadas en el descubrimiento."""
        return self._sections or _DEFAULT_RSS_SECTIONS

    @classmethod
    def available_subtypes(cls) -> tuple[str, ...]:
        """Subtipos semánticos aceptados por ``subtypes``/``--subtype``."""
        return _ARTICLE_SUBTYPES

    @property
    def subtypes(self) -> tuple[str, ...]:
        """Subtipos de artículo aceptados en la corrida actual."""
        return self._subtypes or _ARTICLE_SUBTYPES

    @property
    def discovery_diagnostics(self) -> dict[str, dict[str, Any]]:
        """Diagnóstico serializable de los feeds RSS consultados en la corrida."""
        return {key: dict(value) for key, value in self._discovery_diagnostics.items()}

    def accepts_record(self, record: DiscursoRecord) -> bool:
        """Aplica el filtro público de subtipos después de identificar la nota.

        Sin ``--subtype`` se conserva el comportamiento histórico y también se
        preservan documentos auxiliares. Cuando el usuario selecciona uno o más
        subtipos, sólo se persisten artículos de esos subtipos.
        """
        payload = record.to_dict()
        if not self._subtypes_explicit:
            return True
        if str(payload.get("tipo_documento") or "") != "articulo":
            return False
        return str(payload.get("subtipo_articulo") or "static") in self.subtypes

    def counts_toward_max(self, record: DiscursoRecord) -> bool:
        """Sólo los artículos periodísticos consumen ``scrape --max``.

        Página/12 también publica piezas editoriales en forma de ``story`` (por
        ejemplo índices de la edición). Se preservan como registros, pero no
        cuentan cuando el usuario pide N artículos.
        """
        payload = record.to_dict()
        return str(payload.get("tipo_documento") or "articulo") == "articulo"

    def list_discursos(
        self,
        *,
        max_items: int | None = None,
        from_date: date | None = None,
        to_date: date | None = None,
    ) -> Iterator[str]:
        """Itera URLs, filtrando fecha antes del tope de URLs listadas.

        El CLI de adquisición no usa este ``max_items`` para su ``--max``:
        ``--max`` cuenta artículos efectivamente extraídos. El parámetro se
        conserva en el contrato del adapter para callers que sí quieran limitar
        sólo el listado.
        """
        emitted = 0
        discovered = 0
        seen: set[str] = set()

        for url, published, discovery in self._iter_discovery_entries():
            if url in seen or not _is_article_url(url):
                continue
            seen.add(url)
            discovered += 1

            effective_date = published or _date_from_url(url)
            if from_date is not None and effective_date is not None and effective_date < from_date:
                continue
            if to_date is not None and effective_date is not None and effective_date > to_date:
                continue

            self._discovery_context[url] = discovery
            yield url
            emitted += 1
            if max_items is not None and emitted >= max_items:
                return

        if discovered == 0:
            selected = ", ".join(self.sections)
            raise RuntimeError(
                "Página/12 no devolvió URLs de artículos desde los feeds RSS "
                f"seleccionados ({selected})"
                + ("." if self._sections_explicit else " ni desde el sitemap oficial.")
            )

    def _iter_discovery_entries(
        self,
    ) -> Iterator[tuple[str, date | None, dict[str, Any]]]:
        """Descubre primero por RSS seccional, balanceado entre secciones.

        Cada feed consultado deja diagnóstico explícito. Con secciones
        solicitadas por el usuario, una sección vacía o fallida se informa y
        nunca se sustituye silenciosamente por el sitemap. Si no se solicitaron
        secciones, el sitemap oficial queda como complemento final.
        """
        self._discovery_diagnostics = {}
        per_section: list[tuple[str, list[dict[str, Any]]]] = []
        for section in self.sections:
            feed_url = _RSS_SECTIONS[section]
            diagnostic: dict[str, Any] = {
                "section": section,
                "section_display": _SECTION_DISPLAY_NAMES[section],
                "feed_label": _RSS_FEED_LABELS[section],
                "feed_url": feed_url,
                "status": "pending",
                "entries": 0,
                "article_urls": 0,
            }
            try:
                feed_entries = _parse_rss_entries(self._fetch_text(feed_url))
            except (ValueError, requests.RequestException, TransientHttpError) as e:
                diagnostic["status"] = "error"
                diagnostic["error"] = f"{type(e).__name__}: {e}"
                self._discovery_diagnostics[section] = diagnostic
                logger.warning(f"[Pagina12] No se pudo usar RSS {section}: {e}")
                continue

            valid = [item for item in feed_entries if _is_article_url(str(item["url"]))]
            diagnostic["status"] = "ok"
            diagnostic["entries"] = len(feed_entries)
            diagnostic["article_urls"] = len(valid)
            self._discovery_diagnostics[section] = diagnostic
            if not valid:
                logger.warning(
                    f"[Pagina12] RSS {section}: 0 URLs de artículos "
                    f"({len(feed_entries)} entradas del feed)."
                )
            else:
                logger.info(
                    f"[Pagina12] RSS {section}: {len(valid)} URLs de artículos "
                    f"({len(feed_entries)} entradas)."
                )
                per_section.append((section, valid))

        if per_section:
            iterables = [entries for _, entries in per_section]
            for row in zip_longest(*iterables):
                for (section, _), item in zip(per_section, row, strict=True):
                    if item is None:
                        continue
                    url = str(item["url"])
                    published = item.get("published")
                    yield (
                        url,
                        published if isinstance(published, date) else None,
                        {
                            "kind": "rss",
                            "section": section,
                            "section_display": _SECTION_DISPLAY_NAMES[section],
                            "feed_label": _RSS_FEED_LABELS[section],
                            "feed_url": _RSS_SECTIONS[section],
                            "entry": _rss_entry_for_raw(item),
                            "feed_diagnostic": dict(self._discovery_diagnostics[section]),
                        },
                    )

        if self._sections_explicit:
            return

        sitemap_entries: list[tuple[str, date | None]] = []
        try:
            sitemap_entries = parse_sitemap(self._fetch_text(self._sitemap_url))
        except (ValueError, requests.RequestException, TransientHttpError) as e:
            logger.warning(f"[Pagina12] No se pudo usar el sitemap: {e}")

        valid_sitemap = [item for item in sitemap_entries if _is_article_url(item[0])]
        logger.info(f"[Pagina12] Sitemap complementario: {len(valid_sitemap)} URLs.")
        for url, published in valid_sitemap:
            yield (
                url,
                published,
                {"kind": "sitemap", "section": None, "feed_url": self._sitemap_url},
            )

    def fetch_discurso(self, url: str) -> DiscursoRecord | None:
        """Descarga una nota, normaliza campos y conserva el snapshot fuente.

        Página/12 usa Arc XP y una página renderizada puede contener el ``story``
        de la nota junto con promos/listas de otras noticias. El adapter sólo usa
        objetos JSON-LD/ANS cuya identidad coincide con URL/título/fecha de la
        nota. La metadata adicional del objeto identificado se conserva en
        ``raw``; no se usa para rellenar campos cuando su semántica es ambigua.
        """
        html = self._fetch_text(url)
        soup = _parse_html(html)

        canonical_url = _validated_canonical_url(soup, url)
        visible_title = _first_nonempty(
            _first_text(soup, ("article h1", "main h1", "h1")),
            _meta_content(soup, "property", "og:title"),
        )
        url_date = _date_from_url(canonical_url)
        visible_date = _first_nonempty(
            normalize_date(_meta_content(soup, "property", "article:published_time")),
            _extract_time(soup),
            url_date.isoformat() if url_date is not None else "",
        )

        article = _extract_news_article(
            soup,
            canonical_url=canonical_url,
            page_title=visible_title,
            page_date=visible_date,
        )
        story = _extract_fusion_global_content(
            soup,
            canonical_url=canonical_url,
            page_title=visible_title,
            page_date=visible_date,
        )

        titulo, title_source = _first_with_source(
            (visible_title, "dom_or_og"),
            (_fusion_headline(story), "ans_story.headlines.basic"),
            (_structured_headline(article), "jsonld.headline"),
        )
        fecha, date_source = _first_with_source(
            (visible_date, "page_or_url"),
            (_fusion_date(story), "ans_story.publish_date"),
            (normalize_date(_as_text(article.get("datePublished"))), "jsonld.datePublished"),
        )

        ans_subtitle = _fusion_subheadline(story)
        dom_subtitle = _first_text(soup, _SUBTITLE_SELECTORS)
        raw_subtitulo, subtitle_source = _first_with_source(
            (ans_subtitle, "ans_story.subheadlines.basic"),
            (dom_subtitle, "dom.header"),
        )
        subtitulo = (
            "" if _is_stale_dynamic_subtitle(titulo, raw_subtitulo, fecha) else raw_subtitulo
        )
        if raw_subtitulo and not subtitulo:
            subtitle_source = f"{subtitle_source}:discarded_stale_dynamic"

        stale_dynamic_descriptions = tuple(
            value
            for value in (
                _meta_content(soup, "property", "og:description"),
                _meta_content(soup, "name", "description"),
                _structured_description(article),
                _fusion_description(story),
            )
            if value and _is_stale_dynamic_subtitle(titulo, value, fecha)
        )
        article_subtype = _classify_article_subtype(story)
        contenido, body_source, content_classification = _extract_body_bundle(
            soup,
            article,
            story,
            excluded_texts=(titulo, raw_subtitulo, *stale_dynamic_descriptions),
        )
        if not titulo or not contenido.strip():
            logger.warning(f"[Pagina12] Nota sin título o sin cuerpo atribuible, se omite: {url}")
            return None

        discovery = self._discovery_context.get(url) or self._discovery_context.get(canonical_url)
        discovery_section = ""
        if isinstance(discovery, dict):
            discovery_section = _as_text(discovery.get("section_display"))
        seccion, section_source = _first_with_source(
            (_fusion_section(story), "ans_story.taxonomy"),
            (_structured_section(article), "jsonld.articleSection"),
            (_meta_content(soup, "property", "article:section"), "meta.article:section"),
            (_first_text(soup, _SECTION_SELECTORS), "dom.header"),
            (discovery_section, "discovery.rss_section"),
        )
        volanta, overline_source = _select_pagina12_overline(
            soup, story, titulo=titulo, subtitulo=subtitulo, fecha=fecha
        )
        autoria, authors_source = _extract_authors_for_story(soup, story, article)
        ans_epigrafe, ans_epigrafe_source = _fusion_image_epigraph(story)
        dom_epigrafe, dom_epigrafe_source = _extract_dom_image_epigraph(soup, story)
        epigrafe, caption_source = _first_with_source(
            (ans_epigrafe, ans_epigrafe_source),
            (_extract_image_caption(article), "jsonld.image.caption"),
            (dom_epigrafe, dom_epigrafe_source),
        )
        agencia, agency_source = _extract_story_agency(story)
        idioma, language_source = _first_with_source(
            (_fusion_language(story), "ans_story.language"),
            (_html_language(soup), "html.lang"),
            (_structured_language(article), "jsonld.inLanguage"),
            ("es-AR", "default"),
        )
        tipo_documento, document_classification = _classify_document_kind(story, titulo=titulo)

        provenance = {
            "titulo": title_source,
            "fecha": date_source,
            "contenido": body_source,
            "seccion": section_source,
            "volanta": overline_source,
            "subtitulo": subtitle_source,
            "autoria": authors_source,
            "agencia": agency_source,
            "epigrafe": caption_source,
            "idioma": language_source,
        }
        raw = _build_raw_snapshot(
            soup=soup,
            requested_url=url,
            canonical_url=canonical_url,
            visible_title=visible_title,
            visible_date=visible_date,
            story=story,
            article=article,
            discovery=discovery,
            provenance=provenance,
            content_classification=content_classification,
            document_classification={
                "tipo_documento": tipo_documento,
                "subtipo_articulo": article_subtype,
                "subtipo_fuente": _fusion_story_subtype(story),
                "requested_subtypes": list(self.subtypes),
                **document_classification,
            },
            discovery_diagnostics=self.discovery_diagnostics,
            live_blog=_build_live_blog_snapshot(story, content_classification),
        )

        extras = (
            ("medio", "Página/12"),
            ("idioma", idioma),
            ("seccion", seccion),
            ("volanta", volanta),
            ("subtitulo", subtitulo),
            ("autoria", json.dumps(autoria, ensure_ascii=False)),
            ("agencia", agencia),
            ("epigrafe", epigrafe),
            ("tipo_documento", tipo_documento),
            ("subtipo_articulo", article_subtype),
            ("subtipo_fuente", _fusion_story_subtype(story)),
            ("scrape_mode", "http"),
        )

        return DiscursoRecord(
            codigo=_codigo_from_url(canonical_url),
            url=canonical_url,
            titulo=titulo,
            fecha=fecha,
            contenido=contenido,
            fuente=self.source_id,
            extras=extras,
            raw=raw,
        )

    def _fetch_text(self, url: str) -> str:
        """Descarga texto con un intervalo mínimo entre solicitudes."""
        if self._last_request_at is not None:
            elapsed = time.monotonic() - self._last_request_at
            wait = self._request_interval - elapsed
            if wait > 0:
                time.sleep(wait)
        response = self._http.get(url)
        self._last_request_at = time.monotonic()
        if response.status_code >= 400:
            response.raise_for_status()
        return response.text

    def close(self) -> None:
        """Cierra la sesión HTTP."""
        self._http.close()


def parse_sitemap(xml: str) -> list[tuple[str, date | None]]:
    """Parsea un sitemap XML y devuelve URL y fecha de publicación conocida."""
    try:
        root = ElementTree.fromstring(xml)
    except ElementTree.ParseError as e:
        raise ValueError(f"Sitemap XML inválido: {e}") from e

    items: list[tuple[str, date | None]] = []
    for url_node in root.findall(".//{*}url"):
        location = _child_text(url_node, "loc")
        if not location:
            continue
        raw_date = _child_text(url_node, "publication_date") or _child_text(url_node, "lastmod")
        items.append((location, _parse_date(raw_date)))
    return items


def parse_rss(xml: str) -> list[tuple[str, date | None]]:
    """Parsea RSS o Atom y conserva el contrato público URL+fecha."""
    return [
        (
            str(item["url"]),
            item.get("published") if isinstance(item.get("published"), date) else None,
        )
        for item in _parse_rss_entries(xml)
    ]


def _parse_rss_entries(xml: str) -> list[dict[str, Any]]:
    """Parsea RSS/Atom preservando metadata del ítem para ``raw.discovery``."""
    try:
        root = ElementTree.fromstring(xml)
    except ElementTree.ParseError as e:
        raise ValueError(f"Feed XML inválido: {e}") from e

    items: list[dict[str, Any]] = []
    for item in root.findall(".//{*}item"):
        location = _child_text(item, "link") or _child_text(item, "guid")
        if not location:
            continue
        raw_date = (
            _child_text(item, "pubDate")
            or _child_text(item, "date")
            or _child_text(item, "published")
            or _child_text(item, "updated")
        )
        items.append(
            {
                "url": location,
                "published": _parse_date(raw_date),
                "published_raw": raw_date,
                "title": _child_text(item, "title"),
                "description": _child_text(item, "description"),
                "guid": _child_text(item, "guid"),
                "categories": _child_texts(item, "category"),
            }
        )

    for entry in root.findall(".//{*}entry"):
        location = _atom_link(entry)
        if not location:
            continue
        raw_date = (
            _child_text(entry, "published")
            or _child_text(entry, "updated")
            or _child_text(entry, "date")
        )
        items.append(
            {
                "url": location,
                "published": _parse_date(raw_date),
                "published_raw": raw_date,
                "title": _child_text(entry, "title"),
                "description": _child_text(entry, "summary"),
                "guid": _child_text(entry, "id"),
                "categories": _atom_categories(entry),
            }
        )
    return items


def _rss_entry_for_raw(item: dict[str, Any]) -> dict[str, Any]:
    """Convierte la entrada de descubrimiento a valores JSON serializables."""
    return {
        key: (value.isoformat() if isinstance(value, date) else value)
        for key, value in item.items()
        if key != "url" and value not in (None, "", [], ())
    }


def _child_texts(node: ElementTree.Element, local_name: str) -> list[str]:
    values: list[str] = []
    for child in node.iter():
        if child.tag.rsplit("}", 1)[-1] != local_name or not child.text:
            continue
        value = clean_whitespace(child.text)
        if value and value not in values:
            values.append(value)
    return values


def _atom_categories(entry: ElementTree.Element) -> list[str]:
    values: list[str] = []
    for child in entry:
        if child.tag.rsplit("}", 1)[-1] != "category":
            continue
        value = str(child.attrib.get("term") or child.text or "").strip()
        if value and value not in values:
            values.append(value)
    return values


def _atom_link(entry: ElementTree.Element) -> str:
    for child in entry:
        if child.tag.rsplit("}", 1)[-1] != "link":
            continue
        relation = child.attrib.get("rel", "alternate")
        href = child.attrib.get("href", "").strip()
        if href and relation in {"", "alternate"}:
            return href
    return ""


def _child_text(node: ElementTree.Element, local_name: str) -> str:
    for child in node.iter():
        if child.tag.rsplit("}", 1)[-1] == local_name and child.text:
            return child.text.strip()
    return ""


def _parse_date(raw: str) -> date | None:
    normalized = normalize_date(raw)
    if normalized:
        try:
            return date.fromisoformat(normalized)
        except ValueError:
            pass
    try:
        return parsedate_to_datetime(raw).date()
    except (TypeError, ValueError, OverflowError):
        return None


def _date_from_url(url: str) -> date | None:
    match = _URL_DATE_RE.search(urlparse(url).path)
    if match is None:
        return None
    try:
        return date(*(int(part) for part in match.groups()))
    except ValueError:
        return None


def _is_article_url(url: str) -> bool:
    parsed = urlparse(url)
    if parsed.netloc not in {"pagina12.com.ar", "www.pagina12.com.ar"}:
        return False
    return bool(
        _DATED_ARTICLE_URL_RE.search(parsed.path) or _LEGACY_ARTICLE_URL_RE.search(parsed.path)
    )


def _normalize_section_key(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value.strip().casefold())
    normalized = "".join(ch for ch in normalized if not unicodedata.combining(ch))
    normalized = re.sub(r"[^a-z0-9]+", "-", normalized).strip("-")
    return normalized


def _normalize_sections(sections: Iterable[str] | None) -> tuple[str, ...]:
    if sections is None:
        return ()
    normalized: list[str] = []
    for raw in sections:
        for part in str(raw).split(","):
            key = _normalize_section_key(part)
            if not key:
                continue
            canonical = _SECTION_ALIASES.get(key, key)
            if canonical not in _RSS_SECTIONS:
                available = ", ".join(_RSS_SECTIONS)
                raise ValueError(
                    f"Sección de Página/12 desconocida: {part!r}. Disponibles: {available}"
                )
            if canonical not in normalized:
                normalized.append(canonical)
    if not normalized:
        raise ValueError("sections no puede quedar vacío si se especifica")
    return tuple(normalized)


def _normalize_article_subtypes(subtypes: Iterable[str] | None) -> tuple[str, ...]:
    """Normaliza subtipos públicos sin exponer los subtipos internos de Arc."""
    if subtypes is None:
        return ()
    normalized: list[str] = []
    for raw in subtypes:
        for part in str(raw).split(","):
            key = _normalize_section_key(part)
            if not key:
                continue
            canonical = _ARTICLE_SUBTYPE_ALIASES.get(key)
            if canonical is None:
                available = ", ".join(_ARTICLE_SUBTYPES)
                raise ValueError(
                    f"Subtipo de Página/12 desconocido: {part!r}. Disponibles: {available}"
                )
            if canonical not in normalized:
                normalized.append(canonical)
    if not normalized:
        raise ValueError("subtypes no puede quedar vacío si se especifica")
    return tuple(normalized)


def _fusion_story_subtype(candidate: dict[str, Any]) -> str:
    """Devuelve el subtipo fuente de Arc sin reinterpretarlo."""
    return _as_text(candidate.get("subtype"))


def _classify_article_subtype(candidate: dict[str, Any]) -> str:
    """Clasifica la nota en los subtipos semánticos públicos del adapter."""
    return (
        "lbp_article" if _fusion_story_subtype(candidate).casefold() == "lbp_article" else "static"
    )


def _validated_canonical_url(soup: BeautifulSoup, requested_url: str) -> str:
    candidate = _canonical_url(soup)
    if candidate and _is_article_url(candidate):
        return candidate
    return requested_url


def _first_with_source(*candidates: tuple[str, str]) -> tuple[str, str]:
    for value, source in candidates:
        if value:
            return value, source
    return "", "absent"


def _fusion_subheadline(candidate: dict[str, Any]) -> str:
    subheadlines = candidate.get("subheadlines")
    if isinstance(subheadlines, dict):
        return _as_text(subheadlines.get("basic"))
    return ""


def _fusion_section(candidate: dict[str, Any]) -> str:
    taxonomy = candidate.get("taxonomy")
    if isinstance(taxonomy, dict):
        primary = taxonomy.get("primary_section")
        if isinstance(primary, dict):
            value = _as_text(primary.get("name") or primary.get("display_name"))
            if value:
                return value
        sections = taxonomy.get("sections")
        if isinstance(sections, list):
            for section in sections:
                if isinstance(section, dict):
                    value = _as_text(section.get("name") or section.get("display_name"))
                    if value:
                        return value

    primary = candidate.get("website_primary_section")
    if isinstance(primary, dict):
        value = _as_text(primary.get("name") or primary.get("display_name"))
        if value:
            return value

    websites = candidate.get("websites")
    if isinstance(websites, dict):
        for website in websites.values():
            if not isinstance(website, dict):
                continue
            section = website.get("website_section")
            if isinstance(section, dict):
                value = _as_text(section.get("name") or section.get("display_name"))
                if value:
                    return value
    return ""


def _structured_section(candidate: dict[str, Any]) -> str:
    section = candidate.get("articleSection")
    if isinstance(section, list):
        for value in section:
            text = _as_text(value)
            if text:
                return text
        return ""
    return _as_text(section)


def _fusion_label(candidate: dict[str, Any]) -> str:
    label = candidate.get("label")
    if not isinstance(label, dict):
        return ""
    basic = label.get("basic")
    if isinstance(basic, dict):
        return _as_text(basic.get("text") or basic.get("name"))
    return _as_text(basic)


def _fusion_authors(candidate: dict[str, Any]) -> tuple[str, ...]:
    credits = candidate.get("credits")
    if not isinstance(credits, dict):
        return ()
    by = credits.get("by")
    if not isinstance(by, list):
        return ()
    authors: list[str] = []
    for item in by:
        if not isinstance(item, dict):
            continue
        name = _clean_author(_as_text(item.get("name")))
        _append_unique(authors, name)
    return tuple(authors)


def _structured_authors(candidate: dict[str, Any]) -> tuple[str, ...]:
    """Autores JSON-LD, excluyendo el publisher genérico de Página/12.

    Algunas páginas publican ``author: Organization(Página 12)`` como fallback
    SEO cuando no hay firma. Ese objeto se preserva en ``raw`` pero no se
    normaliza como autoría periodística.
    """
    raw = candidate.get("author")
    values = raw if isinstance(raw, list) else [raw]
    authors: list[str] = []
    for item in values:
        item_type = ""
        if isinstance(item, dict):
            name = _as_text(item.get("name"))
            item_type = _as_text(item.get("@type")).casefold()
        else:
            name = _as_text(item)
        cleaned = _clean_author(name)
        normalized = _normalize_section_key(cleaned).replace("-", " ")
        if normalized in {
            _normalize_section_key(v).replace("-", " ") for v in _GENERIC_PUBLISHER_AUTHORS
        }:
            continue
        if item_type == "organization" and not cleaned:
            continue
        _append_unique(authors, cleaned)
    return tuple(authors)


def _extract_authors_for_story(
    soup: BeautifulSoup,
    story: dict[str, Any],
    article: dict[str, Any],
) -> tuple[tuple[str, ...], str]:
    authors = _fusion_authors(story)
    if authors:
        return authors, "ans_story.credits.by"
    authors = _extract_authors(soup)
    if authors:
        return authors, "dom.byline"
    authors = _structured_authors(article)
    if 0 < len(authors) <= 4:
        return authors, "jsonld.author"
    return (), "absent"


def _fusion_image_epigraph(candidate: dict[str, Any]) -> tuple[str, str]:
    """Devuelve texto de epígrafe sin mezclar créditos de la imagen.

    Página/12 utiliza ``caption`` cuando está disponible y ``subtitle`` en
    otras imágenes. Los créditos/autores/copyright permanecen separados dentro
    del ``promo_items`` preservado en ``raw``.
    """
    promo = candidate.get("promo_items")
    if not isinstance(promo, dict):
        return "", "absent"
    for key in ("lead_art", "basic"):
        item = promo.get(key)
        if not isinstance(item, dict):
            continue
        caption = item.get("caption")
        if isinstance(caption, dict):
            caption = caption.get("basic") or caption.get("text")
        value = _as_text(caption)
        if value:
            return value, f"ans_story.promo_items.{key}.caption"
        subtitle = _as_text(item.get("subtitle"))
        if subtitle:
            return subtitle, f"ans_story.promo_items.{key}.subtitle"
    return "", "absent"


def _fusion_image_credit_names(candidate: dict[str, Any]) -> tuple[str, ...]:
    """Créditos/autores de la imagen principal ANS, sólo para desambiguar DOM."""
    promo = candidate.get("promo_items")
    if not isinstance(promo, dict):
        return ()
    names: list[str] = []
    for key in ("lead_art", "basic"):
        item = promo.get(key)
        if not isinstance(item, dict):
            continue
        credits = item.get("credits")
        if not isinstance(credits, dict):
            continue
        by = credits.get("by")
        if not isinstance(by, list):
            continue
        for author in by:
            if not isinstance(author, dict):
                continue
            for raw in (author.get("name"), author.get("org")):
                value = _as_text(raw)
                if value and value not in names:
                    names.append(value)
    return tuple(names)


def _strip_known_image_credits(text: str, credits: tuple[str, ...]) -> str:
    """Quita únicamente créditos ANS conocidos cuando aparecen aislados al final."""
    cleaned = clean_whitespace(text)
    if not cleaned:
        return ""
    for credit in credits:
        if not credit:
            continue
        if _normalized_text_key(cleaned) == _normalized_text_key(credit):
            return ""
        # El fallback DOM a veces concatena caption + crédito dentro de figcaption.
        # Sólo removemos un crédito que el story identifica para esa misma imagen
        # y únicamente si ocupa el extremo final del texto.
        pattern = re.compile(
            rf"(?:\s*[|·•–—-]\s*)?{re.escape(credit)}\s*$",
            re.IGNORECASE,
        )
        cleaned = clean_whitespace(pattern.sub("", cleaned))
    return cleaned


def _extract_dom_image_epigraph(
    soup: BeautifulSoup,
    story: dict[str, Any],
) -> tuple[str, str]:
    """Extrae caption/título visible sin convertir créditos fotográficos en epígrafe.

    Página/12 separa visualmente título/caption y crédito, pero algunos layouts
    antiguos los agrupan dentro de un único ``figcaption``. El ``story`` ANS ya
    identificado aporta los nombres de crédito de la imagen y permite separar
    ambos roles sin heurísticas basadas en agencias concretas.
    """
    article = soup.select_one("article")
    scope = article or soup.select_one("main")
    if scope is None:
        return "", "absent"

    credits = _fusion_image_credit_names(story)
    for figure in scope.select("figure"):
        for selector in _IMAGE_EPIGRAPH_SELECTORS:
            element = figure.select_one(selector)
            if element is None:
                continue
            value = _strip_known_image_credits(element.get_text(separator=" ", strip=True), credits)
            if value:
                return value, f"dom.figure{selector}"

        figcaption = figure.find("figcaption")
        if figcaption is None:
            continue

        # Trabajamos sobre una copia parseada del figcaption para quitar nodos
        # cuyo rol DOM es explícitamente de crédito, sin destruir el snapshot
        # original que luego se conserva completo en ``raw``.
        fragment_soup = _parse_html(str(figcaption))
        fragment = fragment_soup.find("figcaption") or fragment_soup
        for selector in _IMAGE_CREDIT_SELECTORS:
            for credit_node in fragment.select(selector):
                credit_node.decompose()
        candidate = _strip_known_image_credits(
            fragment.get_text(separator=" ", strip=True), credits
        )
        if candidate:
            return candidate, "dom.figure.figcaption_without_credit"
    return "", "absent"


def _fusion_image_caption(candidate: dict[str, Any]) -> str:
    """Compatibilidad interna: texto de epígrafe estructurado."""
    return _fusion_image_epigraph(candidate)[0]


def _extract_story_agency(candidate: dict[str, Any]) -> tuple[str, str]:
    """Normaliza agencia sólo cuando ANS identifica inequívocamente un cable/wire."""
    distributor = candidate.get("distributor")
    distributor_name = ""
    distributor_category = ""
    if isinstance(distributor, dict):
        distributor_name = _as_text(distributor.get("name"))
        distributor_category = _as_text(distributor.get("category")).casefold()

    source = candidate.get("source")
    source_type = ""
    source_name = ""
    if isinstance(source, dict):
        source_type = _as_text(source.get("source_type")).casefold()
        source_name = _as_text(source.get("name"))

    is_wire = distributor_category.startswith("wire") or source_type.startswith("wire")
    if not is_wire:
        return "", "absent"

    for value, provenance in (
        (distributor_name, "ans_story.distributor.name[wire]"),
        (source_name, "ans_story.source.name[wire]"),
    ):
        if value and value.casefold() not in {"página/12", "pagina/12", "pagina12"}:
            return value, provenance

    credits = candidate.get("credits")
    if isinstance(credits, dict) and isinstance(credits.get("by"), list):
        for author in credits["by"]:
            if not isinstance(author, dict):
                continue
            org = _as_text(author.get("org"))
            if org and org.casefold() not in {"página/12", "pagina/12", "pagina12"}:
                return org, "ans_story.credits.by.org[wire]"
    return "", "absent"


def _fusion_language(candidate: dict[str, Any]) -> str:
    return _as_text(candidate.get("language"))


def _structured_language(candidate: dict[str, Any]) -> str:
    return _as_text(candidate.get("inLanguage"))


def _html_language(soup: BeautifulSoup) -> str:
    if soup.html is None:
        return ""
    return _as_text(soup.html.get("lang"))


def _json_safe_attrs(element: Tag) -> dict[str, Any]:
    attrs: dict[str, Any] = {}
    for key, value in element.attrs.items():
        if isinstance(value, (str, int, float, bool)) or value is None:
            attrs[str(key)] = value
        elif isinstance(value, (list, tuple)):
            attrs[str(key)] = [str(item) for item in value]
        else:
            attrs[str(key)] = str(value)
    return attrs


def _dom_element_snapshot(element: Tag | None) -> dict[str, Any] | None:
    if element is None:
        return None
    return {
        "tag": element.name,
        "attrs": _json_safe_attrs(element),
        "text": clean_whitespace(element.get_text(separator=" ", strip=True)),
        "html": str(element),
    }


def _collect_dom_paratext(soup: BeautifulSoup) -> dict[str, Any]:
    """Preserva fragmentos DOM paratextuales atribuibles al artículo."""
    article = soup.select_one("article")
    scope = article or soup.select_one("main")
    if scope is None:
        return {}

    header = scope.select_one("header") or soup.select_one(".article-header")
    figures = [_dom_element_snapshot(fig) for fig in scope.select("figure")]
    return {
        "article_attrs": _json_safe_attrs(article) if article is not None else None,
        "header": _dom_element_snapshot(header),
        "figures": [figure for figure in figures if figure is not None],
    }


def _collect_head_metadata(soup: BeautifulSoup) -> dict[str, Any]:
    metadata: list[dict[str, str]] = []
    for element in soup.select("head meta"):
        entry: dict[str, str] = {}
        for key in ("name", "property", "itemprop", "http-equiv", "content"):
            value = element.get(key)
            if value is not None:
                entry[key] = str(value)
        if entry:
            metadata.append(entry)

    links: list[dict[str, Any]] = []
    for element in soup.select("head link[rel]"):
        rel = element.get("rel")
        entry = {
            "rel": list(rel) if isinstance(rel, list) else str(rel or ""),
            "href": str(element.get("href") or ""),
        }
        if element.get("hreflang"):
            entry["hreflang"] = str(element.get("hreflang"))
        links.append(entry)
    return {"meta": metadata, "links": links}


def _build_raw_snapshot(
    *,
    soup: BeautifulSoup,
    requested_url: str,
    canonical_url: str,
    visible_title: str,
    visible_date: str,
    story: dict[str, Any],
    article: dict[str, Any],
    discovery: dict[str, Any] | None,
    provenance: dict[str, str],
    content_classification: list[dict[str, Any]],
    document_classification: dict[str, Any],
    discovery_diagnostics: dict[str, dict[str, Any]],
    live_blog: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Snapshot auditable sin mezclar módulos globales no identificados."""
    return {
        "schema": "emoparse.pagina12.raw.v2",
        "requested_url": requested_url,
        "canonical_url": canonical_url,
        "discovery": dict(discovery or {}),
        "discovery_diagnostics": discovery_diagnostics,
        "identity": {
            "visible_title": visible_title,
            "visible_date": visible_date,
            "ans_story_accepted": bool(story),
            "jsonld_article_accepted": bool(article),
        },
        "document_classification": dict(document_classification),
        "content_classification": list(content_classification),
        "live_blog": live_blog,
        "normalized_provenance": dict(provenance),
        "document_head": _collect_head_metadata(soup),
        "dom_paratext": _collect_dom_paratext(soup),
        "ans_story": story or None,
        "jsonld_article": article or None,
    }


def _normalize_url_identity(value: str) -> str:
    if not value:
        return ""
    parsed = urlparse(value)
    path = parsed.path or value
    path = re.sub(r"/+", "/", path).rstrip("/")
    return path.casefold() or "/"


def _structured_headline(candidate: dict[str, Any]) -> str:
    value = candidate.get("headline")
    if isinstance(value, dict):
        value = value.get("basic") or value.get("name")
    return _as_text(value)


def _structured_description(candidate: dict[str, Any]) -> str:
    value = candidate.get("description")
    if isinstance(value, dict):
        value = value.get("basic") or value.get("text")
    return _as_text(value)


def _fusion_headline(candidate: dict[str, Any]) -> str:
    headlines = candidate.get("headlines")
    if isinstance(headlines, dict):
        return _as_text(headlines.get("basic") or headlines.get("web"))
    return _structured_headline(candidate)


def _fusion_description(candidate: dict[str, Any]) -> str:
    """Descripción ANS de la historia, sin confundirla con ``subheadlines``."""
    description = candidate.get("description")
    if isinstance(description, dict):
        return _as_text(description.get("basic"))
    return _as_text(description)


def _select_pagina12_overline(
    soup: BeautifulSoup,
    story: dict[str, Any],
    *,
    titulo: str,
    subtitulo: str,
    fecha: str,
) -> tuple[str, str]:
    """Normaliza la volanta según el mapeo editorial observado en Página/12.

    Arc distingue ``label``, ``description`` y ``subheadlines``. En Página/12,
    el texto visible sobre el título se publica actualmente en ``label.basic``
    cuando existe y, en la mayoría de las notas, en ``description.basic``. La
    bajada se mantiene separada en ``subheadlines.basic``. El mapeo se limita a
    este adapter y conserva el objeto ANS completo en ``raw``.
    """
    candidates = (
        (_fusion_label(story), "ans_story.label.basic.text"),
        (_fusion_description(story), "ans_story.description.basic[pagina12_overline]"),
        (_first_text(soup, _VOLANTA_SELECTORS), "dom.header"),
    )
    excluded = {_normalized_text_key(value) for value in (titulo, subtitulo) if value}
    for value, source in candidates:
        if not value:
            continue
        if _normalized_text_key(value) in excluded:
            continue
        if _is_stale_dynamic_subtitle(titulo, value, fecha):
            continue
        return value, source
    return "", "absent"


def _fusion_date(candidate: dict[str, Any]) -> str:
    for key in ("publish_date", "first_publish_date", "display_date"):
        value = normalize_date(_as_text(candidate.get(key)))
        if value:
            return value
    return ""


def _candidate_urls(candidate: dict[str, Any], *, fusion: bool) -> tuple[str, ...]:
    values: list[str] = []

    def add(value: Any) -> None:
        text = _as_text(value)
        if text and text not in values:
            values.append(text)

    if fusion:
        add(candidate.get("canonical_url"))
        add(candidate.get("website_url"))
        websites = candidate.get("websites")
        if isinstance(websites, dict):
            for website in websites.values():
                if isinstance(website, dict):
                    add(website.get("website_url"))
    else:
        add(candidate.get("url"))
        add(candidate.get("@id"))
        main = candidate.get("mainEntityOfPage")
        if isinstance(main, dict):
            add(main.get("@id"))
            add(main.get("url"))
        else:
            add(main)
    return tuple(values)


def _candidate_identity_score(
    candidate: dict[str, Any],
    *,
    canonical_url: str,
    page_title: str,
    page_date: str,
    fusion: bool,
) -> int:
    """Puntúa sólo coincidencias de identidad y rechaza contradicciones explícitas."""
    score = 0
    expected_url = _normalize_url_identity(canonical_url)
    urls = tuple(_normalize_url_identity(v) for v in _candidate_urls(candidate, fusion=fusion))
    urls = tuple(v for v in urls if v)
    url_matched = False
    if expected_url and urls:
        if expected_url not in urls:
            return -1
        score += 3
        url_matched = True

    headline = _fusion_headline(candidate) if fusion else _structured_headline(candidate)
    if page_title and headline:
        if _normalized_text_key(page_title) == _normalized_text_key(headline):
            score += 2
        elif not url_matched:
            return -1

    candidate_date = (
        _fusion_date(candidate)
        if fusion
        else normalize_date(_as_text(candidate.get("datePublished")))
    )
    if page_date and candidate_date:
        if page_date == candidate_date:
            score += 1
        elif not url_matched:
            return -1
    return score


def _extract_news_article(
    soup: BeautifulSoup,
    *,
    canonical_url: str = "",
    page_title: str = "",
    page_date: str = "",
) -> dict[str, Any]:
    candidates: list[dict[str, Any]] = []
    for script in soup.select('script[type="application/ld+json"]'):
        raw = script.string or script.get_text()
        if not raw.strip():
            continue
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            continue
        for candidate in _walk_json_ld(payload):
            types = candidate.get("@type", ())
            if isinstance(types, str):
                types = (types,)
            if any(str(t) in {"NewsArticle", "Article"} for t in types):
                candidates.append(candidate)

    if not candidates:
        return {}
    ranked = sorted(
        (
            (
                _candidate_identity_score(
                    candidate,
                    canonical_url=canonical_url,
                    page_title=page_title,
                    page_date=page_date,
                    fusion=False,
                ),
                candidate,
            )
            for candidate in candidates
        ),
        key=lambda item: item[0],
        reverse=True,
    )
    score, candidate = ranked[0]
    # Una coincidencia de título (2) o de URL (3) es el mínimo para aceptar
    # metadata estructurada. Una fecha sola no identifica una nota.
    return candidate if score >= 2 else {}


def _walk_json_ld(value: Any) -> Iterable[dict[str, Any]]:
    if isinstance(value, dict):
        yield value
        graph = value.get("@graph")
        if graph is not None:
            yield from _walk_json_ld(graph)
    elif isinstance(value, list):
        for item in value:
            yield from _walk_json_ld(item)


def _extract_fusion_global_content(
    soup: BeautifulSoup,
    *,
    canonical_url: str = "",
    page_title: str = "",
    page_date: str = "",
) -> dict[str, Any]:
    """Recupera sólo un documento ANS compatible con la identidad visible de la nota."""
    decoder = json.JSONDecoder()
    candidates: list[dict[str, Any]] = []
    for script in soup.select("script"):
        raw = script.string or script.get_text()
        if "globalContent" not in raw:
            continue
        for pattern in _FUSION_GLOBAL_CONTENT_PATTERNS:
            for match in pattern.finditer(raw):
                payload = _decode_json_assignment(raw, match.end(), decoder)
                if (
                    isinstance(payload, dict)
                    and str(payload.get("type") or "").casefold() == "story"
                ):
                    candidates.append(payload)

    if not candidates:
        return {}
    ranked = sorted(
        (
            (
                _candidate_identity_score(
                    candidate,
                    canonical_url=canonical_url,
                    page_title=page_title,
                    page_date=page_date,
                    fusion=True,
                ),
                candidate,
            )
            for candidate in candidates
        ),
        key=lambda item: item[0],
        reverse=True,
    )
    score, candidate = ranked[0]
    return candidate if score >= 2 else {}


def _decode_json_assignment(
    script: str,
    offset: int,
    decoder: json.JSONDecoder,
) -> Any:
    value = script[offset:].lstrip()
    if value.startswith("JSON.parse"):
        opening = value.find("(")
        if opening < 0:
            return None
        encoded = value[opening + 1 :].lstrip()
        try:
            serialized, _ = decoder.raw_decode(encoded)
        except json.JSONDecodeError:
            return None
        if not isinstance(serialized, str):
            return None
        try:
            return json.loads(serialized)
        except json.JSONDecodeError:
            return None

    try:
        payload, _ = decoder.raw_decode(value)
    except json.JSONDecodeError:
        return None
    return payload


def _extract_body_bundle(
    soup: BeautifulSoup,
    article: dict[str, Any],
    fusion_content: dict[str, Any],
    *,
    excluded_texts: Iterable[str] = (),
) -> tuple[str, str, list[dict[str, Any]]]:
    """Extrae cuerpo, procedencia y clasificación auditable de elementos.

    El ``story`` ANS identificado es la fuente preferida. Los elementos que no
    pertenecen al cuerpo analítico (contactos, recirculación, media embebida,
    etc.) no se destruyen: el story original y la clasificación quedan en
    ``raw``.
    """
    classification: list[dict[str, Any]] = []
    if _classify_article_subtype(fusion_content) == "lbp_article":
        fusion_body, classification = _extract_lbp_body_bundle(
            fusion_content, excluded_texts=excluded_texts
        )
        if fusion_body:
            return fusion_body, "ans_story.lbp_article", classification
    else:
        fusion_body, classification = _extract_ans_body_bundle(
            fusion_content, excluded_texts=excluded_texts
        )
        if fusion_body:
            return fusion_body, "ans_story.content_elements", classification

    for selector in _BODY_SELECTORS:
        paragraphs = soup.select(selector)
        texts = [text for text in _paragraph_texts(paragraphs) if not _is_standalone_contact(text)]
        if texts:
            body = strip_boilerplate(clean_whitespace("\n\n".join(texts)))
            if body:
                return body, f"dom:{selector}", []

    # JSON-LD es último fallback: suele aplanar el artículo en una sola cadena.
    structured = strip_boilerplate(clean_whitespace(_as_text(article.get("articleBody"))))
    if structured:
        return structured, "jsonld.articleBody", []
    return "", "absent", classification


def _extract_body_with_source(
    soup: BeautifulSoup,
    article: dict[str, Any],
    fusion_content: dict[str, Any],
    *,
    excluded_texts: Iterable[str] = (),
) -> tuple[str, str]:
    """Compatibilidad interna: extrae cuerpo + procedencia."""
    body, source, _ = _extract_body_bundle(
        soup, article, fusion_content, excluded_texts=excluded_texts
    )
    return body, source


def _extract_body(
    soup: BeautifulSoup,
    article: dict[str, Any],
    fusion_content: dict[str, Any],
    *,
    excluded_texts: Iterable[str] = (),
) -> str:
    """Compatibilidad interna: devuelve sólo el cuerpo."""
    return _extract_body_with_source(soup, article, fusion_content, excluded_texts=excluded_texts)[
        0
    ]


def _extract_ans_body_bundle(
    global_content: dict[str, Any],
    *,
    excluded_texts: Iterable[str] = (),
    standalone_bylines_as_paratext: bool = False,
) -> tuple[str, list[dict[str, Any]]]:
    elements = global_content.get("content_elements")
    if not isinstance(elements, list):
        return "", []

    excluded = {_normalized_text_key(value) for value in excluded_texts if value}
    paragraphs: list[str] = []
    classification: list[dict[str, Any]] = []

    for index, element in enumerate(elements):
        element_type = (
            str(element.get("type") or "").casefold() if isinstance(element, dict) else "unknown"
        )
        next_element = elements[index + 1] if index + 1 < len(elements) else None
        entry: dict[str, Any] = {
            "index": index,
            "type": element_type,
            "element_id": _as_text(element.get("_id")) if isinstance(element, dict) else "",
        }

        if _ans_element_is_recirculation(element):
            entry["role"] = "recirculation"
            entry["texts"] = _ans_element_visible_texts(element)
            classification.append(entry)
            continue

        if _ans_element_is_recirculation_label(element, next_element):
            entry["role"] = "recirculation_label"
            entry["texts"] = _ans_element_visible_texts(element)
            classification.append(entry)
            continue

        raw_texts = _ans_element_texts(element)
        kept_texts: list[str] = []
        removed_contacts: list[str] = []
        removed_duplicates: list[str] = []
        removed_technical: list[str] = []
        removed_bylines: list[str] = []
        for text in raw_texts:
            if _is_ans_technical_placeholder(text):
                removed_technical.append(text)
                continue
            if _normalized_text_key(text) in excluded:
                removed_duplicates.append(text)
                continue
            if _is_standalone_contact(text):
                removed_contacts.append(text)
                continue
            if standalone_bylines_as_paratext and _BYLINE_MARKER_RE.fullmatch(text):
                removed_bylines.append(text)
                continue
            kept_texts.append(text)

        if kept_texts:
            entry["role"] = "body"
            entry["texts"] = kept_texts
            paragraphs.extend(kept_texts)
        elif removed_contacts:
            entry["role"] = "contact"
            entry["texts"] = removed_contacts
        elif removed_duplicates:
            entry["role"] = "duplicate_paratext"
            entry["texts"] = removed_duplicates
        elif removed_bylines:
            entry["role"] = "byline_paratext"
            entry["texts"] = removed_bylines
        elif removed_technical:
            entry["role"] = "technical_placeholder"
            entry["texts"] = removed_technical
        elif element_type in {
            "image",
            "video",
            "gallery",
            "oembed_response",
            "raw_html",
            "custom_embed",
        }:
            entry["role"] = "embedded_media"
            entry["texts"] = []
        else:
            entry["role"] = "preserved_nonbody"
            entry["texts"] = _ans_element_visible_texts(element)
        classification.append(entry)

    return strip_boilerplate(clean_whitespace("\n\n".join(paragraphs))), classification


def _extract_lbp_body_bundle(
    story: dict[str, Any],
    *,
    excluded_texts: Iterable[str] = (),
) -> tuple[str, list[dict[str, Any]]]:
    """Normaliza un ``lbp_article`` preservando la frontera entre actualizaciones.

    Página/12 conserva las entradas del vivo en ``LBPList`` como stories
    ``lbp_update``. El cuerpo analítico incluye la introducción del padre y, en
    el orden entregado por la fuente, el titular y texto legítimo de cada
    actualización. IDs, timestamps, bylines, embeds y media quedan preservados
    en el ANS original y en la clasificación auditable.
    """
    parent_body, parent_classification = _extract_ans_body_bundle(
        story, excluded_texts=excluded_texts
    )
    paragraphs = [part for part in parent_body.split("\n\n") if part.strip()]
    classification: list[dict[str, Any]] = []
    for entry in parent_classification:
        tagged = dict(entry)
        tagged["scope"] = "lbp_parent"
        classification.append(tagged)

    updates = story.get("LBPList")
    if not isinstance(updates, list):
        return strip_boilerplate(clean_whitespace("\n\n".join(paragraphs))), classification

    seen_headlines: set[str] = set()
    for update_index, update in enumerate(updates):
        if not isinstance(update, dict):
            classification.append(
                {
                    "scope": "lbp_update",
                    "update_index": update_index,
                    "role": "invalid_update",
                    "type": type(update).__name__,
                    "texts": [],
                }
            )
            continue
        if _as_text(update.get("subtype")).casefold() != "lbp_update":
            classification.append(
                {
                    "scope": "lbp_update",
                    "update_index": update_index,
                    "update_id": _as_text(update.get("_id")),
                    "role": "unsupported_update_subtype",
                    "type": _as_text(update.get("type")),
                    "subtype": _as_text(update.get("subtype")),
                    "texts": _ans_story_visible_texts(update),
                }
            )
            continue

        headline = _fusion_headline(update)
        headline_key = _normalized_text_key(headline)
        if headline and headline_key not in seen_headlines:
            paragraphs.append(headline)
            seen_headlines.add(headline_key)
            classification.append(
                {
                    "scope": "lbp_update",
                    "update_index": update_index,
                    "update_id": _as_text(update.get("_id")),
                    "update_display_date": _as_text(update.get("display_date")),
                    "role": "update_headline",
                    "type": "headline",
                    "texts": [headline],
                }
            )

        update_body, update_classification = _extract_ans_body_bundle(
            update,
            excluded_texts=(headline,),
            standalone_bylines_as_paratext=True,
        )
        paragraphs.extend(part for part in update_body.split("\n\n") if part.strip())
        for entry in update_classification:
            tagged = dict(entry)
            tagged.update(
                {
                    "scope": "lbp_update",
                    "update_index": update_index,
                    "update_id": _as_text(update.get("_id")),
                    "update_headline": headline,
                    "update_display_date": _as_text(update.get("display_date")),
                }
            )
            classification.append(tagged)

    return strip_boilerplate(clean_whitespace("\n\n".join(paragraphs))), classification


def _ans_story_visible_texts(story: dict[str, Any]) -> list[str]:
    """Texto visible de ``content_elements`` para auditoría de stories anidados."""
    elements = story.get("content_elements")
    if not isinstance(elements, list):
        return []
    texts: list[str] = []
    for element in elements:
        texts.extend(_ans_element_visible_texts(element))
    return texts


def _build_live_blog_snapshot(
    story: dict[str, Any],
    classification: list[dict[str, Any]],
) -> dict[str, Any] | None:
    """Resumen estructurado del vivo; el ``LBPList`` completo sigue en ``ans_story``."""
    if _classify_article_subtype(story) != "lbp_article":
        return None
    updates = story.get("LBPList")
    if not isinstance(updates, list):
        updates = []
    summaries: list[dict[str, Any]] = []
    for index, update in enumerate(updates):
        if not isinstance(update, dict):
            continue
        update_entries = [
            item
            for item in classification
            if item.get("scope") == "lbp_update" and item.get("update_index") == index
        ]
        summaries.append(
            {
                "index": index,
                "id": _as_text(update.get("_id")),
                "subtype": _as_text(update.get("subtype")),
                "headline": _fusion_headline(update),
                "display_date": _as_text(update.get("display_date")),
                "publish_date": _as_text(update.get("publish_date")),
                "canonical_url": _first_nonempty(
                    _as_text(update.get("canonical_url")),
                    _as_text((update.get("additional_properties") or {}).get("story_url"))
                    if isinstance(update.get("additional_properties"), dict)
                    else "",
                ),
                "authors": _fusion_authors(update),
                "body_units": sum(
                    len(item.get("texts") or [])
                    for item in update_entries
                    if item.get("role") in {"body", "update_headline"}
                ),
                "paratext_units": sum(
                    len(item.get("texts") or [])
                    for item in update_entries
                    if item.get("role") not in {"body", "update_headline"}
                ),
            }
        )
    return {
        "schema": "emoparse.pagina12.live_blog.v1",
        "source_order": "LBPList",
        "parent_id": _as_text(story.get("_id")),
        "parent_subtype": _fusion_story_subtype(story),
        "update_count": len(summaries),
        "updates": summaries,
    }


def _extract_ans_body(
    global_content: dict[str, Any],
    *,
    excluded_texts: Iterable[str] = (),
) -> str:
    """Compatibilidad interna: devuelve sólo el cuerpo ANS."""
    return _extract_ans_body_bundle(global_content, excluded_texts=excluded_texts)[0]


def _is_standalone_contact(value: str) -> bool:
    """Detecta contactos editoriales que deben preservarse fuera del cuerpo."""
    text = clean_whitespace(value)
    return bool(_STANDALONE_EMAIL_RE.fullmatch(text))


def _ans_element_visible_texts(element: Any) -> list[str]:
    """Texto visible de un elemento, incluso si se clasifica fuera del cuerpo."""
    if not isinstance(element, dict):
        return []
    element_type = str(element.get("type") or "").casefold()
    if element_type in _ANS_TEXT_ELEMENT_TYPES:
        content = element.get("content")
        return _html_fragment_texts(content) if isinstance(content, str) else []
    if element_type in {"element_group", "list"}:
        texts: list[str] = []
        for child in _ans_nested_elements(element):
            if isinstance(child, str):
                texts.extend(_html_fragment_texts(child))
            else:
                texts.extend(_ans_element_visible_texts(child))
        return texts
    return []


def _html_fragment_is_emphasized_label(fragment: str) -> bool:
    """Verdadero si un fragmento corto está compuesto sólo por énfasis textual."""
    parsed = _parse_html(f"<body>{fragment}</body>")
    body = parsed.body
    if body is None or body.select("a[href]"):
        return False
    text = clean_whitespace(body.get_text(separator=" ", strip=True))
    if not text or len(text) > 120:
        return False
    tags = [tag.name for tag in body.find_all(True)]
    return bool(tags) and all(name in {"b", "strong", "i", "em", "span"} for name in tags)


def _ans_element_is_recirculation_label(element: Any, next_element: Any) -> bool:
    """Detecta el rótulo editorial inmediatamente anterior a un bloque de links."""
    if not _ans_element_is_recirculation(next_element) or not isinstance(element, dict):
        return False
    element_type = str(element.get("type") or "").casefold()
    if element_type not in {"text", "header"}:
        return False
    content = element.get("content")
    if not isinstance(content, str) or not content.strip():
        return False
    text = clean_whitespace(_parse_html(f"<body>{content}</body>").get_text(" ", strip=True))
    if not text or len(text) > 120:
        return False
    if element_type == "header":
        return True
    return _html_fragment_is_emphasized_label(content)


def _classify_document_kind(
    story: dict[str, Any],
    *,
    titulo: str,
) -> tuple[str, dict[str, Any]]:
    """Clasifica piezas editoriales que Arc representa como ``story``.

    La clasificación no depende sólo del slug. Los índices de la edición de
    Página/12 presentan un patrón de maquetación repetido: instrucciones como
    ``Cabezal``, múltiples bylines breves, separadores y referencias de página.
    Ese patrón los distingue de una nota periodística convencional.
    """
    elements = story.get("content_elements")
    if not isinstance(elements, list):
        return "articulo", {"reason": "no_ans_elements", "layout_score": 0}

    visible: list[str] = []
    for element in elements:
        visible.extend(_ans_element_visible_texts(element))
    normalized = [clean_whitespace(text) for text in visible if clean_whitespace(text)]
    instructions = sum(text.casefold().startswith("cabezal") for text in normalized)
    bylines = sum(bool(_BYLINE_MARKER_RE.fullmatch(text)) for text in normalized)
    separators = sum(bool(_LAYOUT_SEPARATOR_RE.fullmatch(text)) for text in normalized)
    standalone_pages = sum(bool(_PAGE_MARKER_RE.fullmatch(text)) for text in normalized)
    inline_page_refs = sum(
        bool(re.search(r"\bP\.\s*\d{1,3}(?:/\d{1,3})?\b", text)) for text in normalized
    )
    layout_score = instructions * 3 + bylines + separators + standalone_pages + inline_page_refs
    title_key = _normalized_text_key(titulo)
    title_signals_index = bool(re.match(r"^t[ií]tulos?\b", title_key, flags=re.IGNORECASE))
    is_index = (title_signals_index and layout_score >= 4) or (
        instructions >= 1 and bylines >= 2 and (standalone_pages + inline_page_refs) >= 2
    )
    details = {
        "reason": "editorial_layout" if is_index else "default_story",
        "layout_score": layout_score,
        "instructions": instructions,
        "bylines": bylines,
        "separators": separators,
        "standalone_page_markers": standalone_pages,
        "inline_page_refs": inline_page_refs,
        "title_index_signal": title_signals_index,
    }
    return ("indice_editorial" if is_index else "articulo"), details


def _normalized_text_key(value: str) -> str:
    return clean_whitespace(value).casefold()


def _is_ans_technical_placeholder(value: str) -> bool:
    return bool(_ANS_UNSUPPORTED_PLACEHOLDER_RE.fullmatch(clean_whitespace(value)))


def _day_month(value: str) -> tuple[int, int] | None:
    match = _DAY_MONTH_RE.search(value)
    if match is None:
        return None
    day = int(match.group(1))
    month_name = match.group(2).casefold()
    return day, _SPANISH_MONTHS[month_name]


def _without_day_month(value: str) -> str:
    value = _DAY_MONTH_RE.sub(" ", value)
    value = re.sub(r"[^\w]+", " ", value, flags=re.UNICODE)
    return clean_whitespace(value).casefold()


def _is_stale_dynamic_subtitle(title: str, subtitle: str, published: str) -> bool:
    """Descarta bajadas templadas que conservan la fecha de otra actualización viva."""
    if not title or not subtitle or not published:
        return False
    title_day_month = _day_month(title)
    subtitle_day_month = _day_month(subtitle)
    if title_day_month is None or subtitle_day_month is None:
        return False
    if title_day_month == subtitle_day_month:
        return False
    try:
        published_date = date.fromisoformat(published)
    except ValueError:
        return False
    if title_day_month != (published_date.day, published_date.month):
        return False
    return _without_day_month(title) == _without_day_month(subtitle)


def _ans_element_is_link_only_recirculation(element: Any) -> bool:
    """Detecta unidades ANS cuyo contenido visible es únicamente uno o más enlaces."""
    if not isinstance(element, dict):
        return False
    if str(element.get("type") or "").casefold() not in {"text", "header"}:
        return False

    content = element.get("content")
    if not isinstance(content, str) or not content.strip():
        return False

    parsed = _parse_html(f"<body>{content}</body>")
    body = parsed.body
    if body is None:
        return False
    anchors = body.select("a[href]")
    if not anchors:
        return False

    all_text = _normalized_text_key(body.get_text(separator=" ", strip=True))
    linked_text = _normalized_text_key(
        " ".join(anchor.get_text(separator=" ", strip=True) for anchor in anchors)
    )
    return bool(all_text) and all_text == linked_text


def _ans_nested_elements(element: dict[str, Any]) -> list[Any]:
    nested = element.get("content_elements")
    if not isinstance(nested, list):
        nested = element.get("items")
    return nested if isinstance(nested, list) else []


def _ans_element_is_recirculation(element: Any) -> bool:
    """Detecta recirculación por estructura ANS, no por frases concretas."""
    if not isinstance(element, dict):
        return False
    element_type = str(element.get("type") or "").casefold()
    if element_type in {
        "interstitial_link",
        "related_content",
        "reference",
    }:
        return True
    if _ans_element_is_link_only_recirculation(element):
        return True
    if element_type not in {"element_group", "list"}:
        return False

    nested = _ans_nested_elements(element)
    if not nested:
        return False
    has_link_only = False
    for child in nested:
        if isinstance(child, str):
            if _html_fragment_is_link_only(child):
                has_link_only = True
                continue
            return False
        if _ans_element_is_recirculation(child):
            has_link_only = True
            continue
        if _ans_is_plain_header(child):
            continue
        return False
    return has_link_only


def _ans_header_is_recirculation(element: Any) -> bool:
    """Compatibilidad interna: header enlazado o promocional."""
    return (
        isinstance(element, dict)
        and str(element.get("type") or "").casefold() == "header"
        and _ans_element_is_recirculation(element)
    )


def _ans_is_plain_header(element: Any) -> bool:
    if not isinstance(element, dict):
        return False
    if str(element.get("type") or "").casefold() != "header":
        return False

    content = element.get("content")
    if not isinstance(content, str) or not content.strip():
        return False

    parsed = _parse_html(f"<body>{content}</body>")
    body = parsed.body
    return body is not None and body.find(True) is None


def _ans_element_texts(element: Any) -> list[str]:
    if not isinstance(element, dict):
        return []

    element_type = str(element.get("type") or "").casefold()
    if _ans_element_is_recirculation(element):
        return []
    if element_type in _ANS_TEXT_ELEMENT_TYPES:
        content = element.get("content")
        if isinstance(content, str):
            return _html_fragment_texts(content)
        return []

    if element_type in {"element_group", "list"}:
        nested = _ans_nested_elements(element)
        if not nested:
            return []
        texts: list[str] = []
        for child in nested:
            if isinstance(child, str):
                if not _html_fragment_is_link_only(child):
                    texts.extend(_html_fragment_texts(child))
            else:
                texts.extend(_ans_element_texts(child))
        return texts

    return []


def _html_fragment_is_link_only(fragment: str) -> bool:
    parsed = _parse_html(f"<body>{fragment}</body>")
    body = parsed.body
    if body is None:
        return False
    anchors = body.select("a[href]")
    if not anchors:
        return False
    all_text = _normalized_text_key(body.get_text(separator=" ", strip=True))
    linked_text = _normalized_text_key(
        " ".join(anchor.get_text(separator=" ", strip=True) for anchor in anchors)
    )
    return bool(all_text) and all_text == linked_text


def _html_fragment_texts(fragment: str) -> list[str]:
    parsed = _parse_html(f"<body>{fragment}</body>")
    for unwanted in parsed.select("script, style, noscript"):
        unwanted.decompose()

    blocks = parsed.select("p, h2, h3, h4, h5, h6, blockquote")
    texts = _paragraph_texts(blocks)
    if texts:
        return texts

    text = clean_whitespace(parsed.get_text(separator=" ", strip=True))
    return [text] if text else []


def _paragraph_texts(paragraphs: Iterable[Tag]) -> list[str]:
    texts: list[str] = []
    for paragraph in paragraphs:
        text = clean_whitespace(paragraph.get_text(separator=" ", strip=True))
        if not text or text.lower() in {"temas en esta nota:", "últimas noticias"}:
            continue
        texts.append(text)
    return texts


def _extract_authors(soup: BeautifulSoup) -> tuple[str, ...]:
    """Extrae una byline visible como fallback del story identificado.

    Los créditos ANS/JSON-LD sólo se usan en ``_extract_authors_for_story``
    después de validar la identidad del documento. Este helper queda restringido
    al encabezado/área propia del artículo para no recoger tarjetas posteriores.
    """
    authors: list[str] = []
    for selector in _AUTHOR_SELECTORS:
        for element in soup.select(selector):
            _append_unique(
                authors,
                _clean_author(element.get_text(separator=" ", strip=True)),
            )
        if authors:
            return tuple(authors)
    return ()


def _clean_author(value: str) -> str:
    return re.sub(r"^por\s+", "", value.strip(), flags=re.IGNORECASE)


def _append_unique(values: list[str], value: str) -> None:
    if value and value not in values:
        values.append(value)


def _extract_image_caption(article: dict[str, Any]) -> str:
    image = article.get("image")
    candidates: list[Any]
    if isinstance(image, list):
        candidates = image
    else:
        candidates = [image]
    for candidate in candidates:
        if isinstance(candidate, dict):
            caption = _as_text(candidate.get("caption"))
            if caption:
                return caption
    return ""


def _canonical_url(soup: BeautifulSoup) -> str:
    element = soup.select_one('link[rel="canonical"]')
    if element is None:
        return ""
    return str(element.get("href") or "").strip()


def _extract_time(soup: BeautifulSoup) -> str:
    element = soup.select_one("article time, main time, time")
    if element is None:
        return ""
    raw = str(element.get("datetime") or element.get_text(strip=True))
    return normalize_date(raw)


def _meta_content(soup: BeautifulSoup, attr: str, value: str) -> str:
    element = soup.select_one(f'meta[{attr}="{value}"]')
    if element is None:
        return ""
    return str(element.get("content") or "").strip()


def _first_text(soup: BeautifulSoup, selectors: tuple[str, ...]) -> str:
    for selector in selectors:
        element = soup.select_one(selector)
        if element is None:
            continue
        text = clean_whitespace(element.get_text(separator=" ", strip=True))
        if text:
            return text
    return ""


def _as_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (list, tuple)):
        texts = [_as_text(item) for item in value]
        return "; ".join(text for text in texts if text)
    return clean_whitespace(str(value))


def _first_nonempty(*values: str) -> str:
    return next((value for value in values if value), "")


def _codigo_from_url(url: str) -> str:
    parsed = urlparse(url)
    slug = parsed.path.rstrip("/").rsplit("/", 1)[-1]
    slug = re.sub(r"[^\w-]+", "_", slug, flags=re.UNICODE).strip("_")[:80]
    published = _date_from_url(url)
    date_part = published.isoformat().replace("-", "") if published else "sinfecha"
    if not slug:
        slug = hashlib.sha1(url.encode("utf-8")).hexdigest()[:12]
    return f"pagina12_{date_part}_{slug}"


__all__ = ["Pagina12Adapter", "parse_rss", "parse_sitemap"]
