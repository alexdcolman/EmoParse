# ══════════════════════════════════════════════════════════════════════════════
#  Tests de emoparse.pipeline.emoji_lexicon y emoparse.pipeline.post_context
# ══════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

import pytest

from emoparse.pipeline.emoji_lexicon import resolve_emoji_afecto
from emoparse.pipeline.post_context import (
    make_hilo_context_provider,
    make_tecno_context_provider,
)

pytestmark = pytest.mark.unit

LEXICON = {
    "😡": {"candidatos": ["ira", "indignación"], "foria": "disforico", "ambiguo": False},
    "😂": {"candidatos": ["alegría", "burla"], "foria": None, "ambiguo": True},
    "🥹": {"candidatos": [], "foria": "euforico", "ambiguo": False},
}


class TestEmojiLexicon:
    def test_inequivoco_se_resuelve(self):
        afecto = resolve_emoji_afecto(LEXICON, "😡")
        assert afecto == {"candidato": "ira", "foria": "disforico", "origin": "lexico"}

    def test_ambiguo_queda_para_contexto(self):
        assert resolve_emoji_afecto(LEXICON, "😂") is None

    def test_sin_candidatos_o_desconocido(self):
        assert resolve_emoji_afecto(LEXICON, "🥹") is None
        assert resolve_emoji_afecto(LEXICON, "🦄") is None


# ── Fakes mínimos de repositorios (duck typing) ──────────────────────────────

class _FakePosts:
    def __init__(self, posts):
        self._posts = {p["post_id"]: p for p in posts}

    def get_post(self, post_id):
        return self._posts.get(post_id)


class _FakeTecno:
    def __init__(self, entidades):
        self._e = entidades

    def list_for_unit(self, codigo, unit_idx):
        return [e for e in self._e
                if e["codigo"] == codigo and e["unit_idx"] == unit_idx]


class TestHiloContext:
    def _repo(self):
        return _FakePosts([
            {"post_id": "a", "autor_handle": "ana", "texto": "post raíz",
             "en_respuesta_a": None, "cita_a": None},
            {"post_id": "b", "autor_handle": "luis", "texto": "respuesta uno",
             "en_respuesta_a": "a", "cita_a": None},
            {"post_id": "c", "autor_handle": "ana", "texto": "respuesta dos",
             "en_respuesta_a": "b", "cita_a": None},
            {"post_id": "q", "autor_handle": "irina", "texto": "cito esto",
             "en_respuesta_a": None, "cita_a": "a"},
            {"post_id": "h", "autor_handle": "sol", "texto": "huérfana",
             "en_respuesta_a": "zzz", "cita_a": None},
        ])

    def test_cadena_de_padres_en_orden(self):
        provider = make_hilo_context_provider(self._repo())
        ctx = provider("c")
        assert ctx is not None
        assert ctx.index("post raíz") < ctx.index("respuesta uno")
        assert "@ana" in ctx and "@luis" in ctx

    def test_post_citado(self):
        provider = make_hilo_context_provider(self._repo())
        ctx = provider("q")
        assert "POST CITADO" in ctx and "post raíz" in ctx

    def test_raiz_sin_contexto(self):
        provider = make_hilo_context_provider(self._repo())
        assert provider("a") is None

    def test_padre_no_capturado(self):
        provider = make_hilo_context_provider(self._repo())
        assert "no capturado" in provider("h")


class TestTecnoContext:
    def test_formato_compacto_con_prior(self):
        repo = _FakeTecno([
            {"codigo": "a", "unit_idx": 0, "tipo": "hashtag",
             "valor": "#tarifazo", "valor_norm": "tarifazo",
             "extra": {"funcion_sintactica": "pospuesta"}},
            {"codigo": "a", "unit_idx": 0, "tipo": "emoji",
             "valor": "😡", "valor_norm": "cara_enfadada", "extra": {}},
            {"codigo": "a", "unit_idx": 0, "tipo": "emoji",
             "valor": "🙃", "valor_norm": "cara_invertida",
             "extra": {"afecto": {"candidato": "ironía", "foria": "disforico"}}},
        ])
        provider = make_tecno_context_provider(repo, {"emojis": LEXICON})
        ctx = provider("a", 0)
        assert "#tarifazo (pospuesta)" in ctx
        assert "😡 [candidatos: ira/indignación]" in ctx
        assert "🙃 [ironía, disforico]" in ctx

    def test_sin_entidades(self):
        provider = make_tecno_context_provider(_FakeTecno([]), None)
        assert provider("a", 0) is None
