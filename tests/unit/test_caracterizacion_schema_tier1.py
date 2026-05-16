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
    "fuente": "el acuerdo firmado",
    "tipo_fuente": "situacion",
    "fuente_justificacion": "El hablante menciona el acuerdo como desencadenante.",
    "duracion": "durable",
    "duracion_justificacion": "La emoción se sostiene a lo largo del párrafo.",
    "modo_semiotizacion": "dicha",
    "modo_semiotizacion_justificacion": "Usa el término 'orgullo' explícitamente.",
    "modo_identificacion": "directa",
    "modo_identificacion_justificacion": "Declaración explícita en primera persona.",
    "tipo_atribucion": "auto_atribucion",
    "tipo_atribucion_justificacion": "El enunciador se atribuye la emoción.",
}


class TestCaracterizacionSchemaValid:

    def test_acepta_caracterizacion_completa(self) -> None:
        c = CaracterizacionEmocionSchema(**_VALID_FULL)
        assert c.foria == "euforico"
        assert c.duracion == "durable"
        assert c.modo_semiotizacion == "dicha"
        assert c.modo_identificacion == "directa"
        assert c.tipo_atribucion == "auto_atribucion"

    def test_acepta_todos_los_valores_duracion(self) -> None:
        for val in ("instantanea", "durable", "permanente"):
            data = {**_VALID_FULL, "duracion": val}
            c = CaracterizacionEmocionSchema(**data)
            assert c.duracion == val

    def test_acepta_todos_los_valores_modo_semiotizacion(self) -> None:
        for val in ("dicha", "mostrada", "sostenida"):
            data = {**_VALID_FULL, "modo_semiotizacion": val}
            c = CaracterizacionEmocionSchema(**data)
            assert c.modo_semiotizacion == val

    def test_acepta_todos_los_valores_modo_identificacion(self) -> None:
        for val in ("directa", "por_senales_salida", "por_senales_entrada", "mixta"):
            data = {**_VALID_FULL, "modo_identificacion": val}
            c = CaracterizacionEmocionSchema(**data)
            assert c.modo_identificacion == val

    def test_acepta_todos_los_valores_tipo_atribucion(self) -> None:
        for val in ("auto_atribucion", "hetero_atribucion", "atribucion_transpositiva"):
            data = {**_VALID_FULL, "tipo_atribucion": val}
            c = CaracterizacionEmocionSchema(**data)
            assert c.tipo_atribucion == val


class TestCaracterizacionSchemaInvalid:

    def test_rechaza_sin_duracion(self) -> None:
        data = {k: v for k, v in _VALID_FULL.items() if k != "duracion"}
        with pytest.raises(ValidationError):
            CaracterizacionEmocionSchema(**data)

    def test_rechaza_sin_modo_semiotizacion(self) -> None:
        data = {k: v for k, v in _VALID_FULL.items() if k != "modo_semiotizacion"}
        with pytest.raises(ValidationError):
            CaracterizacionEmocionSchema(**data)

    def test_rechaza_sin_modo_identificacion(self) -> None:
        data = {k: v for k, v in _VALID_FULL.items() if k != "modo_identificacion"}
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

    def test_rechaza_modo_semiotizacion_valor_invalido(self) -> None:
        data = {**_VALID_FULL, "modo_semiotizacion": "implicita"}
        with pytest.raises(ValidationError):
            CaracterizacionEmocionSchema(**data)

    def test_rechaza_modo_identificacion_valor_invalido(self) -> None:
        data = {**_VALID_FULL, "modo_identificacion": "indirecta"}
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
