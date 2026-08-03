"""Contratos de limpieza de justificaciones del caracterizador."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from emoparse.core.schemas import CaracterizacionEmocionSchema


def _payload() -> dict[str, str]:
    return {
        "foria": "euforico",
        "foria_justificacion": "La valoración 'lugar que merece' es positiva.",
        "dominancia": "cognoscitiva",
        "dominancia_justificacion": "La emoción se construye mediante una evaluación.",
        "intensidad": "alta",
        "intensidad_justificacion": "La fórmula 'no hay mayor expresión' maximiza la valoración.",
        "duracion": "durable",
        "duracion_justificacion": "La creencia se presenta como una postura sostenida.",
        "tipo_atribucion": "sin_atribucion",
        "tipo_atribucion_justificacion": (
            "No hay término emocional explícito atribuido sintácticamente."
        ),
        "temporalidad": "contemporanea",
        "temporalidad_justificacion": "El verbo 'creemos' está en presente.",
        "aspecto": "no_marcado",
        "aspecto_justificacion": "No hay una marca aspectual de la emoción.",
    }


def test_characterizer_accepts_concise_final_justifications() -> None:
    parsed = CaracterizacionEmocionSchema(**_payload())

    assert parsed.tipo_atribucion == "sin_atribucion"


def test_characterizer_rejects_internal_deliberation() -> None:
    payload = _payload()
    payload["tipo_atribucion_justificacion"] = (
        "El prompt me pide satisfacción; voy a releer y corregir la decisión."
    )

    with pytest.raises(ValidationError):
        CaracterizacionEmocionSchema(**payload)


def test_characterizer_allows_enunciator_term_in_justification() -> None:
    payload = _payload()
    payload["tipo_atribucion_justificacion"] = (
        "El enunciador no atribuye explícitamente la emoción a un actor."
    )

    parsed = CaracterizacionEmocionSchema(**payload)

    assert "enunciador" in parsed.tipo_atribucion_justificacion.lower()
