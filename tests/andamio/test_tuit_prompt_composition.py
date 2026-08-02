from __future__ import annotations

from emoparse.agents.enunciation import EnunciationAgent
from emoparse.agents.metadata import MetadataAgent
from emoparse.genres.tuit import get_genre


def test_tuit_no_longer_replaces_metadata_or_enunciation_templates() -> None:
    overrides = get_genre().prompt_overrides

    assert "metadata" not in overrides
    assert "enunciation" not in overrides


def test_metadata_uses_base_template_with_closed_tuit_types() -> None:
    agent = MetadataAgent(
        object(),  # type: ignore[arg-type]
        {"referencia": "diccionario abierto"},
        genre=get_genre(),
    )

    assert agent._system.startswith("Sos un analista de discurso.")
    assert "TIPOS DE DISCURSO VÁLIDOS" in agent._system
    assert "- politico:" in agent._system
    assert "proponé uno nuevo" not in agent._system


def test_enunciation_composes_generic_flags_and_genre_heuristics() -> None:
    agent = EnunciationAgent(
        object(),  # type: ignore[arg-type]
        genre=get_genre(),
        heuristicas="MARCA_HEURISTICA_TUIT",
    )

    assert agent._system.startswith(
        "Sos un analista de discurso especializado en estructura enunciativa."
    )
    assert "MARCA_HEURISTICA_TUIT" in agent._system
    assert "viene ya identificado" in agent._system
    assert "devolvé una lista vacía en `auditorio`" in agent._system
