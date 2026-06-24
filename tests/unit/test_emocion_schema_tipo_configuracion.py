# ══════════════════════════════════════════════════════════════════════════════
#  tests.unit.test_emocion_schema_tipo_configuracion
#
#  Verifica que EmocionSchema requiere tipo_configuracion y valida el Literal.
# ══════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

import pytest
from pydantic import ValidationError

from emoparse.core.schemas import EmocionSchema


VALID_CONFIGURATIONS = [
    "sostenido_en_sustantivos",
    "sostenido_en_adjetivos",
    "ordenado_alrededor_de_verbos_psicologicos",
    "cualificacion_por_indicadores_cognitivos",
    "cualificacion_por_indicadores_comportamiento",
    "cualificacion_por_indicadores_axiologicos",
    "cualificacion_por_componentes_descriptivo_narrativos",
    "transposicion_situacion_reconocimiento_potencial",
]


def _base_kwargs(**overrides):
    base = {
        "experienciador": "el pueblo",
        "tipo_emocion": "indignacion",
        "modo_existencia": "realizada",
        "experienciador_marca": "el pueblo",
        "fuente_marca": "el socialismo",
        "fuente_inferencia": "socialismo",
        "tipo_configuracion": "sostenido_en_sustantivos",
    }
    base.update(overrides)
    return base


class TestEmocionSchemaTipoConfiguracion:

    @pytest.mark.parametrize("config", VALID_CONFIGURATIONS)
    def test_each_valid_configuration_accepted(self, config: str) -> None:
        """Cada uno de los 8 valores del Literal se acepta sin error."""
        emo = EmocionSchema(**_base_kwargs(tipo_configuracion=config))
        assert emo.tipo_configuracion == config

    def test_missing_tipo_configuracion_raises(self) -> None:
        """tipo_configuracion es obligatorio."""
        kwargs = _base_kwargs()
        kwargs.pop("tipo_configuracion")
        with pytest.raises(ValidationError):
            EmocionSchema(**kwargs)

    def test_invalid_tipo_configuracion_raises(self) -> None:
        """Un valor fuera del Literal es rechazado."""
        with pytest.raises(ValidationError):
            EmocionSchema(**_base_kwargs(tipo_configuracion="otra_cosa"))

    def test_typo_in_configuration_raises(self) -> None:
        """Sensible a typos / nombres parecidos pero no canónicos."""
        with pytest.raises(ValidationError):
            EmocionSchema(
                **_base_kwargs(
                    tipo_configuracion="sostenido_en_sustantivo"  # falta 's'
                )
            )

    def test_extra_field_still_forbidden(self) -> None:
        """El extra='forbid' de StrictBase sigue activo después del cambio."""
        with pytest.raises(ValidationError):
            EmocionSchema(**_base_kwargs(campo_extra="oops"))
