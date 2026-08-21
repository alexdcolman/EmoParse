from __future__ import annotations

import argparse
import csv
import importlib.util
import json
from datetime import date
from pathlib import Path

from emoparse.acquisition.base import DiscursoRecord, SourceAdapter
from emoparse.acquisition.persist import CsvAppender
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
      <a class="c-link p12Author" href="/autores/ana-perez">
        <div class="author-name"><span class="prefix">Por </span><span class="name">Ana Pérez</span></div>
      </a>
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
    # El crédito de una foto no se infiere como agencia de la historia.
    assert payload["agencia"] == ""
    assert payload["epigrafe"].startswith("La escena principal")
    assert record.raw is not None
    assert record.raw["jsonld_article"]["image"]["caption"].endswith("Noticias Argentinas")
    assert "Título periodístico de prueba" in record.raw["dom_paratext"]["header"]["text"]
    assert record.raw["dom_paratext"]["header"]["tag"] == "header"
    assert payload["medio"] == "Página/12"
    assert payload["idioma"] == "es"
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


def test_fetch_article_keeps_short_but_legitimate_body(monkeypatch) -> None:
    long_body = """<div class="article-body">
      <p>Primer párrafo con información suficiente para formar parte del corpus piloto.</p>
      <p>Segundo párrafo con otra voz citada y antecedentes relevantes del caso analizado.</p>
      <p>Tercer párrafo que completa una extensión mínima razonable para la extracción.</p>
    </div>"""
    short_body = '<div class="article-body"><p>Texto breve pero legítimo.</p></div>'
    short_html = ARTICLE_HTML.replace(long_body, short_body)
    adapter = Pagina12Adapter(mode="http")
    monkeypatch.setattr(adapter, "_fetch_text", lambda _url: short_html)

    record = adapter.fetch_discurso("https://www.pagina12.com.ar/example")
    assert record is not None
    assert record.contenido == "Texto breve pero legítimo."
    adapter.close()


def test_fetch_article_omits_page_without_attributable_body(monkeypatch) -> None:
    body = """<div class="article-body">
      <p>Primer párrafo con información suficiente para formar parte del corpus piloto.</p>
      <p>Segundo párrafo con otra voz citada y antecedentes relevantes del caso analizado.</p>
      <p>Tercer párrafo que completa una extensión mínima razonable para la extracción.</p>
    </div>"""
    html = ARTICLE_HTML.replace(body, "")
    adapter = Pagina12Adapter(mode="http")
    monkeypatch.setattr(adapter, "_fetch_text", lambda _url: html)

    assert adapter.fetch_discurso("https://www.pagina12.com.ar/example") is None
    adapter.close()


RSS_FEED = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <item>
      <title>Nota reciente</title>
      <link>https://www.pagina12.com.ar/2026/08/02/nota-reciente/</link>
      <pubDate>Sun, 02 Aug 2026 11:30:00 -0300</pubDate>
      <description>Bajada del feed</description>
      <category>Economía</category>
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


def test_rss_discovery_preserves_entry_metadata_and_section_for_raw(monkeypatch) -> None:
    adapter = Pagina12Adapter(mode="http", sections=["economia"])

    def fake_fetch(url: str) -> str:
        if "outboundfeeds/rss" in url:
            return RSS_FEED
        return ARTICLE_HTML

    monkeypatch.setattr(adapter, "_fetch_text", fake_fetch)
    url = next(adapter.list_discursos(max_items=1))
    record = adapter.fetch_discurso(url)

    assert record is not None
    assert record.raw is not None
    discovery = record.raw["discovery"]
    assert discovery["section"] == "economia"
    assert discovery["section_display"] == "Economía"
    assert discovery["entry"]["title"] == "Nota reciente"
    assert discovery["entry"]["description"] == "Bajada del feed"
    assert discovery["entry"]["categories"] == ["Economía"]
    adapter.close()


def test_rss_section_is_normalized_fallback_when_page_omits_section(monkeypatch) -> None:
    html = (
        ARTICLE_HTML.replace(
            '<meta property="article:section" content="El País">',
            "",
        )
        .replace(
            '    "articleSection": "El País",\n',
            "",
        )
        .replace(
            "      <h5><a>El País</a></h5>\n",
            "",
        )
    )
    adapter = Pagina12Adapter(mode="http", sections=["economia"])

    def fake_fetch(url: str) -> str:
        if "outboundfeeds/rss" in url:
            return RSS_FEED
        return html

    monkeypatch.setattr(adapter, "_fetch_text", fake_fetch)
    url = next(adapter.list_discursos(max_items=1))
    record = adapter.fetch_discurso(url)

    assert record is not None
    assert record.to_dict()["seccion"] == "Economía"
    assert record.raw is not None
    assert record.raw["normalized_provenance"]["seccion"] == "discovery.rss_section"
    adapter.close()


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
      "canonical_url": "https://www.pagina12.com.ar/2026/08/01/nota-fusion/",
      "headlines": {"basic": "Título servido por Arc XP"},
      "publish_date": "2026-08-01T08:00:00-03:00",
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


FUSION_RECIRCULATION_HTML = """<!doctype html>
<html lang="es">
<head>
  <link rel="canonical" href="https://www.pagina12.com.ar/2026/08/01/nota-recirculacion/">
  <meta property="og:title" content="Nota con subtítulos y recirculación">
  <meta name="description" content="Subtítulo general de la nota.">
  <script>
    window.Fusion = window.Fusion || {};
    Fusion.globalContent = {
      "type": "story",
      "canonical_url": "https://www.pagina12.com.ar/2026/08/01/nota-recirculacion/",
      "headlines": {"basic": "Nota con subtítulos y recirculación"},
      "publish_date": "2026-08-01T08:00:00-03:00",
      "content_elements": [
        {
          "type": "text",
          "content": "<p>Primer párrafo genuino del artículo, con información suficiente para verificar que el cuerpo periodístico se conserva.</p>"
        },
        {
          "type": "header",
          "level": 3,
          "content": "Un subtítulo interno legítimo"
        },
        {
          "type": "text",
          "content": "<p>Segundo párrafo genuino que continúa la nota debajo del subtítulo interno y aporta contexto adicional al acontecimiento.</p>"
        },
        {
          "type": "header",
          "level": 3,
          "content": "<li><a href='https://www.pagina12.com.ar/2026/07/31/otra-nota/'>Titular ajeno insertado como recirculación</a></li>"
        },
        {
          "type": "text",
          "content": "<p>Tercer párrafo genuino que debe permanecer aun cuando el módulo de recirculación anterior sea descartado por el extractor.</p>"
        },
        {
          "type": "header",
          "level": 3,
          "content": "Seguí leyendo:"
        },
        {
          "type": "header",
          "level": 3,
          "content": "<li><a href='https://www.pagina12.com.ar/2026/07/31/otra-recomendacion/'>Segundo titular ajeno insertado como recirculación</a></li>"
        },
        {
          "type": "text",
          "content": "<p>Cuarto párrafo genuino posterior al bloque editorial, conservado para comprobar que la extracción retoma el cuerpo normal.</p>"
        }
      ]
    };
  </script>
</head>
<body><main><h1>Nota con subtítulos y recirculación</h1></main></body>
</html>
"""


def test_fetch_article_excludes_ans_recirculation_headers_but_keeps_plain_subtitles(
    monkeypatch,
) -> None:
    adapter = Pagina12Adapter(mode="http")
    monkeypatch.setattr(adapter, "_fetch_text", lambda _url: FUSION_RECIRCULATION_HTML)

    record = adapter.fetch_discurso("https://www.pagina12.com.ar/example")

    assert record is not None
    assert "Primer párrafo genuino" in record.contenido
    assert "Un subtítulo interno legítimo" in record.contenido
    assert "Segundo párrafo genuino" in record.contenido
    assert "Tercer párrafo genuino" in record.contenido
    assert "Cuarto párrafo genuino" in record.contenido
    assert "Titular ajeno insertado" not in record.contenido
    assert "Segundo titular ajeno" not in record.contenido
    assert "Seguí leyendo:" not in record.contenido
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
    html = (
        ARTICLE_HTML.replace(
            '"author": [{"@type": "Person", "name": "Ana Pérez"}],',
            '"author": [],',
        )
        .replace(
            '      <a class="c-link p12Author" href="/autores/ana-perez">\n        <div class="author-name"><span class="prefix">Por </span><span class="name">Ana Pérez</span></div>\n      </a>\n',
            "",
        )
        .replace(
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
    )
    adapter = Pagina12Adapter(mode="http")
    monkeypatch.setattr(adapter, "_fetch_text", lambda _url: html)

    record = adapter.fetch_discurso("https://www.pagina12.com.ar/example")

    assert record is not None
    assert json.loads(record.to_dict()["autoria"]) == ["Luis Bruschtein"]
    adapter.close()


FUSION_STALE_DYNAMIC_DOLLAR_HTML = """<!doctype html>
<html lang="es">
<head>
  <link rel="canonical" href="https://www.pagina12.com.ar/595457-dolar-blue-hoy-dolar-hoy-a-cuanto-cotizan-el-viernes-06-de-o/">
  <meta property="og:title" content="Dólar blue hoy, dólar hoy: a cuánto cotizan el viernes 06 de octubre">
  <meta name="description" content="Dólar blue hoy, dólar hoy: a cuánto cotizan el viernes 24 de mayo">
  <meta property="article:published_time" content="2023-10-06T08:00:00-03:00">
  <script>
    Fusion.globalContent = {
      "type": "story",
      "canonical_url": "https://www.pagina12.com.ar/595457-dolar-blue-hoy-dolar-hoy-a-cuanto-cotizan-el-viernes-06-de-o/",
      "headlines": {"basic": "Dólar blue hoy, dólar hoy: a cuánto cotizan el viernes 06 de octubre"},
      "publish_date": "2023-10-06T08:00:00-03:00",
      "content_elements": [
        {
          "type": "header",
          "content": "Dólar blue hoy, dólar hoy: a cuánto cotizan el viernes 24 de mayo"
        },
        {
          "type": "header",
          "content": "Cotización del dólar blue y el dólar oficial"
        },
        {
          "type": "text",
          "content": "Unsupported div with classes [dolar table-1]"
        },
        {
          "type": "text",
          "content": "<p>El valor del dólar oficial hoy es de $347,02 para la compra y $367,02 para la venta, mientras que la cotización del dólar blue es de $870,00 y $880,00, respectivamente.</p>"
        },
        {
          "type": "text",
          "content": "<p>Respecto del último día hábil, el blue permanece con tendencia alcista y conserva valores coherentes con la publicación histórica del 6 de octubre.</p>"
        }
      ]
    };
  </script>
</head>
<body>
  <main>
    <article>
      <h1>Dólar blue hoy, dólar hoy: a cuánto cotizan el viernes 06 de octubre</h1>
    </article>
    <section class="latest-news">
      <span class="author-name">Autora de otra nota</span>
      <span class="author-name">Autor de recirculación</span>
    </section>
  </main>
</body>
</html>
"""


def test_fetch_article_filters_stale_dynamic_ans_artifacts(monkeypatch) -> None:
    adapter = Pagina12Adapter(mode="http")
    monkeypatch.setattr(adapter, "_fetch_text", lambda _url: FUSION_STALE_DYNAMIC_DOLLAR_HTML)

    record = adapter.fetch_discurso("https://www.pagina12.com.ar/example")

    assert record is not None
    assert "viernes 24 de mayo" not in record.contenido
    assert "Unsupported div with classes" not in record.contenido
    assert "Cotización del dólar blue y el dólar oficial" in record.contenido
    assert "$870,00 y $880,00" in record.contenido
    payload = record.to_dict()
    assert payload["subtitulo"] == ""
    assert json.loads(payload["autoria"]) == []
    adapter.close()


def test_fetch_article_keeps_non_templated_subtitle_with_another_date(monkeypatch) -> None:
    html = ARTICLE_HTML.replace(
        '"description": "Un subtítulo que contextualiza el acontecimiento.",',
        '"description": "El antecedente del 24 de mayo explica el conflicto actual.",',
    ).replace(
        "<h3>Un subtítulo que contextualiza el acontecimiento.</h3>",
        "<h3>El antecedente del 24 de mayo explica el conflicto actual.</h3>",
    )
    adapter = Pagina12Adapter(mode="http")
    monkeypatch.setattr(adapter, "_fetch_text", lambda _url: html)

    record = adapter.fetch_discurso("https://www.pagina12.com.ar/example")

    assert record is not None
    assert record.to_dict()["subtitulo"] == (
        "El antecedente del 24 de mayo explica el conflicto actual."
    )
    adapter.close()


FUSION_LINK_ONLY_AND_CREDITS_HTML = """<!doctype html>
<html lang="es">
<head>
  <link rel="canonical" href="https://www.pagina12.com.ar/2025/05/18/nota-live/">
  <meta property="og:title" content="Elecciones CABA 2025: derrota histórica del PRO en Ciudad">
  <meta name="description" content="Cobertura minuto a minuto de las elecciones porteñas.">
  <meta property="article:published_time" content="2025-05-18T20:53:00-03:00">
  <script type="application/ld+json">
    {
      "@type": "NewsArticle",
      "headline": "Elecciones CABA 2025: derrota histórica del PRO en Ciudad",
      "url": "https://www.pagina12.com.ar/2025/05/18/nota-live/",
      "datePublished": "2025-05-18T20:53:00-03:00",
      "author": [
        {"@type":"Person","name":"Autora lateral 1"},
        {"@type":"Person","name":"Autora lateral 2"},
        {"@type":"Person","name":"Autora lateral 3"},
        {"@type":"Person","name":"Autora lateral 4"},
        {"@type":"Person","name":"Autora lateral 5"}
      ]
    }
  </script>
  <script>
    Fusion.globalContent = {
      "type": "story",
      "canonical_url": "https://www.pagina12.com.ar/2025/05/18/nota-live/",
      "headlines": {"basic": "Elecciones CABA 2025: derrota histórica del PRO en Ciudad"},
      "publish_date": "2025-05-18T20:53:00-03:00",
      "credits": {
        "by": [
          {"type": "author", "name": "Autora Real"}
        ]
      },
      "content_elements": [
        {
          "type": "text",
          "content": "<p>Este domingo se desarrollaron las elecciones legislativas en la Ciudad Autónoma de Buenos Aires, con información suficiente para conformar un cuerpo periodístico válido.</p>"
        },
        {
          "type": "header",
          "content": "Cobertura relacionada"
        },
        {
          "type": "header",
          "content": "<a href='https://www.pagina12.com.ar/otra-cobertura'>EN VIVO. Elecciones CABA 2025: Leandro Santoro espera los resultados</a>"
        },
        {
          "type": "text",
          "content": "<p><a href='https://www.pagina12.com.ar/otra-cobertura-2'>EN VIVO. Elecciones CABA 2025: Adorni aguarda los resultados en el búnker de LLA</a></p>"
        },
        {
          "type": "header",
          "content": "Subtítulo legítimo"
        },
        {
          "type": "text",
          "content": "<p>La cobertura propia continúa aquí con un segundo párrafo genuino que debe permanecer después de filtrar las tarjetas enlazadas.</p>"
        }
      ]
    };
  </script>
</head>
<body>
  <main>
    <h1>Elecciones CABA 2025: derrota histórica del PRO en Ciudad</h1>
    <section class="latest-news">
      <a class="c-link p12Author" href="/autores/autora-lateral-6">
        <div class="author-name"><span class="prefix">Por </span><span class="name">Autora lateral 6</span></div>
      </a>
    </section>
  </main>
</body>
</html>
"""


def test_fetch_article_filters_link_only_ans_cards_and_keeps_plain_header(
    monkeypatch,
) -> None:
    adapter = Pagina12Adapter(mode="http")
    monkeypatch.setattr(adapter, "_fetch_text", lambda _url: FUSION_LINK_ONLY_AND_CREDITS_HTML)

    record = adapter.fetch_discurso("https://www.pagina12.com.ar/example")

    assert record is not None
    assert "Este domingo se desarrollaron" in record.contenido
    assert "Subtítulo legítimo" in record.contenido
    assert "segundo párrafo genuino" in record.contenido
    assert "Cobertura relacionada" not in record.contenido
    assert "Leandro Santoro espera los resultados" not in record.contenido
    assert "Adorni aguarda los resultados" not in record.contenido
    adapter.close()


def test_fetch_article_uses_identity_bound_ans_authors_without_visible_byline(
    monkeypatch,
) -> None:
    adapter = Pagina12Adapter(mode="http")
    monkeypatch.setattr(adapter, "_fetch_text", lambda _url: FUSION_LINK_ONLY_AND_CREDITS_HTML)

    record = adapter.fetch_discurso("https://www.pagina12.com.ar/example")

    assert record is not None
    assert json.loads(record.to_dict()["autoria"]) == ["Autora Real"]
    assert record.raw is not None
    assert record.raw["normalized_provenance"]["autoria"] == "ans_story.credits.by"
    adapter.close()


def test_fetch_article_ignores_implausible_jsonld_author_list_without_other_byline(
    monkeypatch,
) -> None:
    html = FUSION_LINK_ONLY_AND_CREDITS_HTML.replace(
        '"credits": {\n        "by": [\n          {"type": "author", "name": "Autora Real"}\n        ]\n      },',
        '"credits": {"by": []},',
    )
    adapter = Pagina12Adapter(mode="http")
    monkeypatch.setattr(adapter, "_fetch_text", lambda _url: html)

    record = adapter.fetch_discurso("https://www.pagina12.com.ar/example")

    assert record is not None
    assert json.loads(record.to_dict()["autoria"]) == []
    adapter.close()


JSONLD_MULTIPLE_ARTICLES_HTML = """<!doctype html>
<html lang="es"><head>
  <link rel="canonical" href="https://www.pagina12.com.ar/2026/08/15/nota-correcta/">
  <meta property="og:title" content="Título correcto">
  <meta property="article:published_time" content="2026-08-15T12:00:00-03:00">
  <script type="application/ld+json">[
    {"@type":"NewsArticle","headline":"Tarjeta lateral","url":"https://www.pagina12.com.ar/2026/08/15/otra/","datePublished":"2026-08-15T11:00:00-03:00","articleBody":"Texto lateral incorrecto que no debe seleccionarse aunque aparezca primero y tenga longitud suficiente para confundir un extractor ingenuo."},
    {"@type":"NewsArticle","headline":"Título correcto","url":"https://www.pagina12.com.ar/2026/08/15/nota-correcta/","datePublished":"2026-08-15T12:00:00-03:00","articleBody":"Primer párrafo correcto con suficiente desarrollo para funcionar como respaldo estructurado. Segundo párrafo correcto que continúa la nota y supera holgadamente el mínimo de longitud requerido por el adapter."}
  ]</script>
</head><body><main><article><h1>Título correcto</h1></article></main></body></html>
"""


def test_fetch_article_selects_identity_bound_jsonld_candidate(monkeypatch) -> None:
    adapter = Pagina12Adapter(mode="http")
    monkeypatch.setattr(adapter, "_fetch_text", lambda _url: JSONLD_MULTIPLE_ARTICLES_HTML)
    record = adapter.fetch_discurso("https://www.pagina12.com.ar/example")
    assert record is not None
    assert "Primer párrafo correcto" in record.contenido
    assert "Texto lateral incorrecto" not in record.contenido
    adapter.close()


FUSION_MISMATCH_WITH_DOM_FALLBACK_HTML = """<!doctype html>
<html lang="es"><head>
  <link rel="canonical" href="https://www.pagina12.com.ar/2026/08/15/nota-dom/">
  <meta property="og:title" content="Nota DOM correcta">
  <meta property="article:published_time" content="2026-08-15T12:00:00-03:00">
  <script>
    Fusion.globalContent = {
      "type":"story",
      "canonical_url":"https://www.pagina12.com.ar/2026/08/15/otra-nota/",
      "headlines":{"basic":"Otra nota"},
      "publish_date":"2026-08-15T12:00:00-03:00",
      "content_elements":[{"type":"text","content":"<p>Contenido ANS ajeno que nunca debe entrar al registro correcto aunque tenga suficiente extensión para superar cualquier mínimo.</p>"}]
    };
  </script>
</head><body><main><article>
  <h1>Nota DOM correcta</h1>
  <div class="article-body">
    <p>Primer párrafo propio de la nota DOM correcta, con información suficiente para validar el fallback cuando el documento ANS no coincide con la identidad visible.</p>
    <p>Segundo párrafo propio que completa la longitud necesaria y confirma que el contenido ajeno del objeto global fue descartado de forma cerrada.</p>
  </div>
</article></main></body></html>
"""


def test_fetch_article_rejects_mismatched_fusion_and_uses_dom(monkeypatch) -> None:
    adapter = Pagina12Adapter(mode="http")
    monkeypatch.setattr(adapter, "_fetch_text", lambda _url: FUSION_MISMATCH_WITH_DOM_FALLBACK_HTML)
    record = adapter.fetch_discurso("https://www.pagina12.com.ar/example")
    assert record is not None
    assert "Primer párrafo propio" in record.contenido
    assert "Contenido ANS ajeno" not in record.contenido
    adapter.close()


def test_fetch_article_keeps_inline_link_text_but_filters_link_only_card(monkeypatch) -> None:
    html = FUSION_LINK_ONLY_AND_CREDITS_HTML.replace(
        "<p>La cobertura propia continúa aquí con un segundo párrafo genuino que debe permanecer después de filtrar las tarjetas enlazadas.</p>",
        "<p>La cobertura propia continúa con un <a href='/dato'>dato enlazado</a> dentro de un párrafo genuino que debe permanecer y aporta suficiente información adicional sobre los resultados, las reacciones políticas y el contexto electoral para superar con holgura el mínimo del adapter.</p>",
    )
    adapter = Pagina12Adapter(mode="http")
    monkeypatch.setattr(adapter, "_fetch_text", lambda _url: html)
    record = adapter.fetch_discurso("https://www.pagina12.com.ar/example")
    assert record is not None
    assert "dato enlazado" in record.contenido
    assert "Leandro Santoro espera los resultados" not in record.contenido
    adapter.close()


ANS_METADATA_HTML = """<!doctype html>
<html lang="es-AR"><head>
  <link rel="canonical" href="https://www.pagina12.com.ar/2026/08/16/nota-metadata/">
  <meta property="og:title" content="Título metadata">
  <meta property="og:description" content="Descripción SEO distinta de la bajada editorial.">
  <meta property="article:published_time" content="2026-08-16T10:20:00-03:00">
  <meta property="article:section" content="Sección DOM de respaldo">
  <script type="application/ld+json">
  {
    "@type":"NewsArticle",
    "headline":"Título metadata",
    "url":"https://www.pagina12.com.ar/2026/08/16/nota-metadata/",
    "datePublished":"2026-08-16T10:20:00-03:00",
    "description":"Descripción JSON-LD que no es la bajada",
    "articleSection":"Sección JSON-LD",
    "inLanguage":"es",
    "author":{"@type":"Person","name":"Autora JSON"},
    "image":{"@type":"ImageObject","caption":"Epígrafe JSON. Foto: AFP"}
  }
  </script>
  <script>
    Fusion.globalContent = {
      "type":"story",
      "canonical_url":"https://www.pagina12.com.ar/2026/08/16/nota-metadata/",
      "headlines":{"basic":"Título metadata"},
      "subheadlines":{"basic":"Bajada editorial del story"},
      "description":{"basic":"Descripción SEO ANS distinta"},
      "label":{"basic":{"display":true,"text":"Volanta ANS"}},
      "language":"es-AR",
      "created_date":"2026-08-16T09:00:00-03:00",
      "display_date":"2026-08-16T10:20:00-03:00",
      "first_publish_date":"2026-08-16T10:15:00-03:00",
      "publish_date":"2026-08-16T10:20:00-03:00",
      "last_updated_date":"2026-08-16T11:00:00-03:00",
      "taxonomy":{
        "primary_section":{"name":"Economía","_id":"/economia/"},
        "tags":[{"text":"Inflación"}],
        "seo_keywords":["economía","precios"]
      },
      "credits":{"by":[{"type":"author","name":"Ana Autora","org":"Página/12"}]},
      "distributor":{"name":"Reuters","category":"wire"},
      "promo_items":{"basic":{
        "type":"image",
        "caption":"Epígrafe ANS",
        "credits":{"by":[{"name":"Fotógrafa Real"}]},
        "source":{"name":"AFP Photo"}
      }},
      "content_elements":[
        {"type":"text","content":"<p>Primer párrafo sustantivo de la nota con suficiente desarrollo para validar el documento estructurado y sus metadatos editoriales.</p>"},
        {"type":"header","content":"Subtítulo interno legítimo"},
        {"type":"text","content":"<p>Segundo párrafo sustantivo que conserva el contenido periodístico y permite superar holgadamente el mínimo de longitud del adapter.</p>"}
      ]
    };
  </script>
</head><body><main><article>
  <header>
    <h5>Sección DOM</h5><h2>Volanta DOM</h2><h1>Título metadata</h1><h3>Bajada DOM</h3>
  </header>
</article></main></body></html>
"""


def test_fetch_article_uses_identified_ans_story_for_all_normalized_metadata(monkeypatch) -> None:
    adapter = Pagina12Adapter(mode="http")
    monkeypatch.setattr(adapter, "_fetch_text", lambda _url: ANS_METADATA_HTML)

    record = adapter.fetch_discurso("https://www.pagina12.com.ar/2026/08/16/nota-metadata/")

    assert record is not None
    payload = record.to_dict()
    assert payload["seccion"] == "Economía"
    assert payload["volanta"] == "Volanta ANS"
    assert payload["subtitulo"] == "Bajada editorial del story"
    assert json.loads(payload["autoria"]) == ["Ana Autora"]
    assert payload["agencia"] == "Reuters"
    assert payload["epigrafe"] == "Epígrafe ANS"
    assert payload["idioma"] == "es-AR"
    assert "Descripción SEO" not in payload["subtitulo"]
    assert record.raw is not None
    assert record.raw["ans_story"]["taxonomy"]["tags"][0]["text"] == "Inflación"
    assert record.raw["ans_story"]["last_updated_date"].startswith("2026-08-16")
    assert record.raw["ans_story"]["promo_items"]["basic"]["source"]["name"] == "AFP Photo"
    assert record.raw["normalized_provenance"]["seccion"] == "ans_story.taxonomy"
    adapter.close()


def test_non_wire_distributor_is_preserved_raw_but_not_normalized_as_agency(monkeypatch) -> None:
    html = ANS_METADATA_HTML.replace(
        '"distributor":{"name":"Reuters","category":"wire"},',
        '"distributor":{"name":"Proveedor editorial","category":"staff"},',
    )
    adapter = Pagina12Adapter(mode="http")
    monkeypatch.setattr(adapter, "_fetch_text", lambda _url: html)
    record = adapter.fetch_discurso("https://www.pagina12.com.ar/2026/08/16/nota-metadata/")
    assert record is not None
    assert record.to_dict()["agencia"] == ""
    assert record.raw is not None
    assert record.raw["ans_story"]["distributor"]["name"] == "Proveedor editorial"
    adapter.close()


def test_photo_credit_is_not_used_as_story_agency(monkeypatch) -> None:
    html = ANS_METADATA_HTML.replace(
        '"distributor":{"name":"Reuters","category":"wire"},',
        '"distributor":{"name":"Página/12"},',
    )
    adapter = Pagina12Adapter(mode="http")
    monkeypatch.setattr(adapter, "_fetch_text", lambda _url: html)
    record = adapter.fetch_discurso("https://www.pagina12.com.ar/2026/08/16/nota-metadata/")
    assert record is not None
    assert record.to_dict()["agencia"] == ""
    assert record.raw is not None
    assert record.raw["ans_story"]["promo_items"]["basic"]["source"]["name"] == "AFP Photo"
    adapter.close()


def test_invalid_external_canonical_is_not_adopted(monkeypatch) -> None:
    html = ARTICLE_HTML.replace(
        "https://www.pagina12.com.ar/2026/08/02/nota-de-prueba/",
        "https://example.org/otra-cosa",
        1,
    )
    adapter = Pagina12Adapter(mode="http")
    monkeypatch.setattr(adapter, "_fetch_text", lambda _url: html)
    requested = "https://www.pagina12.com.ar/2026/08/02/nota-de-prueba/"
    record = adapter.fetch_discurso(requested)
    assert record is not None
    assert record.url == requested
    adapter.close()


def _rss_for(urls: list[str]) -> str:
    items = "".join(
        f"<item><link>{url}</link><pubDate>Sun, 16 Aug 2026 10:00:00 -0300</pubDate></item>"
        for url in urls
    )
    return f'<?xml version="1.0"?><rss version="2.0"><channel>{items}</channel></rss>'


def test_listing_can_be_restricted_to_multiple_sections_and_is_balanced(monkeypatch) -> None:
    adapter = Pagina12Adapter(mode="http", sections=["Economía", "deportes"])
    calls: list[str] = []
    economy = [
        "https://www.pagina12.com.ar/2026/08/16/economia-uno/",
        "https://www.pagina12.com.ar/2026/08/16/economia-dos/",
    ]
    sports = [
        "https://www.pagina12.com.ar/2026/08/16/deportes-uno/",
        "https://www.pagina12.com.ar/2026/08/16/deportes-dos/",
    ]

    def fake_fetch(url: str) -> str:
        calls.append(url)
        if "/economia/" in url:
            return _rss_for(economy)
        if "/deportes/" in url:
            return _rss_for(sports)
        raise AssertionError(f"Fuente de descubrimiento inesperada: {url}")

    monkeypatch.setattr(adapter, "_fetch_text", fake_fetch)
    urls = list(adapter.list_discursos())

    assert adapter.sections == ("economia", "deportes")
    assert urls == [economy[0], sports[0], economy[1], sports[1]]
    assert len(calls) == 2
    assert all("breakingnews-sitemap" not in call for call in calls)
    adapter.close()


def test_unknown_section_is_rejected_with_public_catalog() -> None:
    import pytest

    with pytest.raises(ValueError, match="Sección de Página/12 desconocida"):
        Pagina12Adapter(mode="http", sections=["inexistente"])


def test_ans_link_group_is_filtered_as_recirculation_without_phrase_blacklist(monkeypatch) -> None:
    html = FUSION_RECIRCULATION_HTML.replace(
        """{
          "type": "header",
          "level": 3,
          "content": "Seguí leyendo:"
        },
        {
          "type": "header",
          "level": 3,
          "content": "<li><a href='https://www.pagina12.com.ar/2026/07/31/otra-recomendacion/'>Segundo titular ajeno insertado como recirculación</a></li>"
        },""",
        """{
          "type":"element_group",
          "content_elements":[
            {"type":"header","content":"También puede interesarte"},
            {"type":"header","content":"<a href='https://www.pagina12.com.ar/2026/07/31/otra-recomendacion/'>Segundo titular ajeno insertado como recirculación</a>"}
          ]
        },""",
    )
    adapter = Pagina12Adapter(mode="http")
    monkeypatch.setattr(adapter, "_fetch_text", lambda _url: html)
    record = adapter.fetch_discurso("https://www.pagina12.com.ar/example")
    assert record is not None
    assert "También puede interesarte" not in record.contenido
    assert "Segundo titular ajeno" not in record.contenido
    assert "Cuarto párrafo genuino" in record.contenido
    adapter.close()


P12_RELEASE_METADATA_HTML = """<!doctype html>
<html lang="es-AR"><head>
  <link rel="canonical" href="https://www.pagina12.com.ar/2026/08/16/release-metadata/">
  <meta property="og:title" content="Título release">
  <meta property="article:published_time" content="2026-08-16T13:00:00-03:00">
  <script type="application/ld+json">
  {"@type":"NewsArticle","headline":"Título release",
   "url":"https://www.pagina12.com.ar/2026/08/16/release-metadata/",
   "datePublished":"2026-08-16T13:00:00-03:00",
   "author":{"@type":"Organization","name":"Página 12"}}
  </script>
  <script>
    Fusion.globalContent = {
      "type":"story",
      "subtype":"web",
      "canonical_url":"https://www.pagina12.com.ar/2026/08/16/release-metadata/",
      "headlines":{"basic":"Título release"},
      "description":{"basic":"Volanta visible del medio"},
      "subheadlines":{"basic":"Bajada editorial distinta"},
      "publish_date":"2026-08-16T13:00:00-03:00",
      "taxonomy":{"primary_section":{"name":"Sociedad","_id":"/sociedad/"}},
      "promo_items":{"basic":{"type":"image","caption":"",
        "subtitle":"Texto descriptivo de la foto",
        "credits":{"by":[{"name":"Crédito Fotográfico"}]}}},
      "content_elements":[
        {"type":"text","content":"<p>Primer párrafo sustantivo del artículo release con información periodística suficiente.</p>"},
        {"type":"text","content":"<p>Segundo párrafo sustantivo que mantiene separado el cuerpo del resto del paratexto.</p>"}
      ]
    };
  </script>
</head><body><main><article><header>
  <h5>Sociedad</h5><h2>Volanta visible del medio</h2><h1>Título release</h1>
  <h3>Bajada editorial distinta</h3>
</header></article></main></body></html>
"""


def test_release_metadata_keeps_overline_subheadline_image_credit_and_publisher_distinct(
    monkeypatch,
) -> None:
    adapter = Pagina12Adapter(mode="http")
    monkeypatch.setattr(adapter, "_fetch_text", lambda _url: P12_RELEASE_METADATA_HTML)

    record = adapter.fetch_discurso("https://www.pagina12.com.ar/2026/08/16/release-metadata/")

    assert record is not None
    payload = record.to_dict()
    assert payload["seccion"] == "Sociedad"
    assert payload["volanta"] == "Volanta visible del medio"
    assert payload["subtitulo"] == "Bajada editorial distinta"
    assert json.loads(payload["autoria"]) == []
    assert payload["epigrafe"] == "Texto descriptivo de la foto"
    assert "Crédito Fotográfico" not in payload["epigrafe"]
    assert record.raw is not None
    assert record.raw["schema"] == "emoparse.pagina12.raw.v2"
    assert record.raw["jsonld_article"]["author"]["name"] == "Página 12"
    assert (
        record.raw["ans_story"]["promo_items"]["basic"]["credits"]["by"][0]["name"]
        == "Crédito Fotográfico"
    )
    assert record.raw["normalized_provenance"]["volanta"].startswith("ans_story.description")
    adapter.close()


P12_DOM_IMAGE_CREDIT_ONLY_HTML = """<!doctype html>
<html lang="es"><head>
  <link rel="canonical" href="https://www.pagina12.com.ar/2026/08/17/credito-solo/">
  <meta property="og:title" content="Nota con crédito sin epígrafe">
  <meta property="article:published_time" content="2026-08-17T12:00:00-03:00">
  <script>
    Fusion.globalContent = {
      "type":"story",
      "canonical_url":"https://www.pagina12.com.ar/2026/08/17/credito-solo/",
      "headlines":{"basic":"Nota con crédito sin epígrafe"},
      "publish_date":"2026-08-17T12:00:00-03:00",
      "taxonomy":{"primary_section":{"name":"El Mundo"}},
      "promo_items":{"basic":{"type":"image","caption":"","subtitle":"",
        "credits":{"by":[{"name":"EFE"}]}}},
      "content_elements":[
        {"type":"text","content":"<p>Párrafo legítimo y suficientemente largo para representar el cuerpo de la nota.</p>"}
      ]
    };
  </script>
</head><body><main><article>
  <h1>Nota con crédito sin epígrafe</h1>
  <figure><figcaption><span class="c-media-item__credit">EFE</span></figcaption></figure>
</article></main></body></html>
"""


P12_DOM_IMAGE_CAPTION_AND_CREDIT_HTML = (
    P12_DOM_IMAGE_CREDIT_ONLY_HTML.replace(
        "credito-solo",
        "caption-y-credito",
    )
    .replace(
        "Nota con crédito sin epígrafe",
        "Nota con caption y crédito",
    )
    .replace(
        '<span class="c-media-item__credit">EFE</span>',
        '<span class="c-media-item__caption">Descripción visible de la foto</span>'
        '<span class="c-media-item__credit">EFE</span>',
    )
)


def test_dom_photo_credit_alone_is_preserved_in_raw_but_never_becomes_epigraph(
    monkeypatch,
) -> None:
    adapter = Pagina12Adapter(mode="http")
    monkeypatch.setattr(adapter, "_fetch_text", lambda _url: P12_DOM_IMAGE_CREDIT_ONLY_HTML)

    record = adapter.fetch_discurso("https://www.pagina12.com.ar/2026/08/17/credito-solo/")

    assert record is not None
    payload = record.to_dict()
    assert payload["epigrafe"] == ""
    assert record.raw is not None
    assert record.raw["ans_story"]["promo_items"]["basic"]["credits"]["by"][0]["name"] == "EFE"
    assert "EFE" in record.raw["dom_paratext"]["figures"][0]["text"]
    assert record.raw["normalized_provenance"]["epigrafe"] == "absent"
    adapter.close()


def test_dom_image_caption_is_kept_while_credit_is_excluded(
    monkeypatch,
) -> None:
    adapter = Pagina12Adapter(mode="http")
    monkeypatch.setattr(adapter, "_fetch_text", lambda _url: P12_DOM_IMAGE_CAPTION_AND_CREDIT_HTML)

    record = adapter.fetch_discurso("https://www.pagina12.com.ar/2026/08/17/caption-y-credito/")

    assert record is not None
    payload = record.to_dict()
    assert payload["epigrafe"] == "Descripción visible de la foto"
    assert "EFE" not in payload["epigrafe"]
    assert record.raw is not None
    assert record.raw["normalized_provenance"]["epigrafe"].startswith(
        "dom.figure.c-media-item__caption"
    )
    adapter.close()


P12_CONTACT_AND_RECIRCULATION_HTML = """<!doctype html>
<html lang="es"><head>
  <link rel="canonical" href="https://www.pagina12.com.ar/2026/08/16/contacto-recirculacion/">
  <meta property="og:title" content="Nota con contacto y relacionados">
  <meta property="article:published_time" content="2026-08-16T12:00:00-03:00">
  <script>
    Fusion.globalContent = {
      "type":"story",
      "canonical_url":"https://www.pagina12.com.ar/2026/08/16/contacto-recirculacion/",
      "headlines":{"basic":"Nota con contacto y relacionados"},
      "publish_date":"2026-08-16T12:00:00-03:00",
      "taxonomy":{"primary_section":{"name":"Cultura"}},
      "content_elements":[
        {"type":"text","content":"<p>Primer párrafo legítimo con suficiente información propia de la nota para formar parte del cuerpo.</p>"},
        {"type":"text","content":"autor.real@pagina12.com.ar"},
        {"type":"text","content":"<b>Seguí leyendo</b>"},
        {"type":"list","items":[{"type":"text","content":"<a href='/2026/08/16/otra/'>Otra noticia relacionada</a>"}]},
        {"type":"header","content":"También puede interesarte"},
        {"type":"element_group","content_elements":[{"type":"text","content":"<a href='/2026/08/16/tercera/'>Tercera nota relacionada</a>"}]},
        {"type":"text","content":"<p>Segundo párrafo legítimo que continúa el desarrollo editorial después de los módulos relacionados.</p>"}
      ]
    };
  </script>
</head><body><main><article><h1>Nota con contacto y relacionados</h1></article></main></body></html>
"""


def test_release_body_classifies_contacts_and_structural_recirculation_without_dropping_raw(
    monkeypatch,
) -> None:
    adapter = Pagina12Adapter(mode="http")
    monkeypatch.setattr(adapter, "_fetch_text", lambda _url: P12_CONTACT_AND_RECIRCULATION_HTML)

    record = adapter.fetch_discurso(
        "https://www.pagina12.com.ar/2026/08/16/contacto-recirculacion/"
    )

    assert record is not None
    assert "Primer párrafo legítimo" in record.contenido
    assert "Segundo párrafo legítimo" in record.contenido
    assert "autor.real@pagina12.com.ar" not in record.contenido
    assert "Seguí leyendo" not in record.contenido
    assert "También puede interesarte" not in record.contenido
    assert "Otra noticia relacionada" not in record.contenido
    assert record.raw is not None
    classified = record.raw["content_classification"]
    roles = [item["role"] for item in classified]
    assert "contact" in roles
    assert roles.count("recirculation_label") == 2
    assert roles.count("recirculation") == 2
    assert any("autor.real@pagina12.com.ar" in item.get("texts", []) for item in classified)
    adapter.close()


P12_EDITORIAL_INDEX_HTML = """<!doctype html>
<html lang="es"><head>
  <link rel="canonical" href="https://www.pagina12.com.ar/2026/08/16/titulos-16-de-agosto/">
  <meta property="og:title" content="Títulos 16 de agosto">
  <meta property="article:published_time" content="2026-08-16T08:00:00-03:00">
  <script>
    Fusion.globalContent = {
      "type":"story",
      "canonical_url":"https://www.pagina12.com.ar/2026/08/16/titulos-16-de-agosto/",
      "headlines":{"basic":"Títulos 16 de agosto"},
      "publish_date":"2026-08-16T08:00:00-03:00",
      "taxonomy":{"primary_section":{"name":"Edición impresa"}},
      "content_elements":[
        {"type":"text","content":"Cabezal con foto"},
        {"type":"text","content":"P. 6/7"},
        {"type":"text","content":"Una tapa importante"},
        {"type":"text","content":"Por Ana Autora"},
        {"type":"text","content":"---------"},
        {"type":"text","content":"P. 12"},
        {"type":"text","content":"Otra nota de la edición"},
        {"type":"text","content":"Por Bruno Autor"}
      ]
    };
  </script>
</head><body><main><article><h1>Títulos 16 de agosto</h1></article></main></body></html>
"""


def test_editorial_index_is_preserved_but_does_not_count_as_article(monkeypatch) -> None:
    adapter = Pagina12Adapter(mode="http")
    monkeypatch.setattr(adapter, "_fetch_text", lambda _url: P12_EDITORIAL_INDEX_HTML)

    record = adapter.fetch_discurso("https://www.pagina12.com.ar/2026/08/16/titulos-16-de-agosto/")

    assert record is not None
    assert record.to_dict()["tipo_documento"] == "indice_editorial"
    assert adapter.counts_toward_max(record) is False
    assert record.raw is not None
    assert record.raw["document_classification"]["reason"] == "editorial_layout"
    assert record.raw["ans_story"]["content_elements"][0]["content"] == "Cabezal con foto"
    adapter.close()


def test_normal_story_counts_toward_article_limit(monkeypatch) -> None:
    adapter = Pagina12Adapter(mode="http")
    monkeypatch.setattr(adapter, "_fetch_text", lambda _url: P12_RELEASE_METADATA_HTML)
    record = adapter.fetch_discurso("https://www.pagina12.com.ar/2026/08/16/release-metadata/")
    assert record is not None
    assert record.to_dict()["tipo_documento"] == "articulo"
    assert adapter.counts_toward_max(record) is True
    adapter.close()


def test_requested_empty_rss_section_is_visible_in_diagnostics_without_sitemap_fallback(
    monkeypatch,
) -> None:
    adapter = Pagina12Adapter(mode="http", sections=["economia", "cultura"])
    empty_feed = "<?xml version='1.0'?><rss><channel></channel></rss>"

    def fake_fetch(url: str) -> str:
        if "/economia/" in url:
            return RSS_FEED
        if "/suplementos/cultura-y-espectaculos/notas" in url:
            return empty_feed
        raise AssertionError(f"No debe consultar sitemap con secciones explícitas: {url}")

    monkeypatch.setattr(adapter, "_fetch_text", fake_fetch)
    urls = list(adapter.list_discursos(max_items=1))
    assert urls == ["https://www.pagina12.com.ar/2026/08/02/nota-reciente/"]
    diagnostics = adapter.discovery_diagnostics
    assert diagnostics["economia"]["status"] == "ok"
    assert diagnostics["economia"]["article_urls"] == 2
    assert diagnostics["cultura"]["status"] == "ok"
    assert diagnostics["cultura"]["article_urls"] == 0
    assert diagnostics["cultura"]["feed_label"] == "Espectáculos"
    assert diagnostics["cultura"]["feed_url"].endswith(
        "/arc/outboundfeeds/rss/suplementos/cultura-y-espectaculos/notas"
    )
    adapter.close()


def test_cultura_and_espectaculos_aliases_use_active_official_feed(monkeypatch) -> None:
    adapter = Pagina12Adapter(
        mode="http",
        sections=["cultura", "espectaculos", "cultura-y-espectaculos"],
    )
    seen: list[str] = []

    def fake_fetch(url: str) -> str:
        seen.append(url)
        assert url.endswith("/arc/outboundfeeds/rss/suplementos/cultura-y-espectaculos/notas")
        return RSS_FEED

    monkeypatch.setattr(adapter, "_fetch_text", fake_fetch)
    urls = list(adapter.list_discursos(max_items=1))

    assert adapter.sections == ("cultura",)
    assert len(seen) == 1
    assert urls == ["https://www.pagina12.com.ar/2026/08/02/nota-reciente/"]
    diagnostics = adapter.discovery_diagnostics["cultura"]
    assert diagnostics["section_display"] == "Cultura"
    assert diagnostics["feed_label"] == "Espectáculos"
    assert diagnostics["article_urls"] == 2
    adapter.close()


def _raw_record(*, raw: dict[str, object] | None = None, kind: str = "articulo") -> DiscursoRecord:
    return DiscursoRecord(
        codigo="doc-1",
        url="https://example.test/doc-1",
        titulo="Título",
        fecha="2026-08-16",
        contenido="Contenido",
        fuente="fixture",
        extras=(("autoria", '["Ana"]'), ("tipo_documento", kind)),
        raw=raw,
    )


def test_discurso_record_raw_is_preserved_but_not_part_of_identity() -> None:
    first = _raw_record(raw={"story": {"tags": ["a"]}})
    second = _raw_record(raw={"story": {"tags": ["b"]}})
    assert first == second
    assert hash(first) == hash(second)
    assert first.to_dict()["raw"] == {"story": {"tags": ["a"]}}


def test_discurso_record_without_raw_keeps_legacy_dict_shape() -> None:
    assert "raw" not in _raw_record(raw=None).to_dict()


def test_csv_appender_serializes_and_reopens_large_raw_snapshot(tmp_path) -> None:
    path = tmp_path / "records.csv"
    raw = {"schema": "fixture.v1", "ans_story": {"blob": "x" * 250_000}}
    CsvAppender(path).append(_raw_record(raw=raw))
    reopened = CsvAppender(path)
    assert reopened.has_url("https://example.test/doc-1")
    csv.field_size_limit(1_000_000)
    with path.open(encoding="utf-8-sig", newline="") as fh:
        row = next(csv.DictReader(fh))
    assert json.loads(row["raw"]) == raw
    assert json.loads(row["autoria"]) == ["Ana"]


def _load_scrape_cmd_module():
    path = Path(__file__).parents[2] / "src/emoparse/cli/commands/scrape_cmd.py"
    spec = importlib.util.spec_from_file_location("scrape_cmd_release_under_test", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _FakePagina12WithAuxiliary(SourceAdapter):
    source_id = "pagina12"

    def __init__(self) -> None:
        self.fetch_count = 0
        self.list_max_items: int | None | object = object()

    def list_discursos(self, *, max_items=None, from_date=None, to_date=None):
        self.list_max_items = max_items
        for index in range(80):
            yield f"https://www.pagina12.com.ar/2026/08/16/nota-{index}/"

    def fetch_discurso(self, url: str) -> DiscursoRecord | None:
        self.fetch_count += 1
        if self.fetch_count <= 3:
            return None
        kind = "indice_editorial" if self.fetch_count in {5, 9} else "articulo"
        return DiscursoRecord(
            codigo=f"p12-{self.fetch_count}",
            url=url,
            titulo=f"Nota {self.fetch_count}",
            fecha="2026-08-16",
            contenido="Párrafo suficientemente largo para el fixture.",
            fuente="pagina12",
            extras=(("tipo_documento", kind),),
        )

    def counts_toward_max(self, record: DiscursoRecord) -> bool:
        return record.to_dict().get("tipo_documento") == "articulo"


def test_scrape_max_counts_real_articles_and_preserves_auxiliary_documents(
    monkeypatch, tmp_path
) -> None:
    scrape_cmd = _load_scrape_cmd_module()
    adapter = _FakePagina12WithAuxiliary()
    captured: dict[str, object] = {}

    def fake_get_source(source_id: str, **kwargs: object) -> SourceAdapter:
        captured["source_id"] = source_id
        captured.update(kwargs)
        return adapter

    monkeypatch.setattr(scrape_cmd, "get_source", fake_get_source)
    args = argparse.Namespace(
        source="pagina12",
        output=tmp_path / "out.csv",
        max=40,
        from_date=None,
        to_date=None,
        max_after_filter=False,
        mode="http",
        timeout=20.0,
        section=["economia,deportes"],
        subtype=None,
    )
    rc = scrape_cmd.run(args)
    assert rc == 0
    assert adapter.list_max_items is None
    assert captured["sections"] == ("economia", "deportes")
    with (tmp_path / "out.csv").open(encoding="utf-8-sig", newline="") as fh:
        rows = list(csv.DictReader(fh))
    article_rows = [r for r in rows if r.get("tipo_documento") == "articulo"]
    auxiliary_rows = [r for r in rows if r.get("tipo_documento") == "indice_editorial"]
    assert len(article_rows) == 40
    assert len(auxiliary_rows) == 2
    assert len(rows) == 42


def test_section_option_is_rejected_for_other_sources(tmp_path) -> None:
    scrape_cmd = _load_scrape_cmd_module()
    args = argparse.Namespace(
        source="casarosada",
        output=tmp_path / "out.csv",
        max=1,
        from_date=None,
        to_date=None,
        max_after_filter=False,
        mode="http",
        timeout=20.0,
        section=["economia"],
        subtype=None,
    )
    assert scrape_cmd.run(args) == 2


P12_LBP_HTML = r"""<!doctype html>
<html lang="es-AR">
<head>
  <link rel="canonical" href="https://www.pagina12.com.ar/2026/08/19/live-blog-prueba/">
  <meta property="article:published_time" content="2026-08-19T11:50:00-03:00">
  <script type="application/ld+json">
  {
    "@context":"https://schema.org",
    "@type":"NewsArticle",
    "url":"https://www.pagina12.com.ar/2026/08/19/live-blog-prueba/",
    "headline":"Live blog de prueba",
    "datePublished":"2026-08-19T11:50:00-03:00"
  }
  </script>
  <script>
    Fusion.globalContent = {
      "_id":"PARENT-LBP",
      "type":"story",
      "subtype":"lbp_article",
      "canonical_url":"https://www.pagina12.com.ar/2026/08/19/live-blog-prueba/",
      "headlines":{"basic":"Live blog de prueba"},
      "description":{"basic":"Cobertura en vivo"},
      "subheadlines":{"basic":"Actualizaciones de la jornada"},
      "display_date":"2026-08-19T14:50:00Z",
      "publish_date":"2026-08-19T14:50:00Z",
      "taxonomy":{"primary_section":{"name":"Economía"}},
      "content_elements":[
        {"_id":"PARENT-TEXT","type":"text","content":"Introducción legítima del vivo."},
        {"_id":"PARENT-IFRAME","type":"raw_html","content":"<iframe src='x'></iframe>"},
        {"_id":"PARENT-LBP-EMBED","type":"custom_embed","subtype":"Live Blog Post","embed":{"config":{"title":"LBP"}}}
      ],
      "LBPList":[
        {
          "_id":"UPDATE-2","type":"story","subtype":"lbp_update",
          "headlines":{"basic":"Actualización más reciente"},
          "display_date":"2026-08-19T17:20:00Z",
          "publish_date":"2026-08-19T17:21:00Z",
          "content_elements":[
            {"type":"text","content":"Por Ana Autora"},
            {"type":"text","content":"Texto de la actualización más reciente."},
            {"type":"raw_html","content":"<div>embed no analítico</div>"}
          ]
        },
        {
          "_id":"UPDATE-1","type":"story","subtype":"lbp_update",
          "headlines":{"basic":"Actualización anterior"},
          "display_date":"2026-08-19T16:40:00Z",
          "publish_date":"2026-08-19T16:41:00Z",
          "content_elements":[
            {"type":"text","content":"Texto de la actualización anterior."}
          ]
        }
      ]
    };
  </script>
</head>
<body><main><article>
<header><h5>Economía</h5><h2>Cobertura en vivo</h2><h1>Live blog de prueba</h1><h3>Actualizaciones de la jornada</h3></header>
</article></main></body>
</html>"""


def test_article_subtype_defaults_to_static_for_regular_story(monkeypatch) -> None:
    adapter = Pagina12Adapter(mode="http")
    monkeypatch.setattr(adapter, "_fetch_text", lambda _url: P12_RELEASE_METADATA_HTML)

    record = adapter.fetch_discurso("https://www.pagina12.com.ar/2026/08/16/release-metadata/")

    assert record is not None
    payload = record.to_dict()
    assert payload["subtipo_articulo"] == "static"
    assert payload["subtipo_fuente"] == "web"
    assert record.raw is not None
    assert record.raw["document_classification"]["subtipo_articulo"] == "static"
    assert record.raw["live_blog"] is None
    adapter.close()


def test_lbp_article_extracts_parent_and_updates_in_source_order(monkeypatch) -> None:
    adapter = Pagina12Adapter(mode="http")
    monkeypatch.setattr(adapter, "_fetch_text", lambda _url: P12_LBP_HTML)

    record = adapter.fetch_discurso("https://www.pagina12.com.ar/2026/08/19/live-blog-prueba/")

    assert record is not None
    payload = record.to_dict()
    assert payload["subtipo_articulo"] == "lbp_article"
    assert payload["subtipo_fuente"] == "lbp_article"
    assert payload["tipo_documento"] == "articulo"
    assert record.contenido.split("\n\n") == [
        "Introducción legítima del vivo.",
        "Actualización más reciente",
        "Texto de la actualización más reciente.",
        "Actualización anterior",
        "Texto de la actualización anterior.",
    ]
    assert "Por Ana Autora" not in record.contenido
    assert "embed no analítico" not in record.contenido

    assert record.raw is not None
    live_blog = record.raw["live_blog"]
    assert live_blog["update_count"] == 2
    assert [item["id"] for item in live_blog["updates"]] == ["UPDATE-2", "UPDATE-1"]
    assert live_blog["source_order"] == "LBPList"
    roles = [item["role"] for item in record.raw["content_classification"]]
    assert "update_headline" in roles
    assert "byline_paratext" in roles
    assert "embedded_media" in roles
    adapter.close()


def test_subtype_filter_accepts_static_lbp_or_both(monkeypatch) -> None:
    static_adapter = Pagina12Adapter(mode="http", subtypes=["static"])
    monkeypatch.setattr(static_adapter, "_fetch_text", lambda _url: P12_RELEASE_METADATA_HTML)
    static_record = static_adapter.fetch_discurso(
        "https://www.pagina12.com.ar/2026/08/16/release-metadata/"
    )
    assert static_record is not None
    assert static_adapter.accepts_record(static_record) is True

    lbp_adapter = Pagina12Adapter(mode="http", subtypes=["lbp_article"])
    monkeypatch.setattr(lbp_adapter, "_fetch_text", lambda _url: P12_LBP_HTML)
    lbp_record = lbp_adapter.fetch_discurso(
        "https://www.pagina12.com.ar/2026/08/19/live-blog-prueba/"
    )
    assert lbp_record is not None
    assert lbp_adapter.accepts_record(lbp_record) is True
    assert static_adapter.accepts_record(lbp_record) is False
    assert lbp_adapter.accepts_record(static_record) is False

    both = Pagina12Adapter(mode="http", subtypes=["estatico,lbp"])
    assert both.subtypes == ("static", "lbp_article")
    assert both.accepts_record(static_record) is True
    assert both.accepts_record(lbp_record) is True
    static_adapter.close()
    lbp_adapter.close()
    both.close()


def test_unknown_subtype_is_rejected() -> None:
    try:
        Pagina12Adapter(mode="http", subtypes=["video"])
    except ValueError as exc:
        assert "Subtipo de Página/12 desconocido" in str(exc)
        assert "static" in str(exc)
        assert "lbp_article" in str(exc)
    else:
        raise AssertionError("El adapter debía rechazar un subtipo desconocido")


class _FakePagina12SubtypeFilter(SourceAdapter):
    source_id = "pagina12"

    def __init__(self) -> None:
        self.fetch_count = 0

    def list_discursos(self, *, max_items=None, from_date=None, to_date=None):
        for index in range(20):
            yield f"https://www.pagina12.com.ar/2026/08/19/subtype-{index}/"

    def fetch_discurso(self, url: str) -> DiscursoRecord:
        self.fetch_count += 1
        subtype = "lbp_article" if self.fetch_count % 2 else "static"
        return DiscursoRecord(
            codigo=f"doc-{self.fetch_count}",
            url=url,
            titulo=f"Nota {self.fetch_count}",
            fecha="2026-08-19",
            contenido="Contenido legítimo de la nota.",
            fuente="pagina12",
            extras=(
                ("tipo_documento", "articulo"),
                ("subtipo_articulo", subtype),
            ),
        )

    def accepts_record(self, record: DiscursoRecord) -> bool:
        return record.to_dict().get("subtipo_articulo") == "lbp_article"


def test_scrape_subtype_filter_skips_without_consuming_max(monkeypatch, tmp_path) -> None:
    scrape_cmd = _load_scrape_cmd_module()
    adapter = _FakePagina12SubtypeFilter()
    captured: dict[str, object] = {}

    def fake_get_source(source_id: str, **kwargs: object) -> SourceAdapter:
        captured["source_id"] = source_id
        captured.update(kwargs)
        return adapter

    monkeypatch.setattr(scrape_cmd, "get_source", fake_get_source)
    args = argparse.Namespace(
        source="pagina12",
        output=tmp_path / "out.csv",
        max=3,
        from_date=None,
        to_date=None,
        max_after_filter=False,
        mode="http",
        timeout=20.0,
        section=None,
        subtype=["lbp_article"],
    )

    assert scrape_cmd.run(args) == 0
    assert captured["subtypes"] == ("lbp_article",)
    with (tmp_path / "out.csv").open(encoding="utf-8-sig", newline="") as fh:
        rows = list(csv.DictReader(fh))
    assert len(rows) == 3
    assert {row["subtipo_articulo"] for row in rows} == {"lbp_article"}
    assert adapter.fetch_count == 5


def test_subtype_option_is_rejected_for_other_sources(tmp_path) -> None:
    scrape_cmd = _load_scrape_cmd_module()
    args = argparse.Namespace(
        source="casarosada",
        output=tmp_path / "out.csv",
        max=1,
        from_date=None,
        to_date=None,
        max_after_filter=False,
        mode="http",
        timeout=20.0,
        section=None,
        subtype=["lbp_article"],
    )
    assert scrape_cmd.run(args) == 2
