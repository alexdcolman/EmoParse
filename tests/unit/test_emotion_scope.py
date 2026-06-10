# ══════════════════════════════════════════════════════════════════════════════
#  tests.unit.test_emotion_scope
#
#  Garantías de la función de alcance de emociones.
# ══════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

from emoparse.agents.emotions import EMOTION_SCOPE_VALUES, alcance_text


def test_scope_values():
    assert EMOTION_SCOPE_VALUES == ("enunciador", "enunciatarios", "actores")


def test_none_scope_is_empty():
    assert alcance_text(None, "Milei", "audiencia") == ""


def test_empty_tuple_is_empty():
    assert alcance_text((), "Milei", "audiencia") == ""


def test_enunciador_includes_name():
    out = alcance_text(("enunciador",), "Javier Milei", "")
    assert "el enunciador (Javier Milei)" in out


def test_enunciador_fallback_when_unknown():
    out = alcance_text(("enunciador",), "", "")
    assert "no identificado" in out


def test_enunciatarios_with_detail():
    out = alcance_text(("enunciatarios",), "Milei", "audiencia; militantes")
    assert "los enunciatarios del discurso (audiencia; militantes)" in out


def test_enunciatarios_without_detail():
    out = alcance_text(("enunciatarios",), "Milei", "")
    assert "los enunciatarios del discurso" in out
    assert "(" not in out


def test_actores_phrase():
    out = alcance_text(("actores",), "Milei", "")
    assert "otros actores" in out


def test_combined_scopes_joined():
    out = alcance_text(("enunciador", "actores"), "Milei", "")
    assert "el enunciador (Milei)" in out
    assert "otros actores" in out
    assert "; " in out


def test_order_follows_canonical_not_input():
    # El orden de la frase es estable (enunciador, enunciatarios, actores),
    # independientemente del orden del scope recibido.
    a = alcance_text(("actores", "enunciador"), "Milei", "")
    assert a.index("el enunciador") < a.index("otros actores")
