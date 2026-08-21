"""Contratos del alcance acotado de `judge`."""

from __future__ import annotations

from pathlib import Path
from typing import get_args

import pytest
from pydantic import TypeAdapter, ValidationError

from emoparse.core.grammar import schema_to_gbnf
from emoparse.core.schemas import (
    CampoCorregible,
    CorreccionElementoSchema,
    JuicioBatchItemSchema,
    JuicioLLMBatchItemSchema,
    JuicioSchema,
    ListaJuiciosBatchSchema,
    ListaJuiciosLLMBatchSchema,
)

ROOT = Path(__file__).parents[2]


def test_judge_correctable_fields_exclude_characterizer_fine_dimensions() -> None:
    fields = set(get_args(CampoCorregible))
    forbidden = {
        "foria",
        "dominancia",
        "intensidad",
        "duracion",
        "duración",
        "tipo_atribucion",
        "atribucion",
        "atribución",
        "aspecto",
    }
    assert fields.isdisjoint(forbidden)
    assert {
        "experienciador",
        "tipo_emocion",
        "fuente_inferencia",
        "modo_existencia",
        "caracterizacion.temporalidad",
        "actantes.polaridad.tipo",
    }.issubset(fields)


def test_judge_heuristics_do_not_reopen_excluded_dimensions() -> None:
    heuristics = (ROOT / "knowledge/heuristicas/judge.md").read_text(encoding="utf-8").lower()
    for forbidden in ("foria", "dominancia", "intensidad", "duración", "atribución"):
        assert forbidden not in heuristics, forbidden

    for marker in (
        "umbral de corrección",
        "misma entidad",
        "marca experienciador",
        "marca fuente",
        "experienciador y fuente",
        "discurso referido",
        "tipo de emoción y modo de existencia",
        "temporalidad",
        "actantes",
        "verificador normativo",
        "polaridad",
        "materialmente distinta",
        "polaridad no es valencia afectiva",
        "inducida_proyectada",
        "el agente responsable de una fuente",
        "condenar la fuente no deslegitima",
        "presunción de coherencia",
        "no reanalizar el simulacro desde cero",
        "la sintaxis local y las marcas explícitas pesan más",
        "la tercera persona",
        "más de una emoción a la vez",
        "tono global",
        "pobreza/daño",
    ):
        assert marker in heuristics, marker


def test_judge_template_explicitly_excludes_characterizer_fine_dimensions() -> None:
    template = (
        (ROOT / "src/emoparse/core/prompts/templates/judge_system.jinja2")
        .read_text(encoding="utf-8")
        .lower()
    )
    assert "no evalúes ni" in template
    for forbidden in ("foria", "dominancia", "intensidad", "duración", "atribución"):
        assert forbidden in template, forbidden


def test_judge_suggestions_are_required_but_may_be_empty() -> None:
    required = set(ListaJuiciosBatchSchema.model_json_schema()["$defs"]["JuicioSchema"]["required"])
    assert "sugerencias" in required


def test_judge_reception_schema_compiles_field_value_coupling_to_gbnf() -> None:
    grammar = schema_to_gbnf(ListaJuiciosLLMBatchSchema, max_items=1)
    for field in ("coherente", "sugerencias", "campo", "valor_sugerido"):
        assert field.replace("_", "-") in grammar or field in grammar, field
    for valid in (
        "argumentacion_de_la_emocion",
        "persuasion_afectiva",
        "activacion_emocional",
        "inhibicion",
        "afirmada",
        "negada_factual",
    ):
        assert valid in grammar
    assert "promesa_reductora" not in grammar
    assert "afirmada_factual" not in grammar


def test_judge_union_fields_match_campo_corregible() -> None:
    union_fields = {
        get_args(model.model_fields["campo"].annotation)[0]
        for model in get_args(CorreccionElementoSchema)
    }
    assert union_fields == set(get_args(CampoCorregible))


def test_judge_closed_suggestion_values_are_rejected_by_schema() -> None:
    adapter = TypeAdapter(CorreccionElementoSchema)
    with pytest.raises(ValidationError):
        adapter.validate_python(
            {
                "campo": "actantes.operador_modificacion.funcion",
                "valor_sugerido": "promesa_reductora",
            }
        )
    with pytest.raises(ValidationError):
        adapter.validate_python(
            {
                "campo": "actantes.polaridad.tipo",
                "valor_sugerido": "afirmada_factual",
            }
        )
    assert (
        adapter.validate_python(
            {
                "campo": "actantes.operador_modificacion.funcion",
                "valor_sugerido": "persuasion_afectiva",
            }
        ).valor_sugerido
        == "persuasion_afectiva"
    )


def test_judge_user_prompt_includes_textual_marks() -> None:
    source = (ROOT / "src/emoparse/agents/judge.py").read_text(encoding="utf-8")
    assert "Marca experienciador:" in source
    assert "experienciador_marca" in source
    assert "Marca fuente:" in source
    assert "fuente_marca" in source


def test_judge_rejects_duplicate_suggestion_fields() -> None:
    with pytest.raises(ValidationError):
        JuicioSchema.model_validate(
            {
                "coherente": False,
                "sugerencias": [
                    {"campo": "modo_existencia", "valor_sugerido": "actual"},
                    {"campo": "modo_existencia", "valor_sugerido": "potencial"},
                ],
                "issues": "Modo inconsistente.",
                "confianza": "alta",
            }
        )


def test_judge_verdict_and_suggestions_are_consistent() -> None:
    with pytest.raises(ValidationError):
        JuicioSchema.model_validate(
            {
                "coherente": True,
                "sugerencias": [{"campo": "modo_existencia", "valor_sugerido": "actual"}],
                "issues": "no identificado",
                "confianza": "alta",
            }
        )

    with pytest.raises(ValidationError):
        JuicioSchema.model_validate(
            {
                "coherente": False,
                "sugerencias": [],
                "issues": "Modo inconsistente.",
                "confianza": "alta",
            }
        )

    ok = JuicioSchema.model_validate(
        {
            "coherente": False,
            "sugerencias": [{"campo": "modo_existencia", "valor_sugerido": "actual"}],
            "issues": "Modo inconsistente.",
            "confianza": "alta",
        }
    )
    assert ok.sugerencias[0].campo == "modo_existencia"


def test_judge_collapses_only_exact_duplicate_suggestions() -> None:
    exact = JuicioSchema.model_validate(
        {
            "coherente": False,
            "sugerencias": [
                {"campo": "modo_existencia", "valor_sugerido": "actual"},
                {"campo": "modo_existencia", "valor_sugerido": "actual"},
            ],
            "issues": "Modo inconsistente.",
            "confianza": "alta",
        }
    )
    assert len(exact.sugerencias) == 1
    assert exact.sugerencias[0].campo == "modo_existencia"
    assert exact.sugerencias[0].valor_sugerido == "actual"

    with pytest.raises(ValidationError):
        JuicioSchema.model_validate(
            {
                "coherente": False,
                "sugerencias": [
                    {"campo": "modo_existencia", "valor_sugerido": "actual"},
                    {"campo": "modo_existencia", "valor_sugerido": "potencial"},
                ],
                "issues": "Modo inconsistente.",
                "confianza": "alta",
            }
        )


def _judge_item(
    *, coherente: bool, sugerencias: list[dict[str, object]], issues: str = "Error material."
):
    from emoparse.core.schemas import JuicioBatchItemSchema

    return JuicioBatchItemSchema.model_validate(
        {
            "unit_idx": 0,
            "juicio": {
                "coherente": coherente,
                "sugerencias": sugerencias,
                "issues": issues if not coherente else "no identificado",
                "confianza": "alta",
            },
        }
    )


def test_judge_drops_exact_noop_and_normalizes_empty_false_verdict() -> None:
    import pandas as pd

    from emoparse.agents.judge import JudgeAgent

    item = _judge_item(
        coherente=False,
        sugerencias=[{"campo": "fuente_inferencia", "valor_sugerido": "el gobierno anterior"}],
    )
    row = pd.Series({"fuente_inferencia": "el gobierno anterior"})
    agent = object.__new__(JudgeAgent)
    out = agent._map_item_to_columns(item, row)
    assert out == {
        "coherente": True,
        "issues": "no identificado",
        "confianza": "alta",
        "sugerencias": [],
    }


def test_judge_drops_only_noops_and_preserves_material_suggestion() -> None:
    import pandas as pd

    from emoparse.agents.judge import JudgeAgent

    item = _judge_item(
        coherente=False,
        sugerencias=[
            {"campo": "fuente_inferencia", "valor_sugerido": "el gobierno anterior"},
            {"campo": "modo_existencia", "valor_sugerido": "potencial"},
        ],
    )
    row = pd.Series({"fuente_inferencia": "el gobierno anterior", "modo_existencia": "actual"})
    agent = object.__new__(JudgeAgent)
    out = agent._map_item_to_columns(item, row)
    assert out["coherente"] is False
    assert out["issues"] == "Error material."
    assert out["sugerencias"] == [{"campo": "modo_existencia", "valor_sugerido": "potencial"}]


def test_judge_drops_nested_actant_noop_but_not_near_paraphrase() -> None:
    import json

    import pandas as pd

    from emoparse.agents.judge import JudgeAgent

    agent = object.__new__(JudgeAgent)
    nested = _judge_item(
        coherente=False,
        sugerencias=[{"campo": "actantes.polaridad.tipo", "valor_sugerido": "afirmada"}],
    )
    row = pd.Series({"actantes_payload": json.dumps({"polaridad": {"tipo": "afirmada"}})})
    out = agent._map_item_to_columns(nested, row)
    assert out["coherente"] is True
    assert out["sugerencias"] == []

    paraphrase = _judge_item(
        coherente=False,
        sugerencias=[{"campo": "fuente_inferencia", "valor_sugerido": "gobierno anterior"}],
    )
    out2 = agent._map_item_to_columns(
        paraphrase, pd.Series({"fuente_inferencia": "el gobierno anterior"})
    )
    assert out2["coherente"] is False
    assert out2["sugerencias"] == [
        {"campo": "fuente_inferencia", "valor_sugerido": "gobierno anterior"}
    ]


def _judge_llm_item(
    *,
    coherente: bool,
    sugerencias: list[dict[str, object]],
    issues: str = "Error material.",
) -> JuicioLLMBatchItemSchema:
    return JuicioLLMBatchItemSchema.model_validate(
        {
            "unit_idx": 0,
            "juicio": {
                "coherente": coherente,
                "sugerencias": sugerencias,
                "issues": issues if not coherente else "no identificado",
                "confianza": "alta",
            },
        }
    )


def test_judge_llm_reception_allows_duplicate_field_until_row_qc() -> None:
    item = _judge_llm_item(
        coherente=False,
        sugerencias=[
            {"campo": "modo_existencia", "valor_sugerido": "virtual"},
            {"campo": "modo_existencia", "valor_sugerido": "potencial"},
        ],
    )
    assert [s.valor_sugerido for s in item.juicio.sugerencias] == [
        "virtual",
        "potencial",
    ]


def test_judge_qc_drops_upstream_noop_before_duplicate_field_check() -> None:
    import pandas as pd

    from emoparse.agents.judge import JudgeAgent

    item = _judge_llm_item(
        coherente=False,
        sugerencias=[
            {"campo": "modo_existencia", "valor_sugerido": "virtual"},
            {"campo": "modo_existencia", "valor_sugerido": "potencial"},
        ],
        issues="Inversión de polaridad: la liberación es el objetivo, no una realidad.",
    )
    agent = object.__new__(JudgeAgent)
    checked = agent._quality_control_item(item, pd.Series({"modo_existencia": "potencial"}))
    assert isinstance(checked, JuicioBatchItemSchema)
    assert checked.juicio.coherente is False
    assert [s.model_dump() for s in checked.juicio.sugerencias] == [
        {"campo": "modo_existencia", "valor_sugerido": "virtual"}
    ]


def test_judge_qc_still_rejects_two_material_values_for_same_field() -> None:
    import pandas as pd

    from emoparse.agents.judge import JudgeAgent
    from emoparse.core.backend.exceptions import BackendError

    item = _judge_llm_item(
        coherente=False,
        sugerencias=[
            {"campo": "modo_existencia", "valor_sugerido": "virtual"},
            {"campo": "modo_existencia", "valor_sugerido": "actual"},
        ],
    )
    agent = object.__new__(JudgeAgent)
    with pytest.raises(BackendError, match="correcciones materiales incompatibles"):
        agent._quality_control_item(item, pd.Series({"modo_existencia": "potencial"}))


def test_judge_qc_collapses_exact_material_duplicate() -> None:
    import pandas as pd

    from emoparse.agents.judge import JudgeAgent

    item = _judge_llm_item(
        coherente=False,
        sugerencias=[
            {"campo": "modo_existencia", "valor_sugerido": "virtual"},
            {"campo": "modo_existencia", "valor_sugerido": "virtual"},
        ],
    )
    agent = object.__new__(JudgeAgent)
    checked = agent._quality_control_item(item, pd.Series({"modo_existencia": "potencial"}))
    assert [s.model_dump() for s in checked.juicio.sugerencias] == [
        {"campo": "modo_existencia", "valor_sugerido": "virtual"}
    ]


def test_judge_qc_noop_only_becomes_canonical_coherent() -> None:
    import pandas as pd

    from emoparse.agents.judge import JudgeAgent

    item = _judge_llm_item(
        coherente=False,
        sugerencias=[{"campo": "modo_existencia", "valor_sugerido": "potencial"}],
    )
    agent = object.__new__(JudgeAgent)
    checked = agent._quality_control_item(item, pd.Series({"modo_existencia": "potencial"}))
    assert checked.juicio.coherente is True
    assert checked.juicio.issues == "no identificado"
    assert checked.juicio.sugerencias == []


def test_judge_agent_uses_reception_schema_not_canonical_schema() -> None:
    from emoparse.agents.judge import JudgeAgent

    assert JudgeAgent.SCHEMA is ListaJuiciosLLMBatchSchema
    assert JudgeAgent.SCHEMA is not ListaJuiciosBatchSchema


def test_judge_qc_does_not_hide_false_without_any_suggestion() -> None:
    import pandas as pd

    from emoparse.agents.judge import JudgeAgent
    from emoparse.core.backend.exceptions import BackendError

    item = _judge_llm_item(coherente=False, sugerencias=[])
    agent = object.__new__(JudgeAgent)
    with pytest.raises(BackendError, match="correcciones materiales incompatibles"):
        agent._quality_control_item(item, pd.Series({"modo_existencia": "potencial"}))
