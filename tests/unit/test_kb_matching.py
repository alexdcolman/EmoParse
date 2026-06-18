# ══════════════════════════════════════════════════════════════════════════════
#  tests.unit.test_kb_matching
#
#  Tests de KbMatcher: matching de alias, display names, slugs, y propuestas de
#  slugs.
# ══════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

from emoparse.pipeline.kb_matching import KbMatcher, slugify

_KB = {
    "actors": {
        "javier_milei": {"display_name": "Javier Milei",
                         "aliases": ["Milei", "el presidente Milei"], "tipo": "individuo"},
        "la_libertad_avanza": {"display_name": "La Libertad Avanza",
                               "aliases": ["LLA"], "tipo": "institucion"},
        "el_fmi": {"display_name": "Fondo Monetario Internacional",
                   "aliases": ["FMI"], "tipo": "institucion"},
        "victimas_holocausto": {"display_name": "Víctimas del Holocausto",
                                "aliases": [], "tipo": "colectivo"},
    }
}


def _m():
    return KbMatcher(_KB)


def test_match_alias_exact_and_normalized():
    m = _m()
    assert m.match("La Libertad Avanza") == "la_libertad_avanza"
    assert m.match("la libertad avanza") == "la_libertad_avanza"
    assert m.match("LLA") == "la_libertad_avanza"
    assert m.match("Milei") == "javier_milei"
    assert m.match("MILEI") == "javier_milei"


def test_match_article_insensitive():
    m = _m()
    assert m.match("el FMI") == "el_fmi"
    assert m.match("FMI") == "el_fmi"


def test_match_display_name_and_slug():
    m = _m()
    assert m.match("Víctimas del Holocausto") == "victimas_holocausto"
    assert m.match("victimas del holocausto") == "victimas_holocausto"


def test_proposed_slug_and_display_are_ignored():
    # El slug/display que propone el LLM NO debe usarse para linkear:
    # arrastran errores de correferencia. Solo cuenta el texto de la mención.
    m = _m()
    assert m.match("cualquier cosa", "javier_milei") is None
    assert m.match("Javier M.", proposed_display="Javier Milei") is None


def test_regression_milei_no_se_va_a_mindlin():
    # Caso real: el LLM agrupa "Javier Milei" con "Marcelo Mindlin" y propone
    # 'marcelo_mindlin'. El texto manda: debe ir a javier_milei igual.
    kb = {
        "actors": {
            "javier_milei": {"display_name": "Javier Milei",
                             "aliases": ["Presidente de la Nación, Javier Milei",
                                         "Javier Milei"], "tipo": "individuo"},
            "marcelo_mindlin": {"display_name": "Marcelo Mindlin",
                                "aliases": ["presidente del Museo del Holocausto, Marcelo Mindlin"],
                                "tipo": "individuo"},
        }
    }
    m = KbMatcher(kb)
    assert m.match("Javier Milei", "marcelo_mindlin") == "javier_milei"
    assert m.match("Presidente de la Nación, Javier Milei",
                   "marcelo_mindlin") == "javier_milei"
    assert m.match("presidente del Museo del Holocausto, Marcelo Mindlin") \
        == "marcelo_mindlin"


def test_exact_form_not_shadowed_by_article_stripped():
    # Una forma exacta de un canónico no debe ser tapada por la forma
    # sin-artículo de otro (p.ej. 'los ciudadanos' de pueblo → 'ciudadanos').
    kb = {
        "actors": {
            "pueblo_argentino": {"display_name": "Pueblo argentino",
                                 "aliases": ["los ciudadanos"], "tipo": "colectivo"},
            "ciudadanos": {"display_name": "ciudadanos",
                           "aliases": ["ciudadanos"], "tipo": "colectivo"},
        }
    }
    m = KbMatcher(kb)
    assert m.match("ciudadanos") == "ciudadanos"
    assert m.match("los ciudadanos") == "pueblo_argentino"


def test_conservative_no_overmerge():
    m = _m()
    # NO debe unir víctimas distintas
    assert m.match("víctimas del atentado a la AMIA") is None
    assert m.match("víctimas del atentado") is None
    # actor genuinamente nuevo
    assert m.match("Cristina Fernández de Kirchner") is None


def test_empty_kb_matches_nothing():
    m = KbMatcher({"actors": {}})
    assert m.match("Javier Milei") is None
    m2 = KbMatcher(None)
    assert m2.match("x") is None


def test_slugify():
    assert slugify("La Libertad Avanza") == "la_libertad_avanza"
    assert slugify("  Víctimas del Holocausto ") == "victimas_del_holocausto"
