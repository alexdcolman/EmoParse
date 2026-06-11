# ══════════════════════════════════════════════════════════════════════════════
#  tests.unit.test_discovery_grouping
#
#  Tests para agrupamiento de descubrimientos de correferencias de actores.
# ══════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

from emoparse.triage.discovery_grouping import group_discoveries, slugify


def _d(id, mencion, cid=None, name=None, tipo=None, codigo="d1", unit=0):
    return {
        "id": id,
        "codigo": codigo,
        "unit_idx": unit,
        "actor_mencionado": mencion,
        "canonical_id_sugerido": cid,
        "display_name_sugerido": name,
        "tipo_sugerido": tipo,
    }


# ── Caso 1: mismo actor nuevo, nombrado distinto en dos discursos ─────────────

def test_case1_cross_discourse_duplicate_groups_into_one():
    discoveries = [
        _d(1, "La Libertad Avanza", "la_libertad_avanza", "La Libertad Avanza",
           "institucion", codigo="d1", unit=3),
        _d(2, "LLA", "la_libertad_avanza", "La Libertad Avanza",
           "institucion", codigo="d2", unit=1),
    ]
    groups = group_discoveries(discoveries)
    assert len(groups) == 1
    g = groups[0]
    assert g.canonical_id == "la_libertad_avanza"
    assert g.display_name == "La Libertad Avanza"
    assert g.tipo == "institucion"
    # member_ids[0] va como promote, el resto como merge.
    assert g.member_ids == [1, 2]


# ── Caso 2: actor nuevo agrupado + una mención vaga que la heurística separa ──

def test_case2_stray_vague_mention_stays_separate():
    discoveries = [
        _d(1, "Caputo", "luis_caputo", "Luis Caputo", "individuo", codigo="d2"),
        _d(2, "Luis Caputo", "luis_caputo", "Luis Caputo", "individuo", codigo="d3"),
        _d(3, "el funcionario de Economía", "funcionario_economia",
           "Funcionario de Economía", "individuo", codigo="d4"),
    ]
    by_id = {g.canonical_id: g for g in group_discoveries(discoveries)}
    assert set(by_id) == {"luis_caputo", "funcionario_economia"}
    assert by_id["luis_caputo"].member_ids == [1, 2]
    assert by_id["funcionario_economia"].member_ids == [3]


# ── Fallbacks y normalización ─────────────────────────────────────────────────

def test_fallback_to_mention_when_no_suggestion():
    discoveries = [_d(1, "Milei"), _d(2, "milei")]
    groups = group_discoveries(discoveries)
    assert len(groups) == 1
    assert groups[0].canonical_id == "milei"
    assert groups[0].member_ids == [1, 2]


def test_suggested_id_and_bare_mention_converge():
    discoveries = [
        _d(1, "La Libertad Avanza", "la_libertad_avanza", "La Libertad Avanza",
           "institucion"),
        _d(2, "La Libertad Avanza"),  # sin sugerencia: slug de la mención coincide
    ]
    groups = group_discoveries(discoveries)
    assert len(groups) == 1
    g = groups[0]
    assert g.canonical_id == "la_libertad_avanza"
    assert g.member_ids == [1, 2]
    # display/tipo salen del miembro que sí los sugirió.
    assert g.display_name == "La Libertad Avanza"
    assert g.tipo == "institucion"


def test_tipo_synonym_mapped_to_kb_vocab():
    g = group_discoveries([_d(1, "X", "x_actor", "X", "humano_individual")])[0]
    assert g.tipo == "individuo"


def test_unknown_tipo_falls_back_to_desconocido():
    g = group_discoveries([_d(1, "X", "x_actor", "X", "alienigena")])[0]
    assert g.tipo == "desconocido"


def test_slug_starting_with_digit_is_made_valid():
    g = group_discoveries([_d(1, "3 Banderas", "3_banderas", "3 Banderas", "colectivo")])[0]
    assert g.canonical_id[0].isalpha()  # canonical_id empieza por letra
    assert g.member_ids == [1]


def test_group_order_and_member_order_are_stable():
    discoveries = [
        _d(10, "Bullrich", "patricia_bullrich", "Patricia Bullrich", "individuo"),
        _d(11, "Milei", "javier_milei", "Javier Milei", "individuo"),
        _d(12, "Patricia Bullrich", "patricia_bullrich", "Patricia Bullrich", "individuo"),
    ]
    groups = group_discoveries(discoveries)
    assert [g.canonical_id for g in groups] == ["patricia_bullrich", "javier_milei"]
    assert groups[0].member_ids == [10, 12]


def test_display_name_picks_most_common_then_longest_mention():
    # Sin display sugerido: cae a la mención más larga del grupo.
    discoveries = [
        _d(1, "LLA", "la_libertad_avanza"),
        _d(2, "La Libertad Avanza", "la_libertad_avanza"),
    ]
    g = group_discoveries(discoveries)[0]
    assert g.display_name == "La Libertad Avanza"


def test_slugify_basic():
    assert slugify("La Libertad Avanza") == "la_libertad_avanza"
    assert slugify("  Caputo, Luis ") == "caputo_luis"
    assert slugify("Economía") == "economia"
