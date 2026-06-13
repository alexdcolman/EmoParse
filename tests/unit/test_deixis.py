# ══════════════════════════════════════════════════════════════════════════════
#  tests.unit.test_deixis
#
#  Tests para resolución de deícticos.
# ══════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

from emoparse.pipeline.deixis import (
    is_first_person_deictic,
    resolve_deictic_to_enunciador,
)


# ── Detección de deícticos de 1ª persona ──────────────────────────────────────

def test_first_person_simple():
    for s in ["yo", "mí", "me", "nosotros", "nosotras", "nos", "nuestro"]:
        assert is_first_person_deictic(s), s


def test_first_person_normalizes_case_and_accents():
    assert is_first_person_deictic("YO")
    assert is_first_person_deictic("Mí")
    assert is_first_person_deictic("NOSOTRAS")


def test_first_person_strips_parentheticals():
    assert is_first_person_deictic("nosotros (gobierno)")
    assert is_first_person_deictic("nosotros (estamos dando)")
    assert is_first_person_deictic("'yo'")


def test_not_first_person():
    for s in [
        "mi gobierno", "el presidente", "Javier Milei", "el león",
        "el enunciador y sus seguidores", "diputado Nacional", "", "LLA",
    ]:
        assert not is_first_person_deictic(s), s


# ── Resolución al enunciador ──────────────────────────────────────────────────

def test_resolves_deictic_to_enunciador():
    link = {"actor_mencionado": "yo", "actor_canonico": None, "es_nuevo": True}
    out = resolve_deictic_to_enunciador(link, "Javier Milei")
    assert out["actor_canonico"] == "Javier Milei"
    assert out["es_nuevo"] is False
    assert out["resuelto_por"] == "deixis_enunciador"


def test_resolves_nosotros_with_parenthetical():
    link = {"actor_mencionado": "nosotros (gobierno)", "actor_canonico": None,
            "es_nuevo": True}
    out = resolve_deictic_to_enunciador(link, "Javier Milei")
    assert out["actor_canonico"] == "Javier Milei"


def test_respects_existing_canonical():
    link = {"actor_mencionado": "yo", "actor_canonico": "otra_persona",
            "es_nuevo": False}
    out = resolve_deictic_to_enunciador(link, "Javier Milei")
    assert out["actor_canonico"] == "otra_persona"
    assert "resuelto_por" not in out


def test_leaves_non_deictic_untouched():
    link = {"actor_mencionado": "Javier Milei", "actor_canonico": None,
            "es_nuevo": True}
    out = resolve_deictic_to_enunciador(link, "Javier Milei")
    assert out["actor_canonico"] is None
    assert out["es_nuevo"] is True
    assert "resuelto_por" not in out


def test_no_enunciador_is_noop():
    link = {"actor_mencionado": "yo", "actor_canonico": None, "es_nuevo": True}
    out = resolve_deictic_to_enunciador(link, "")
    assert out["actor_canonico"] is None
    assert out["es_nuevo"] is True


def test_mutates_and_returns_same_dict():
    link = {"actor_mencionado": "yo", "actor_canonico": None, "es_nuevo": True}
    out = resolve_deictic_to_enunciador(link, "Milei")
    assert out is link
