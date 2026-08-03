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
from collections.abc import Iterable, Iterator
from datetime import date
from email.utils import parsedate_to_datetime
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
_RSS_URLS: tuple[str, ...] = (
    f"{_BASE_DOMAIN}/arc/outboundfeeds/rss/portada",
    f"{_BASE_DOMAIN}/arc/outboundfeeds/rss/secciones/el-pais/notas",
    f"{_BASE_DOMAIN}/arc/outboundfeeds/rss/secciones/economia/notas",
    f"{_BASE_DOMAIN}/arc/outboundfeeds/rss/secciones/sociedad/notas",
    f"{_BASE_DOMAIN}/arc/outboundfeeds/rss/secciones/el-mundo/notas",
    f"{_BASE_DOMAIN}/arc/outboundfeeds/rss/secciones/cultura/notas",
)
_DATED_ARTICLE_URL_RE = re.compile(r"/\d{4}/\d{2}/\d{2}/[^/]+/?$")
_LEGACY_ARTICLE_URL_RE = re.compile(r"/\d{5,}-[^/]+/?$")
_URL_DATE_RE = re.compile(r"/(\d{4})/(\d{2})/(\d{2})/")
_FUSION_GLOBAL_CONTENT_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"(?:window\.)?Fusion\.globalContent\s*=\s*"),
    re.compile(r"(?:window\.)?Fusion\[['\"]globalContent['\"]\]\s*=\s*"),
)
_ANS_TEXT_ELEMENT_TYPES = frozenset({"text", "header", "quote", "correction"})

_BODY_SELECTORS: tuple[str, ...] = (
    "article [data-testid='article-body'] p",
    "article .article-main-content p",
    "article .article-body p",
    "article .article-text p",
    "article .article-content p",
    "main .article-main-content p",
    "main article p",
    "article p",
)

_SECTION_SELECTORS: tuple[str, ...] = (
    "article header h5 a",
    "article header h5",
    ".article-header h5 a",
    ".article-header h5",
    "main h5 a",
)

_VOLANTA_SELECTORS: tuple[str, ...] = (
    "article header h2",
    ".article-header h2",
    "main article h2",
)

_SUBTITLE_SELECTORS: tuple[str, ...] = (
    "article header h3",
    ".article-header h3",
    "main article h3",
)

_CAPTION_SELECTORS: tuple[str, ...] = (
    "article figure figcaption",
    "main figure figcaption",
    ".article-main-image figcaption",
    ".article-image figcaption",
)

_AUTHOR_SELECTORS: tuple[str, ...] = (
    ".p12Author .author-name .name",
    "article [rel='author']",
    "article a[href*='/autor/']",
    "article a[href*='/autores/']",
    ".article-author",
    ".author-name",
)

_AGENCY_NAMES: tuple[str, ...] = (
    "Noticias Argentinas",
    "Télam",
    "Reuters",
    "Associated Press",
    "Agencia EFE",
    "AFP",
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
    """Extrae artículos recientes de Página/12 mediante sitemap y RSS."""

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
    ) -> None:
        if mode == "selenium":
            raise ValueError("La fuente pagina12 usa únicamente HTTP; elegí --mode http o auto.")
        if request_interval < 0:
            raise ValueError("request_interval no puede ser negativo")
        self._mode = mode
        self._sitemap_url = sitemap_url or _SITEMAP_URL
        self._request_interval = request_interval
        self._last_request_at: float | None = None
        self._http = HttpClient(timeout=timeout, max_retries=max_retries)

    def list_discursos(
        self,
        *,
        max_items: int | None = None,
        from_date: date | None = None,
        to_date: date | None = None,
    ) -> Iterator[str]:
        """Itera URLs descubiertas y aplica el rango de fechas antes del tope."""
        emitted = 0
        discovered = 0
        seen: set[str] = set()

        for url, published in self._iter_discovery_entries():
            if url in seen or not _is_article_url(url):
                continue
            seen.add(url)
            discovered += 1

            effective_date = published or _date_from_url(url)
            if from_date is not None and effective_date is not None:
                if effective_date < from_date:
                    continue
            if to_date is not None and effective_date is not None:
                if effective_date > to_date:
                    continue

            yield url
            emitted += 1
            if max_items is not None and emitted >= max_items:
                return

        if discovered == 0:
            raise RuntimeError(
                "Página/12 no devolvió URLs de artículos desde el sitemap ni "
                "desde los feeds RSS oficiales."
            )

    def _iter_discovery_entries(self) -> Iterator[tuple[str, date | None]]:
        """Descubre artículos por sitemap y usa RSS como respaldo estable."""
        sitemap_entries: list[tuple[str, date | None]] = []
        try:
            sitemap_entries = parse_sitemap(self._fetch_text(self._sitemap_url))
        except (ValueError, requests.RequestException, TransientHttpError) as e:
            logger.warning(f"[Pagina12] No se pudo usar el sitemap: {e}")

        valid_sitemap = [item for item in sitemap_entries if _is_article_url(item[0])]
        if valid_sitemap:
            logger.debug(f"[Pagina12] Sitemap: {len(valid_sitemap)} URLs de artículos.")
            yield from valid_sitemap
        else:
            logger.warning(
                "[Pagina12] El sitemap no expuso URLs de artículos; "
                "se continúa con los feeds RSS oficiales."
            )

        for feed_url in _RSS_URLS:
            try:
                feed_entries = parse_rss(self._fetch_text(feed_url))
            except (ValueError, requests.RequestException, TransientHttpError) as e:
                logger.warning(f"[Pagina12] No se pudo usar RSS {feed_url}: {e}")
                continue
            valid_feed = [item for item in feed_entries if _is_article_url(item[0])]
            logger.debug(f"[Pagina12] RSS {feed_url}: {len(valid_feed)} URLs de artículos.")
            yield from valid_feed

    def fetch_discurso(self, url: str) -> DiscursoRecord | None:
        """Descarga una nota y conserva texto y metadata periodística."""
        html = self._fetch_text(url)
        soup = _parse_html(html)
        article = _extract_news_article(soup)
        fusion_content = _extract_fusion_global_content(soup)

        canonical_url = _canonical_url(soup) or url
        titulo = _first_nonempty(
            _as_text(article.get("headline")),
            _meta_content(soup, "property", "og:title"),
            _first_text(soup, ("article h1", "main h1", "h1")),
        )
        contenido = _extract_body(soup, article, fusion_content)

        if not titulo or len(contenido) < 200:
            logger.warning(f"[Pagina12] Nota incompleta o demasiado breve, se omite: {url}")
            return None

        url_date = _date_from_url(canonical_url)
        fecha = _first_nonempty(
            normalize_date(_as_text(article.get("datePublished"))),
            normalize_date(_meta_content(soup, "property", "article:published_time")),
            _extract_time(soup),
            url_date.isoformat() if url_date is not None else "",
        )
        seccion = _first_nonempty(
            _as_text(article.get("articleSection")),
            _meta_content(soup, "property", "article:section"),
            _first_text(soup, _SECTION_SELECTORS),
        )
        volanta = _first_text(soup, _VOLANTA_SELECTORS)
        subtitulo = _first_nonempty(
            _as_text(article.get("description")),
            _meta_content(soup, "name", "description"),
            _meta_content(soup, "property", "og:description"),
            _first_text(soup, _SUBTITLE_SELECTORS),
        )
        autoria = _extract_authors(soup, article)
        epigrafe = _first_nonempty(
            _extract_image_caption(article),
            _first_text(soup, _CAPTION_SELECTORS),
        )
        agencia = _extract_agency(article, autoria, epigrafe)

        extras = (
            ("medio", "Página/12"),
            ("idioma", "es-AR"),
            ("seccion", seccion),
            ("volanta", volanta),
            ("subtitulo", subtitulo),
            ("autoria", json.dumps(autoria, ensure_ascii=False)),
            ("agencia", agencia),
            ("epigrafe", epigrafe),
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
    """Parsea RSS o Atom y devuelve URL y fecha de publicación conocida."""
    try:
        root = ElementTree.fromstring(xml)
    except ElementTree.ParseError as e:
        raise ValueError(f"Feed XML inválido: {e}") from e

    items: list[tuple[str, date | None]] = []
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
        items.append((location, _parse_date(raw_date)))

    for entry in root.findall(".//{*}entry"):
        location = _atom_link(entry)
        if not location:
            continue
        raw_date = (
            _child_text(entry, "published")
            or _child_text(entry, "updated")
            or _child_text(entry, "date")
        )
        items.append((location, _parse_date(raw_date)))
    return items


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


def _extract_news_article(soup: BeautifulSoup) -> dict[str, Any]:
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
                return candidate
    return {}


def _walk_json_ld(value: Any) -> Iterable[dict[str, Any]]:
    if isinstance(value, dict):
        yield value
        graph = value.get("@graph")
        if graph is not None:
            yield from _walk_json_ld(graph)
    elif isinstance(value, list):
        for item in value:
            yield from _walk_json_ld(item)


def _extract_fusion_global_content(soup: BeautifulSoup) -> dict[str, Any]:
    """Recupera el documento ANS embebido por Arc XP en la página."""
    decoder = json.JSONDecoder()
    for script in soup.select("script"):
        raw = script.string or script.get_text()
        if "globalContent" not in raw:
            continue
        for pattern in _FUSION_GLOBAL_CONTENT_PATTERNS:
            for match in pattern.finditer(raw):
                payload = _decode_json_assignment(raw, match.end(), decoder)
                if isinstance(payload, dict):
                    return payload
    return {}


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


def _extract_body(
    soup: BeautifulSoup,
    article: dict[str, Any],
    fusion_content: dict[str, Any],
) -> str:
    structured = _as_text(article.get("articleBody"))
    if len(structured) >= 200:
        return strip_boilerplate(clean_whitespace(structured))

    fusion_body = _extract_ans_body(fusion_content)
    if len(fusion_body) >= 200:
        return fusion_body

    for selector in _BODY_SELECTORS:
        paragraphs = soup.select(selector)
        texts = _paragraph_texts(paragraphs)
        if texts:
            return strip_boilerplate(clean_whitespace("\n\n".join(texts)))
    return ""


def _extract_ans_body(global_content: dict[str, Any]) -> str:
    elements = global_content.get("content_elements")
    if not isinstance(elements, list):
        return ""

    paragraphs: list[str] = []
    for element in elements:
        paragraphs.extend(_ans_element_texts(element))

    return strip_boilerplate(clean_whitespace("\n\n".join(paragraphs)))


def _ans_element_texts(element: Any) -> list[str]:
    if not isinstance(element, dict):
        return []

    element_type = str(element.get("type") or "").casefold()
    if element_type in _ANS_TEXT_ELEMENT_TYPES:
        content = element.get("content")
        if isinstance(content, str):
            return _html_fragment_texts(content)
        return []

    if element_type in {"element_group", "list"}:
        nested = element.get("content_elements")
        if not isinstance(nested, list):
            nested = element.get("items")
        if not isinstance(nested, list):
            return []
        texts: list[str] = []
        for child in nested:
            if isinstance(child, str):
                texts.extend(_html_fragment_texts(child))
            else:
                texts.extend(_ans_element_texts(child))
        return texts

    return []


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


def _extract_authors(
    soup: BeautifulSoup,
    article: dict[str, Any],
) -> tuple[str, ...]:
    authors: list[str] = []
    raw = article.get("author")
    if isinstance(raw, (str, dict)):
        raw = [raw]
    if isinstance(raw, list):
        for item in raw:
            name = _as_text(item.get("name")) if isinstance(item, dict) else _as_text(item)
            _append_unique(authors, _clean_author(name))

    if not authors:
        for selector in _AUTHOR_SELECTORS:
            for element in soup.select(selector):
                _append_unique(
                    authors,
                    _clean_author(element.get_text(separator=" ", strip=True)),
                )
            if authors:
                break

    if not authors:
        _append_unique(authors, _clean_author(_meta_content(soup, "name", "author")))
    return tuple(authors)


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


def _extract_agency(
    article: dict[str, Any],
    authors: tuple[str, ...],
    caption: str,
) -> str:
    for field in ("provider", "sourceOrganization"):
        candidate = article.get(field)
        if isinstance(candidate, dict):
            candidate = candidate.get("name")
        value = _as_text(candidate)
        if value and value.casefold() != "página/12".casefold():
            return value

    searchable = " ".join((*authors, caption))
    for agency in _AGENCY_NAMES:
        if agency.casefold() in searchable.casefold():
            return agency
    if re.search(r"(?:^|[\s/(])NA(?:$|[\s/.)])", searchable):
        return "Noticias Argentinas"
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
