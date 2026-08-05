from __future__ import annotations

import json
from datetime import date

from emoparse.acquisition.sources import SOURCES
from emoparse.acquisition.sources.pagina12 import Pagina12Adapter, parse_sitemap

SITEMAP = """<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"
        xmlns:news="http://www.google.com/schemas/sitemap-news/0.9">
  <url>
    <loc>https://www.pagina12.com.ar/2026/08/02/nota-reciente/</loc>
    <news:news><news:publication_date>2026-08-02T11:30:00-03:00</news:publication_date></news:news>
  </url>
  <url>
    <loc>https://www.pagina12.com.ar/2026/08/01/nota-anterior/</loc>
    <lastmod>2026-08-01T09:00:00-03:00</lastmod>
  </url>
  <url>
    <loc>https://www.pagina12.com.ar/archivo/</loc>
  </url>
</urlset>
"""


ARTICLE_HTML = """<!doctype html>
<html lang="es">
<head>
  <link rel="canonical" href="https://www.pagina12.com.ar/2026/08/02/nota-de-prueba/">
  <meta property="article:section" content="El País">
  <script type="application/ld+json">
  {
    "@context": "https://schema.org",
    "@type": "NewsArticle",
    "headline": "Título periodístico de prueba",
    "description": "Un subtítulo que contextualiza el acontecimiento.",
    "datePublished": "2026-08-02T08:30:00-03:00",
    "articleSection": "El País",
    "author": [{"@type": "Person", "name": "Ana Pérez"}],
    "image": {"@type": "ImageObject", "caption": "La escena principal. Noticias Argentinas"}
  }
  </script>
</head>
<body>
  <main><article>
    <header>
      <h5><a>El País</a></h5>
      <h2>Una volanta informativa</h2>
      <h1>Título periodístico de prueba</h1>
      <h3>Un subtítulo que contextualiza el acontecimiento.</h3>
    </header>
    <div class="article-body">
      <p>Primer párrafo con información suficiente para formar parte del corpus piloto.</p>
      <p>Segundo párrafo con otra voz citada y antecedentes relevantes del caso analizado.</p>
      <p>Tercer párrafo que completa una extensión mínima razonable para la extracción.</p>
    </div>
  </article></main>
</body>
</html>
"""


def test_pagina12_source_is_registered() -> None:
    assert SOURCES["pagina12"] is Pagina12Adapter


def test_parse_sitemap_reads_namespaced_publication_dates() -> None:
    items = parse_sitemap(SITEMAP)

    assert items[0] == (
        "https://www.pagina12.com.ar/2026/08/02/nota-reciente/",
        date(2026, 8, 2),
    )
    assert items[1][1] == date(2026, 8, 1)


def test_listing_filters_by_date_before_applying_max(monkeypatch) -> None:
    adapter = Pagina12Adapter(mode="http")
    monkeypatch.setattr(adapter, "_fetch_text", lambda _url: SITEMAP)

    urls = list(
        adapter.list_discursos(
            max_items=1,
            from_date=date(2026, 8, 1),
            to_date=date(2026, 8, 1),
        )
    )

    assert urls == ["https://www.pagina12.com.ar/2026/08/01/nota-anterior/"]
    adapter.close()


def test_fetch_article_preserves_journalistic_metadata(monkeypatch) -> None:
    adapter = Pagina12Adapter(mode="http")
    monkeypatch.setattr(adapter, "_fetch_text", lambda _url: ARTICLE_HTML)

    record = adapter.fetch_discurso("https://www.pagina12.com.ar/example")

    assert record is not None
    assert record.codigo == "pagina12_20260802_nota-de-prueba"
    assert record.titulo == "Título periodístico de prueba"
    assert record.fecha == "2026-08-02"
    assert "Primer párrafo" in record.contenido
    assert "\n\n" in record.contenido

    payload = record.to_dict()
    assert payload["seccion"] == "El País"
    assert payload["volanta"] == "Una volanta informativa"
    assert payload["subtitulo"].startswith("Un subtítulo")
    assert json.loads(payload["autoria"]) == ["Ana Pérez"]
    assert payload["agencia"] == "Noticias Argentinas"
    assert payload["epigrafe"].startswith("La escena principal")
    assert payload["medio"] == "Página/12"
    assert payload["idioma"] == "es-AR"
    adapter.close()


def test_fetch_article_prefers_paragraph_structure_over_flat_json_ld(monkeypatch) -> None:
    flattened = ARTICLE_HTML.replace(
        '"description": "Un subtítulo que contextualiza el acontecimiento.",',
        '"description": "Un subtítulo que contextualiza el acontecimiento.",\n'
        '    "articleBody": "Primer párrafo con información suficiente para formar parte '
        "del corpus piloto. Segundo párrafo con otra voz citada y antecedentes relevantes "
        "del caso analizado. Tercer párrafo que completa una extensión mínima razonable "
        'para la extracción.",',
    )
    adapter = Pagina12Adapter(mode="http")
    monkeypatch.setattr(adapter, "_fetch_text", lambda _url: flattened)

    record = adapter.fetch_discurso("https://www.pagina12.com.ar/example")

    assert record is not None
    assert record.contenido.count("\n\n") == 2
    adapter.close()


def test_fetch_article_omits_bodies_too_short_for_the_pilot(monkeypatch) -> None:
    long_body = """<div class="article-body">
      <p>Primer párrafo con información suficiente para formar parte del corpus piloto.</p>
      <p>Segundo párrafo con otra voz citada y antecedentes relevantes del caso analizado.</p>
      <p>Tercer párrafo que completa una extensión mínima razonable para la extracción.</p>
    </div>"""
    short_body = '<div class="article-body"><p>Texto breve.</p></div>'
    short_html = ARTICLE_HTML.replace(long_body, short_body)
    adapter = Pagina12Adapter(mode="http")
    monkeypatch.setattr(adapter, "_fetch_text", lambda _url: short_html)

    assert adapter.fetch_discurso("https://www.pagina12.com.ar/example") is None
    adapter.close()


RSS_FEED = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <item>
      <title>Nota reciente</title>
      <link>https://www.pagina12.com.ar/2026/08/02/nota-reciente/</link>
      <pubDate>Sun, 02 Aug 2026 11:30:00 -0300</pubDate>
    </item>
    <item>
      <title>Nota anterior en URL histórica</title>
      <link>https://www.pagina12.com.ar/873421-nota-anterior</link>
      <pubDate>Sat, 01 Aug 2026 09:00:00 -0300</pubDate>
    </item>
  </channel>
</rss>
"""

EMPTY_SITEMAP_INDEX = """<?xml version="1.0" encoding="UTF-8"?>
<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <sitemap>
    <loc>https://www.pagina12.com.ar/arc/outboundfeeds/otro-sitemap.xml</loc>
  </sitemap>
</sitemapindex>
"""


def test_parse_rss_reads_rfc822_dates() -> None:
    from emoparse.acquisition.sources.pagina12 import parse_rss

    items = parse_rss(RSS_FEED)

    assert items == [
        (
            "https://www.pagina12.com.ar/2026/08/02/nota-reciente/",
            date(2026, 8, 2),
        ),
        (
            "https://www.pagina12.com.ar/873421-nota-anterior",
            date(2026, 8, 1),
        ),
    ]


def test_listing_falls_back_to_official_rss(monkeypatch) -> None:
    adapter = Pagina12Adapter(mode="http")

    def fake_fetch(url: str) -> str:
        if url.endswith("breakingnews-sitemap.xml"):
            return EMPTY_SITEMAP_INDEX
        return RSS_FEED

    monkeypatch.setattr(adapter, "_fetch_text", fake_fetch)

    urls = list(
        adapter.list_discursos(
            max_items=2,
            from_date=date(2026, 8, 1),
            to_date=date(2026, 8, 2),
        )
    )

    assert urls == [
        "https://www.pagina12.com.ar/2026/08/02/nota-reciente/",
        "https://www.pagina12.com.ar/873421-nota-anterior",
    ]
    adapter.close()


FUSION_ARTICLE_HTML = """<!doctype html>
<html lang="es">
<head>
  <link rel="canonical" href="https://www.pagina12.com.ar/2026/08/01/nota-fusion/">
  <meta property="og:title" content="Título servido por Arc XP">
  <meta name="description" content="Subtítulo servido en el encabezado.">
  <script>
    window.Fusion = window.Fusion || {};
    Fusion.globalContent = {
      "type": "story",
      "content_elements": [
        {
          "type": "text",
          "content": "<p>Primer párrafo recuperado desde el documento ANS embebido por Arc XP, con información suficiente para comprobar la extracción.</p>"
        },
        {
          "type": "text",
          "content": "<p>Segundo párrafo del artículo periodístico, que conserva el orden editorial y amplía el cuerpo por encima del mínimo requerido.</p>"
        },
        {
          "type": "interstitial_link",
          "content": "Esta recomendación no pertenece al cuerpo de la nota."
        },
        {
          "type": "text",
          "content": "<p>Tercer párrafo utilizado para verificar que los elementos promocionales o relacionados no contaminan el corpus.</p>"
        }
      ]
    };
    Fusion.globalContentConfig = {"source": "content-api"};
  </script>
</head>
<body>
  <main>
    <div class="article-wrapper">
      <h1>Título servido por Arc XP</h1>
      <h3>Subtítulo servido en el encabezado.</h3>
    </div>
  </main>
</body>
</html>
"""


def test_fetch_article_extracts_body_from_fusion_global_content(monkeypatch) -> None:
    adapter = Pagina12Adapter(mode="http")
    monkeypatch.setattr(adapter, "_fetch_text", lambda _url: FUSION_ARTICLE_HTML)

    record = adapter.fetch_discurso("https://www.pagina12.com.ar/example")

    assert record is not None
    assert "Primer párrafo recuperado" in record.contenido
    assert "Segundo párrafo del artículo" in record.contenido
    assert "Tercer párrafo utilizado" in record.contenido
    assert "Esta recomendación" not in record.contenido
    assert record.contenido.count("\n\n") == 2
    adapter.close()


def test_invalid_fusion_payload_keeps_html_fallback(monkeypatch) -> None:
    broken = ARTICLE_HTML.replace(
        "</head>",
        "<script>Fusion.globalContent = {contenido: inválido};</script></head>",
    )
    adapter = Pagina12Adapter(mode="http")
    monkeypatch.setattr(adapter, "_fetch_text", lambda _url: broken)

    record = adapter.fetch_discurso("https://www.pagina12.com.ar/example")

    assert record is not None
    assert "Primer párrafo" in record.contenido
    adapter.close()


def test_fetch_article_reads_current_p12_author_markup(monkeypatch) -> None:
    html = ARTICLE_HTML.replace(
        '"author": [{"@type": "Person", "name": "Ana Pérez"}],',
        '"author": [],',
    ).replace(
        '<div class="article-body">',
        """<div class="left-content">
          <a class="c-link p12Author" href="/autores/luis-bruschtein">
            <div class="author-name">
              <span class="prefix">Por </span>
              <span class="name">Luis Bruschtein</span>
            </div>
          </a>
        </div>
        <div class="article-body">""",
        1,
    )
    adapter = Pagina12Adapter(mode="http")
    monkeypatch.setattr(adapter, "_fetch_text", lambda _url: html)

    record = adapter.fetch_discurso("https://www.pagina12.com.ar/example")

    assert record is not None
    assert json.loads(record.to_dict()["autoria"]) == ["Luis Bruschtein"]
    adapter.close()
