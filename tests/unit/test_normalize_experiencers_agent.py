# ══════════════════════════════════════════════════════════════════════════════
#  tests.unit.test_normalize_experiencers_agent
#
#  Garantías del NormalizeExperiencersAgent.
# ══════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

import json

import pydantic
import pytest

from emoparse.agents.normalize_experiencers import NormalizeExperiencersAgent
from emoparse.core.schemas import ExperiencerEquivalenceSchema


# ── _format_experiencers (staticmethod, sin backend) ──────────────────────────

def test_format_from_list():
    out = NormalizeExperiencersAgent._format_experiencers(
        [{"raw": "yo", "ocurrencias": 3}, {"raw": "la casta", "ocurrencias": 1}]
    )
    assert "[0] yo (x3)" in out
    assert "[1] la casta (x1)" in out


def test_format_from_json_string():
    raw = json.dumps([{"raw": "enunciador", "ocurrencias": 2}])
    out = NormalizeExperiencersAgent._format_experiencers(raw)
    assert "enunciador (x2)" in out


def test_format_without_count():
    out = NormalizeExperiencersAgent._format_experiencers([{"raw": "yo"}])
    assert "yo" in out
    assert "(x" not in out


def test_format_empty_and_garbage():
    assert "(ninguno)" in NormalizeExperiencersAgent._format_experiencers([])
    assert "(ninguno)" in NormalizeExperiencersAgent._format_experiencers("not json")
    assert "(ninguno)" in NormalizeExperiencersAgent._format_experiencers(None)


# ── Schema ────────────────────────────────────────────────────────────────────

def test_schema_valid():
    s = ExperiencerEquivalenceSchema(
        raw_experienciador="yo",
        clase="enunciador",
        canonical_sugerido="Milei",
        confianza="alta",
        justificacion="primera persona",
    )
    assert s.clase == "enunciador"
    assert s.canonical_sugerido == "Milei"


def test_schema_allows_null_suggestion_for_otro():
    s = ExperiencerEquivalenceSchema(
        raw_experienciador="x",
        clase="otro",
        canonical_sugerido=None,
        confianza="baja",
        justificacion="ambiguo",
    )
    assert s.canonical_sugerido is None


def test_schema_rejects_unknown_clase():
    with pytest.raises(pydantic.ValidationError):
        ExperiencerEquivalenceSchema(
            raw_experienciador="yo",
            clase="hablante",  # no está en el Literal
            canonical_sugerido="Milei",
            confianza="alta",
            justificacion="x",
        )


def test_schema_rejects_unknown_confianza():
    with pytest.raises(pydantic.ValidationError):
        ExperiencerEquivalenceSchema(
            raw_experienciador="yo",
            clase="enunciador",
            canonical_sugerido="Milei",
            confianza="altisima",  # no está en el Literal
            justificacion="x",
        )
