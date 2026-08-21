"""Contrato de calidad lingüística para texto libre generado por LLM."""

from __future__ import annotations

import pandas as pd

from emoparse.agents.actants import ACTANTS_COMPONENTS, ActantsAgent
from emoparse.core.output_quality import find_unexpected_script_spans
from emoparse.core.schemas import (
    ActantesBatchItemSchema,
    ActantesEmocionSchema,
    ListaActantesBatchSchema,
    MediadorSchema,
    OperadorModificacionSchema,
    PolaridadSchema,
    VerificadorNormativoSchema,
    VerificadorObservacionalSchema,
)
from tests.factories import FakeBackend


def _item(
    unit_idx: int,
    *,
    mediador_justificacion: str = "No hay una instancia distinta que medie entre fuente y experienciador.",
    mediador_descripcion: str | None = None,
) -> ActantesBatchItemSchema:
    return ActantesBatchItemSchema(
        unit_idx=unit_idx,
        actantes=ActantesEmocionSchema(
            mediador=MediadorSchema(
                presente=mediador_descripcion is not None,
                descripcion=mediador_descripcion,
                tipo="discurso_ajeno" if mediador_descripcion is not None else "ausente",
                justificacion=mediador_justificacion,
            ),
            verificador_normativo=VerificadorNormativoSchema(
                presente=False,
                descripcion=None,
                tipo="ausente",
                evaluacion="sin_evaluacion",
                justificacion="No aparece una norma que evalúe la legitimidad de la emoción.",
            ),
            verificador_observacional=VerificadorObservacionalSchema(
                presente=False,
                descripcion=None,
                tipo="ausente",
                evaluacion="sin_evaluacion",
                justificacion="No se comprueba la autenticidad de la emoción ni de su fuente.",
            ),
            operador_modificacion=OperadorModificacionSchema(
                presente=False,
                descripcion=None,
                funcion="ausente",
                justificacion="El discurso no busca modificar la emoción del experienciador.",
            ),
            polaridad=PolaridadSchema(
                negada=False,
                tipo="afirmada",
                justificacion="La emoción se presenta de forma afirmada en la unidad analizada.",
            ),
        ),
    )


def _row(frase: str = "La medida provocó indignación.") -> pd.Series:
    return pd.Series(
        {
            "codigo": "doc:1",
            "frase": frase,
            "experienciador": "el enunciador",
            "fuente_inferencia": "la medida",
            "fuente_marca": "La medida",
            "tipo_emocion": "indignación",
            "modo_existencia": "efectiva",
            "tipo_configuracion": "indicadores axiológicos",
        }
    )


def test_detector_finds_devanagari_and_cyrillic_as_whole_spans() -> None:
    text = "No existe तीसरा mediador ni сельскохозяйственный criterio."

    spans = find_unexpected_script_spans(text)

    assert [span.text for span in spans] == ["तीसरा", "сельскохозяйственный"]


def test_non_latin_span_copied_from_input_is_not_contamination() -> None:
    text = "El nombre Москва funciona como parte de la fuente citada."

    spans = find_unexpected_script_spans(
        text,
        source_text="La referencia original nombra explícitamente a Москва.",
    )

    assert spans == ()


def test_actants_repair_changes_only_the_contaminated_span() -> None:
    original = _item(
        0,
        mediador_justificacion=(
            "No existe तीसरा mediador entre la fuente fijada y el experienciador."
        ),
    )
    backend = FakeBackend(responses=[{"reemplazo": "tercer"}])
    agent = ActantsAgent(backend, enabled_components=ACTANTS_COMPONENTS)
    before = original.model_dump(mode="python")

    repaired = agent._quality_control_item(original, _row())
    after = repaired.model_dump(mode="python")

    assert repaired.actantes.mediador.justificacion == (
        "No existe tercer mediador entre la fuente fijada y el experienciador."
    )
    expected = before
    expected["actantes"]["mediador"]["justificacion"] = (
        "No existe tercer mediador entre la fuente fijada y el experienciador."
    )
    assert after == expected
    assert len(backend.calls) == 1
    assert "तीसरा" in backend.calls[0].user


def test_actants_repair_handles_cyrillic_contamination() -> None:
    original = _item(
        0,
        mediador_justificacion=(
            "No aparece un сельскохозяйственный mediador distinto de la fuente fijada."
        ),
    )
    backend = FakeBackend(responses=[{"reemplazo": "agrícola"}])
    agent = ActantsAgent(backend, enabled_components=ACTANTS_COMPONENTS)

    repaired = agent._quality_control_item(original, _row())

    assert repaired.actantes.mediador.justificacion == (
        "No aparece un agrícola mediador distinto de la fuente fijada."
    )
    assert len(backend.calls) == 1


def test_actants_does_not_repair_non_latin_text_present_in_unit_input() -> None:
    original = _item(
        0,
        mediador_descripcion="Москва",
        mediador_justificacion="La mención Москва vehiculiza la fuente hacia el experienciador.",
    )
    backend = FakeBackend()
    agent = ActantsAgent(backend, enabled_components=ACTANTS_COMPONENTS)

    repaired = agent._quality_control_item(
        original,
        _row("La noticia proveniente de Москва provocó indignación."),
    )

    assert repaired == original
    assert backend.calls == []


def test_disabled_component_text_is_not_sent_to_quality_repair() -> None:
    original = _item(
        0,
        mediador_justificacion=(
            "No existe तीसरा mediador entre la fuente fijada y el experienciador."
        ),
    )
    backend = FakeBackend()
    agent = ActantsAgent(
        backend,
        enabled_components=(
            "verificador_normativo",
            "verificador_observacional",
            "operador_modificacion",
            "polaridad",
        ),
    )

    repaired = agent._quality_control_item(original, _row())

    assert repaired == original
    assert backend.calls == []


def test_failed_repair_marks_only_its_item_and_preserves_batch_sibling() -> None:
    contaminated = _item(
        0,
        mediador_justificacion=(
            "No existe तीसरा mediador entre la fuente fijada y el experienciador."
        ),
    )
    clean = _item(1)
    batch_response = ListaActantesBatchSchema([contaminated, clean])
    backend = FakeBackend(
        responses=[
            batch_response,
            {"reemplazo": "третий"},
        ]
    )
    agent = ActantsAgent(backend, enabled_components=ACTANTS_COMPONENTS)
    df = pd.DataFrame([_row().to_dict(), _row("La decisión produjo alegría.").to_dict()])

    out = agent.run(df)

    assert pd.isna(out.loc[0, "mediador_presente"])
    assert "OutputQualityError" in out.loc[0, agent.ERROR_COLUMN]
    assert "escritura inesperada" in out.loc[0, agent.ERROR_COLUMN]
    assert out.loc[1, "mediador_presente"] == clean.actantes.mediador.presente
    assert out.loc[1, "mediador_justificacion"] == clean.actantes.mediador.justificacion
    assert pd.isna(out.loc[1].get(agent.ERROR_COLUMN))
