# ══════════════════════════════════════════════════════════════════════════════
#  Tests de emoparse.pipeline.technoparse
# ══════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

import pytest

from emoparse.pipeline.technoparse import (
    detect_repost_prefix,
    extract_hashtags,
    extract_menciones,
    extract_tecnografismos,
    extract_urls,
    menciones_handles,
    parse_texto,
)

pytestmark = pytest.mark.unit


class TestHashtags:
    def test_integrada_vs_pospuesta(self):
        texto = "El #tarifazo nos afecta a todos. Basta ya #tarifazo #servicios"
        tags = extract_hashtags(texto)
        assert [t.valor_norm for t in tags] == ["tarifazo", "tarifazo", "servicios"]
        assert tags[0].extra["funcion_sintactica"] == "integrada"
        assert tags[1].extra["funcion_sintactica"] == "pospuesta"
        assert tags[2].extra["funcion_sintactica"] == "pospuesta"

    def test_offsets(self):
        texto = "hola #mundo"
        (tag,) = extract_hashtags(texto)
        assert texto[tag.inicio:tag.fin] == "#mundo"

    def test_unicode(self):
        (tag,) = extract_hashtags("#CienciaArgentina al frente")
        assert tag.valor_norm == "cienciaargentina"
        assert tag.extra["funcion_sintactica"] == "integrada"


class TestMenciones:
    def test_vocativo_inicial(self):
        texto = "@ana.bsky.social @luis_ok totalmente de acuerdo con @pedro"
        menciones = extract_menciones(texto)
        assert [m.valor_norm for m in menciones] == [
            "ana.bsky.social", "luis_ok", "pedro",
        ]
        assert menciones[0].extra["posicion"] == "vocativo_inicial"
        assert menciones[1].extra["posicion"] == "vocativo_inicial"
        assert menciones[2].extra["posicion"] == "integrada"

    def test_handle_con_puntos_no_arrastra_puntuacion(self):
        (m,) = extract_menciones("gracias @vecinos-sur.bsky.social!")
        assert m.valor_norm == "vecinos-sur.bsky.social"


class TestUrls:
    def test_dominio_y_puntuacion_final(self):
        (u,) = extract_urls("mirá https://www.ejemplo.com/nota?x=1, importante")
        assert u.valor_norm == "ejemplo.com"
        assert not u.valor.endswith(",")

    def test_hash_en_url_no_es_hashtag(self):
        texto = "ver https://ejemplo.com/doc#seccion2 ahora"
        entidades = parse_texto(texto)
        assert [e.tipo for e in entidades if e.tipo == "hashtag"] == []


class TestTecnografismos:
    def test_alargamiento(self):
        tgs = extract_tecnografismos("me da muchííísima bronca")
        (t,) = [t for t in tgs if t.extra["subtipo"] == "alargamiento"]
        assert t.valor == "muchííísima"
        assert t.valor_norm == "muchíisima".replace("íi", "í")  # colapsa la repetida

    def test_risa(self):
        tgs = extract_tecnografismos("jajaja no puedo")
        assert any(t.extra["subtipo"] == "risa" for t in tgs)

    def test_mayusculas(self):
        tgs = extract_tecnografismos("es una VERGÜENZA total")
        (t,) = [t for t in tgs if t.extra["subtipo"] == "mayusculas"]
        assert t.valor == "VERGÜENZA"

    def test_puntuacion_expresiva(self):
        tgs = extract_tecnografismos("¿¿en serio?? no lo puedo creer!!!")
        normas = {t.valor_norm for t in tgs if t.extra["subtipo"] == "puntuacion"}
        assert "interrogacion_multiple" in normas
        assert "exclamacion_multiple" in normas

    def test_numeros_no_son_alargamiento(self):
        tgs = extract_tecnografismos("juntamos 4000 firmas")
        assert [t for t in tgs if t.extra["subtipo"] == "alargamiento"] == []

    def test_grito_alargado_una_sola_entidad(self):
        # "GOOOOOOOL": alargamiento y mayúsculas compiten; debe salir una sola.
        tgs = extract_tecnografismos("GOOOOOOOL de Belgrano")
        matches = [t for t in tgs if "gol" in t.valor_norm.lower() or t.valor.startswith("GO")]
        assert len(matches) == 1


class TestParseTexto:
    def test_orden_y_tipos(self):
        texto = "@martina mirá esto 😡 https://ejemplo.com/n #tarifazo"
        entidades = parse_texto(texto)
        assert [e.inicio for e in entidades] == sorted(e.inicio for e in entidades)
        tipos = {e.tipo for e in entidades}
        assert {"mencion", "url", "hashtag"} <= tipos

    def test_emoji_presente(self):
        entidades = parse_texto("qué bronca 😡")
        emojis = [e for e in entidades if e.tipo == "emoji"]
        assert len(emojis) == 1
        assert emojis[0].valor == "😡"

    def test_texto_plano_sin_entidades(self):
        assert parse_texto("Una frase sobria sin marcas digitales.") == []

    def test_helper_menciones(self):
        entidades = parse_texto("@ana y @luis debaten")
        assert [m.valor_norm for m in menciones_handles(entidades)] == ["ana", "luis"]


class TestRepostPrefix:
    def test_detecta_rt(self):
        assert detect_repost_prefix("RT @cuenta: texto original") == "cuenta"

    def test_no_detecta_texto_normal(self):
        assert detect_repost_prefix("El RT @cuenta no va al inicio") is None
