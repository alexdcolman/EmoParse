# ══════════════════════════════════════════════════════════════════════════════
#  tests.unit.test_normalization_helper
#
#  Tests del helper build_emotion_alias_lookup.
# ══════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

import pytest

from emoparse.knowledge.normalization import build_emotion_alias_lookup


# ── Fixture ───────────────────────────────────────────────────────────────────

MINIMAL_ONTOLOGY: dict = {
    "version": "v1",
    "emociones": {
        "ira": {
            "aliases": ["enojo", "rabia", "furia", "bronca"],
        },
        "alegria": {
            "aliases": ["alegría", "felicidad", "júbilo"],
        },
    },
}


# ── Tests ─────────────────────────────────────────────────────────────────────

class TestBuildEmotionAliasLookup:

    def test_canonical_maps_to_itself(self) -> None:
        lookup = build_emotion_alias_lookup(MINIMAL_ONTOLOGY)
        assert lookup["ira"] == "ira"
        assert lookup["alegria"] == "alegria"

    def test_alias_lowercase_maps_to_canonical(self) -> None:
        lookup = build_emotion_alias_lookup(MINIMAL_ONTOLOGY)
        assert lookup["enojo"] == "ira"
        assert lookup["rabia"] == "ira"
        assert lookup["felicidad"] == "alegria"

    def test_alias_with_tilde_maps_correctly(self) -> None:
        lookup = build_emotion_alias_lookup(MINIMAL_ONTOLOGY)
        assert lookup["alegría"] == "alegria"
        assert lookup["júbilo"] == "alegria"

    def test_unknown_alias_not_in_lookup(self) -> None:
        lookup = build_emotion_alias_lookup(MINIMAL_ONTOLOGY)
        assert "tristeza" not in lookup
        assert "miedo" not in lookup

    def test_canonical_has_priority_over_alias(self) -> None:
        """Si un alias coincide con el canónico de otra emoción, gana el canónico."""
        ontology = {
            "emociones": {
                "alegria": {"aliases": []},             # canónico va primero
                "ira": {"aliases": ["alegria"]},         # alias llega tarde → no pisa
            }
        }
        lookup = build_emotion_alias_lookup(ontology)
        assert lookup["alegria"] == "alegria"

    def test_empty_ontology_returns_empty_lookup(self) -> None:
        lookup = build_emotion_alias_lookup({})
        assert lookup == {}

    def test_malformed_emociones_value_returns_empty(self) -> None:
        lookup = build_emotion_alias_lookup({"emociones": "mal_formado"})
        assert lookup == {}

    def test_entry_without_aliases_key(self) -> None:
        ontology = {"emociones": {"orgullo": {}}}
        lookup = build_emotion_alias_lookup(ontology)
        assert lookup["orgullo"] == "orgullo"

    def test_whitespace_in_alias_is_stripped(self) -> None:
        ontology = {"emociones": {"ira": {"aliases": [" rabia "]}}}
        lookup = build_emotion_alias_lookup(ontology)
        assert lookup["rabia"] == "ira"
