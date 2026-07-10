# ══════════════════════════════════════════════════════════════════════════════
#  tests.unit.test_caracterizacion_schema_tier1
#
#  Verifica que CaracterizacionEmocionSchema acepta y rechaza correctamente
#  caracterizaciones con los campos de Tier 1.
# ══════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

import pytest
from pydantic import ValidationError

from emoparse.core.schemas import CaracterizacionEmocionSchema


_VALID_FULL: dict = {
    "foria": "euforico",
    "foria_justificacion": "El tono celebratorio del discurso.",
    "dominancia": "cognoscitiva",
    "dominancia_justificacion": "Evaluación racional del logro.",
    "intensidad": "alta",
    "intensidad_justificacion": "Énfasis repetido en el éxito.",
    "duracion": "durable",
    "duracion_justificacion": "La emoción se sostiene a lo largo del párrafo.",
    "tipo_atribucion": "auto_atribucion",
    "tipo_atribucion_justificacion": "El enunciador se atribuye la emoción.",
    "temporalidad": "contemporanea",
    "temporalidad_justificacion": "La emoción se sitúa en el presente de la enunciación.",
    "aspecto": "imperfectivo",
    "aspecto_justificacion": "La emoción se presenta en curso.",
}


class TestCaracterizacionSchemaValid:

    def test_acepta_caracterizacion_completa(self) -> None:
        c = CaracterizacionEmocionSchema(**_VALID_FULL)
        assert c.foria == "euforico"
        assert c.duracion == "durable"
        assert c.tipo_atribucion == "auto_atribucion"

    def test_acepta_todos_los_valores_duracion(self) -> None:
        for val in ("instantanea", "durable", "permanente"):
            data = {**_VALID_FULL, "duracion": val}
            c = CaracterizacionEmocionSchema(**data)
            assert c.duracion == val

    def test_acepta_todos_los_valores_tipo_atribucion(self) -> None:
        for val in ("auto_atribucion", "hetero_atribucion", "sin_atribucion"):
            data = {**_VALID_FULL, "tipo_atribucion": val}
            c = CaracterizacionEmocionSchema(**data)
            assert c.tipo_atribucion == val


class TestCaracterizacionSchemaInvalid:

    def test_rechaza_sin_duracion(self) -> None:
        data = {k: v for k, v in _VALID_FULL.items() if k != "duracion"}
        with pytest.raises(ValidationError):
            CaracterizacionEmocionSchema(**data)

    def test_rechaza_sin_tipo_atribucion(self) -> None:
        data = {k: v for k, v in _VALID_FULL.items() if k != "tipo_atribucion"}
        with pytest.raises(ValidationError):
            CaracterizacionEmocionSchema(**data)

    def test_rechaza_duracion_valor_invalido(self) -> None:
        data = {**_VALID_FULL, "duracion": "efimera"}
        with pytest.raises(ValidationError):
            CaracterizacionEmocionSchema(**data)

    def test_rechaza_tipo_atribucion_valor_invalido(self) -> None:
        data = {**_VALID_FULL, "tipo_atribucion": "colectiva"}
        with pytest.raises(ValidationError):
            CaracterizacionEmocionSchema(**data)

    def test_rechaza_campo_extra(self) -> None:
        """StrictBase tiene extra='forbid'."""
        data = {**_VALID_FULL, "campo_inventado": "x"}
        with pytest.raises(ValidationError):
            CaracterizacionEmocionSchema(**data)

    def test_rechaza_sin_justificaciones_tier1(self) -> None:
        """Campos de justificación son obligatorios."""
        data = {k: v for k, v in _VALID_FULL.items()
                if k not in ("duracion_justificacion",)}
        with pytest.raises(ValidationError):
            CaracterizacionEmocionSchema(**data)
