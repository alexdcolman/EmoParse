"""Contratos de destinación política y auditorio oral."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from emoparse.agents.enunciation import EnunciationAgent
from emoparse.core.schemas import (
    EnunciacionSchema,
    EnunciadorSchema,
    EnunciatarioSchema,
)
from emoparse.genres.discurso_presidencial import get_genre


def _agent() -> EnunciationAgent:
    agent = object.__new__(EnunciationAgent)
    agent._genre = get_genre()
    agent._indicadores = {}
    agent._clases_validas = set()
    path = Path(__file__).parents[2] / "knowledge" / "tipos_discurso.json"
    agent._tipos_discurso = json.loads(path.read_text(encoding="utf-8"))
    return agent


def test_political_role_descriptions_come_from_knowledge() -> None:
    agent = _agent()

    block = agent._roles_block("discurso político")

    assert "Colectivo político que comparte los valores" in block
    assert "La presencia física, un vocativo" in block
    assert "vocativo" in block
    assert "AUDITORIO" in block


def test_vocatives_are_moved_from_prodestination_to_auditorium() -> None:
    agent = _agent()
    parsed = EnunciacionSchema(
        enunciador=EnunciadorSchema(
            actor="Javier Milei",
            justificacion="El enunciador se presenta como Presidente.",
        ),
        enunciatarios=[
            EnunciatarioSchema(
                actor="autoridades nacionales",
                tipo="prodestinatario",
                justificacion="Vocativo explícito al inicio de la ceremonia.",
            ),
            EnunciatarioSchema(
                actor="la base electoral oficialista",
                tipo="prodestinatario",
                justificacion="Comparte los valores reivindicados por el discurso.",
            ),
            EnunciatarioSchema(
                actor="el resto de los argentinos",
                tipo="prodestinatario",
                justificacion="Se lo menciona como población general.",
            ),
        ],
        auditorio=[],
        colectivos=[],
    )
    row = pd.Series(
        {
            "tipo_discurso": "discurso político",
            "contenido": "Señoras y señores, autoridades nacionales, estamos reunidos.",
        }
    )

    mapped = agent._map_to_columns(parsed, row)
    recipients = json.loads(mapped["enunciatarios"])
    auditorium = json.loads(mapped["auditorio"])

    assert [entry["actor"] for entry in recipients] == ["la base electoral oficialista"]
    assert [entry["actor"] for entry in auditorium] == ["autoridades nacionales"]


def test_oral_genre_has_deterministic_auditorium_fallback() -> None:
    agent = _agent()
    parsed = EnunciacionSchema(
        enunciador=EnunciadorSchema(
            actor="Javier Milei",
            justificacion="El enunciador se presenta como Presidente.",
        ),
        enunciatarios=[
            EnunciatarioSchema(
                actor="la base electoral oficialista",
                tipo="prodestinatario",
                justificacion="Comparte los valores reivindicados por el discurso.",
            )
        ],
        auditorio=[],
        colectivos=[],
    )
    row = pd.Series(
        {
            "tipo_discurso": "discurso político",
            "contenido": (
                "Palabras en conmemoración al Día del Veterano y de los Caídos "
                "en la Guerra de Malvinas. Como cada 2 de abril, estamos reunidos."
            ),
        }
    )

    mapped = agent._map_to_columns(parsed, row)
    auditorium = json.loads(mapped["auditorio"])

    assert len(auditorium) == 1
    assert "acto conmemorativo" in auditorium[0]["actor"]
    assert "Malvinas" in auditorium[0]["actor"]
