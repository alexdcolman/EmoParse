from __future__ import annotations

from emoparse.core.grammar import schema_to_gbnf
from emoparse.core.schemas import (
    ModalidadItemSchema,
    ModalidadRecoverySchema,
    ModalidadSchema,
)


def test_revisar_vinculo_es_requerido_en_json_schema() -> None:
    schema = ModalidadItemSchema.model_json_schema()
    required = set(schema.get("required", []))
    assert {"link_id", "modalidad", "revisar_vinculo", "justificacion"} <= required


def test_modalidad_contract_no_depende_de_marca_referente_ni_naturaleza() -> None:
    fields = set(ModalidadItemSchema.model_fields)
    assert fields == {"link_id", "modalidad", "revisar_vinculo", "justificacion"}


def test_justificacion_es_breve_en_el_contrato() -> None:
    schema = ModalidadItemSchema.model_json_schema()
    assert schema["properties"]["justificacion"]["maxLength"] == 180


def test_coherencia_semantica_no_invalida_el_batch_en_pydantic() -> None:
    parsed = ModalidadSchema.model_validate(
        {
            "clasificaciones": [
                {
                    "link_id": 0,
                    "modalidad": "designacion",
                    "revisar_vinculo": False,
                    "justificacion": "Nombra directamente al referente.",
                },
                {
                    "link_id": 1,
                    "modalidad": None,
                    "revisar_vinculo": False,
                    "justificacion": "Debe quedar pendiente en la stage.",
                },
            ]
        }
    )
    assert len(parsed.clasificaciones) == 2


def test_gbnf_real_incluye_link_id_revisar_y_null() -> None:
    grammar = schema_to_gbnf(ModalidadSchema)
    assert '\\"link_id\\"' in grammar
    assert '\\"revisar_vinculo\\"' in grammar
    assert "null" in grammar
    assert '\\"marca\\"' not in grammar
    assert '\\"referente\\"' not in grammar


def test_recovery_contract_exige_un_unico_item_coherente() -> None:
    schema = ModalidadRecoverySchema.model_json_schema()
    clasificaciones = schema["properties"]["clasificaciones"]
    assert clasificaciones["minItems"] == 1
    assert clasificaciones["maxItems"] == 1

    ModalidadRecoverySchema.model_validate(
        {
            "clasificaciones": [
                {
                    "link_id": 7,
                    "modalidad": "predicacion",
                    "revisar_vinculo": False,
                    "justificacion": "Construye el evento.",
                }
            ]
        }
    )
    ModalidadRecoverySchema.model_validate(
        {
            "clasificaciones": [
                {
                    "link_id": 7,
                    "modalidad": None,
                    "revisar_vinculo": True,
                    "justificacion": "Vínculo upstream insostenible.",
                }
            ]
        }
    )


def test_recovery_contract_rechaza_combinaciones_incoherentes() -> None:
    import pytest
    from pydantic import ValidationError

    invalid = (
        ("designacion", True),
        (None, False),
    )
    for modalidad, revisar in invalid:
        with pytest.raises(ValidationError):
            ModalidadRecoverySchema.model_validate(
                {
                    "clasificaciones": [
                        {
                            "link_id": 7,
                            "modalidad": modalidad,
                            "revisar_vinculo": revisar,
                            "justificacion": "Combinación inválida.",
                        }
                    ]
                }
            )


def test_recovery_gbnf_fija_true_false_y_un_item() -> None:
    grammar = schema_to_gbnf(ModalidadRecoverySchema)
    array_line = next(
        line for line in grammar.splitlines() if line.startswith("Clasificaciones ::=")
    )

    assert '\\"revisar_vinculo\\"' in grammar
    assert '"true"' in grammar
    assert '"false"' in grammar
    assert "ModalidadResolvedRecoveryItemSchema | ModalidadReviewRecoveryItemSchema" in array_line
    assert '","' not in array_line
    assert "?" not in array_line
