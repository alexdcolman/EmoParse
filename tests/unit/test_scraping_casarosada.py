# ══════════════════════════════════════════════════════════════════════════════
#  tests/unit/test_scraping_casarosada.py
#
#  Tests del adapter Casa Rosada usando HTML fixtures (sin red).
# ══════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

from datetime import date

import pytest

from emoparse.acquisition.sources.casarosada import CasaRosadaAdapter


# ══════════════════════════════════════════════════════════════════════════════
#  Fixtures de HTML
# ══════════════════════════════════════════════════════════════════════════════

LISTING_PAGE_1 = """
<!DOCTYPE html><html><head><title>Discursos</title></head><body>
<main>
  <a href="/informacion/discursos/12345-discurso-uno">Discurso uno</a>
  <a href="/informacion/discursos/12346-discurso-dos">Discurso dos</a>
  <a href="/informacion/discursos">link al propio listado, ignorar</a>
  <ul class="pagination">
    <li class="pagination-next">
      <a href="/informacion/discursos?page=2">Siguiente</a>
    </li>
  </ul>
</main>
</body></html>
"""

LISTING_PAGE_2 = """
<!DOCTYPE html><html><body>
<main>
  <a href="/informacion/discursos/12347-discurso-tres">Discurso tres</a>
</main>
</body></html>
"""

DISCURSO_PAGE = """
<!DOCTYPE html><html><body>
<article>
  <h2>Palabras del Presidente en el acto de inauguración</h2>
  <time datetime="2024-12-15T10:30:00-03:00">15 de diciembre de 2024</time>
  <p>Buenas tardes a todos. Hoy es un día importante para la Argentina.</p>
  <p>Quiero agradecer a todos los presentes.</p>
  <p>Estamos comprometidos con el futuro del país.</p>
</article>
</body></html>
"""

DISCURSO_VACIO = """
<!DOCTYPE html><html><body>
<article>
  <h1>Título solo</h1>
  <time datetime="2024-12-15">15-12-2024</time>
</article>
</body></html>
"""


# ══════════════════════════════════════════════════════════════════════════════
#  Fixture: adapter mockeable
# ══════════════════════════════════════════════════════════════════════════════

class _MockedAdapter(CasaRosadaAdapter):
    """CasaRosadaAdapter con `_fetch_html` mockeado por un mapa URL→HTML."""

    def __init__(self, html_by_url: dict[str, str], **kwargs: object) -> None:
        super().__init__(**kwargs)
        self._html_by_url = html_by_url
        self.fetch_calls: list[str] = []

    def _fetch_html(self, url: str) -> str:
        self.fetch_calls.append(url)
        return self._html_by_url.get(url, "")


# ══════════════════════════════════════════════════════════════════════════════
#  Listado y paginación
# ══════════════════════════════════════════════════════════════════════════════

def test_list_discursos_devuelve_links_de_la_primera_pagina() -> None:
    base = "https://www.casarosada.gob.ar"
    adapter = _MockedAdapter(
        {f"{base}/informacion/discursos": LISTING_PAGE_1},
        mode="http",
    )
    urls = list(adapter.list_discursos(max_items=10))
    assert urls == [
        f"{base}/informacion/discursos/12345-discurso-uno",
        f"{base}/informacion/discursos/12346-discurso-dos",
    ]


def test_list_discursos_pagina() -> None:
    base = "https://www.casarosada.gob.ar"
    adapter = _MockedAdapter({
        f"{base}/informacion/discursos": LISTING_PAGE_1,
        f"{base}/informacion/discursos?page=2": LISTING_PAGE_2,
    }, mode="http")
    urls = list(adapter.list_discursos(max_items=10))
    assert len(urls) == 3
    assert urls[-1].endswith("12347-discurso-tres")


def test_list_discursos_respeta_max_items() -> None:
    base = "https://www.casarosada.gob.ar"
    adapter = _MockedAdapter({
        f"{base}/informacion/discursos": LISTING_PAGE_1,
        f"{base}/informacion/discursos?page=2": LISTING_PAGE_2,
    }, mode="http")
    urls = list(adapter.list_discursos(max_items=1))
    assert len(urls) == 1


def test_list_discursos_dedupes() -> None:
    """Si un mismo link aparece en dos páginas, solo se yield-ea una vez."""
    page = """
    <main>
      <a href="/informacion/discursos/X">X</a>
      <a href="/informacion/discursos/X">X otra vez</a>
    </main>
    """
    adapter = _MockedAdapter(
        {"https://www.casarosada.gob.ar/informacion/discursos": page},
        mode="http",
    )
    urls = list(adapter.list_discursos())
    assert len(urls) == 1


def test_list_discursos_empty_listing_termina() -> None:
    adapter = _MockedAdapter(
        {"https://www.casarosada.gob.ar/informacion/discursos": "<html><body></body></html>"},
        mode="http",
    )
    assert list(adapter.list_discursos()) == []


# ══════════════════════════════════════════════════════════════════════════════
#  fetch_discurso
# ══════════════════════════════════════════════════════════════════════════════

def test_fetch_discurso_extrae_todo() -> None:
    url = "https://www.casarosada.gob.ar/informacion/discursos/12345-discurso-uno"
    adapter = _MockedAdapter({url: DISCURSO_PAGE}, mode="http")
    rec = adapter.fetch_discurso(url)
    assert rec is not None
    assert rec.titulo == "Palabras del Presidente en el acto de inauguración"
    assert rec.fecha == "2024-12-15"
    assert "Buenas tardes" in rec.contenido
    assert "Estamos comprometidos" in rec.contenido
    assert rec.fuente == "casarosada"
    assert rec.codigo == "casarosada_12345-discurso-uno"


def test_fetch_discurso_sin_contenido_devuelve_none() -> None:
    url = "https://www.casarosada.gob.ar/informacion/discursos/X"
    adapter = _MockedAdapter({url: DISCURSO_VACIO}, mode="http")
    rec = adapter.fetch_discurso(url)
    assert rec is None


def test_fetch_discurso_html_vacio_devuelve_none() -> None:
    url = "https://www.casarosada.gob.ar/informacion/discursos/X"
    adapter = _MockedAdapter({url: ""}, mode="http")
    rec = adapter.fetch_discurso(url)
    assert rec is None


def test_fetch_discurso_respeta_orden_de_parrafos() -> None:
    url = "https://www.casarosada.gob.ar/informacion/discursos/X"
    adapter = _MockedAdapter({url: DISCURSO_PAGE}, mode="http")
    rec = adapter.fetch_discurso(url)
    parrafos = rec.contenido.split("\n\n")
    assert parrafos[0].startswith("Buenas tardes")
    assert parrafos[1].startswith("Quiero agradecer")
    assert parrafos[2].startswith("Estamos comprometidos")


def test_codigo_from_url_es_estable() -> None:
    """El código depende solo del slug; mismo URL → mismo código entre runs."""
    c1 = CasaRosadaAdapter._codigo_from_url(
        "https://www.casarosada.gob.ar/informacion/discursos/12345-foo"
    )
    c2 = CasaRosadaAdapter._codigo_from_url(
        "https://www.casarosada.gob.ar/informacion/discursos/12345-foo/"
    )
    assert c1 == c2 == "casarosada_12345-foo"


def test_codigo_from_url_sanitiza_slug() -> None:
    c = CasaRosadaAdapter._codigo_from_url(
        "https://x/informacion/discursos/abc!@#-def"
    )
    # Solo [\w-] sobreviven, el resto pasa a "_".
    assert c == "casarosada_abc___-def"


# ══════════════════════════════════════════════════════════════════════════════
#  Modo auto: detección de bloqueo
# ══════════════════════════════════════════════════════════════════════════════

def test_is_blocked_response_detecta_html_corto() -> None:
    assert CasaRosadaAdapter._is_blocked_response("") is True
    assert CasaRosadaAdapter._is_blocked_response("<html></html>") is True


def test_is_blocked_response_detecta_cloudflare_challenge() -> None:
    html = "<html><body>" + "x" * 300 + "checking your browser</body></html>"
    assert CasaRosadaAdapter._is_blocked_response(html) is True


def test_is_blocked_response_detecta_403_title() -> None:
    html = "<html><head><title>403 Forbidden</title></head>" + "x" * 300 + "</html>"
    assert CasaRosadaAdapter._is_blocked_response(html) is True


def test_is_blocked_response_pasa_html_normal() -> None:
    html = LISTING_PAGE_1
    assert CasaRosadaAdapter._is_blocked_response(html) is False


# ══════════════════════════════════════════════════════════════════════════════
#  Schema del DiscursoRecord
# ══════════════════════════════════════════════════════════════════════════════

def test_record_to_dict_expone_extras() -> None:
    url = "https://www.casarosada.gob.ar/informacion/discursos/X"
    adapter = _MockedAdapter({url: DISCURSO_PAGE}, mode="http")
    rec = adapter.fetch_discurso(url)
    d = rec.to_dict()
    assert d["codigo"] == "casarosada_X"
    assert d["fuente"] == "casarosada"
    # `scrape_mode` viene como extra del adapter.
    assert d.get("scrape_mode") == "http"


def test_close_es_idempotente() -> None:
    """Llamar close() dos veces no rompe."""
    adapter = _MockedAdapter({}, mode="http")
    adapter.close()
    adapter.close()


# ══════════════════════════════════════════════════════════════════════════════
#  Escalada HTTP → Selenium (mockeada)
# ══════════════════════════════════════════════════════════════════════════════

class _AlwaysBlockedAdapter(CasaRosadaAdapter):
    """HTTP siempre devuelve respuesta bloqueada; Selenium devuelve OK.

    Sirve para verificar que, una vez detectado bloqueo, las requests
    siguientes van directo a Selenium sin reintento HTTP."""

    def __init__(self, **kwargs: object) -> None:
        super().__init__(**kwargs)
        self.http_calls: list[str] = []
        self.selenium_calls: list[str] = []

    def _fetch_http_strict(self, url: str) -> str:
        self.http_calls.append(url)
        return ""  # respuesta bloqueada → el dispatcher escala

    def _fetch_selenium(self, url: str) -> str:
        self.selenium_calls.append(url)
        return DISCURSO_PAGE


def test_modo_auto_escala_a_selenium_y_se_queda() -> None:
    adapter = _AlwaysBlockedAdapter(mode="auto")
    rec1 = adapter.fetch_discurso("https://x/a")
    rec2 = adapter.fetch_discurso("https://x/b")

    # Ambos records se obtuvieron via Selenium tras el primer fallback.
    assert rec1 is not None
    assert rec2 is not None
    assert len(adapter.http_calls) == 1   # solo el primer intento HTTP
    assert len(adapter.selenium_calls) == 2  # las dos requests via Selenium


def test_modo_http_estricto_no_escala() -> None:
    adapter = _AlwaysBlockedAdapter(mode="http")
    rec = adapter.fetch_discurso("https://x/a")
    # HTTP devolvió "" → contenido vacío → record None.
    assert rec is None
    assert len(adapter.http_calls) == 1
    assert len(adapter.selenium_calls) == 0


def test_modo_selenium_skipea_http() -> None:
    adapter = _AlwaysBlockedAdapter(mode="selenium")
    rec = adapter.fetch_discurso("https://x/a")
    assert rec is not None
    assert len(adapter.http_calls) == 0
    assert len(adapter.selenium_calls) == 1
