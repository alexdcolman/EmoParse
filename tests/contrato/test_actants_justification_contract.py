"""Contrato duro de justificaciones y componentes deshabilitados de ACTANTS."""

from __future__ import annotations

import pandas as pd
import pytest
from pydantic import ValidationError

from emoparse.agents.actants import (
    ACTANTS_COMPONENTS,
    ActantsAgent,
    _disabled_mediador,
    _disabled_operador_modificacion,
    _disabled_polaridad,
    _disabled_verificador_normativo,
    _disabled_verificador_observacional,
)
from emoparse.core.grammar import schema_to_gbnf
from emoparse.core.prompts import actants as prompts
from emoparse.core.schemas import ListaActantesBatchSchema, MediadorSchema
from tests.factories import FakeBackend


def _mediador(justificacion: str) -> MediadorSchema:
    return MediadorSchema(
        presente=False,
        descripcion=None,
        tipo="ausente",
        justificacion=justificacion,
    )


@pytest.mark.parametrize(
    "texto",
    [
        "El vínculo es directo y no presenta mediación.",
        "La expresión 'nació la pasión' afirma la emoción.",
        "No hay evidencia textual suficiente para identificar un mediador.",
    ],
)
def test_actants_justification_accepts_complete_sentence_without_double_quotes(
    texto: str,
) -> None:
    assert _mediador(texto).justificacion == texto


@pytest.mark.parametrize(
    "texto",
    [
        "El discurso describe la existencia de la pasión (",
        "El discurso describe el sentimiento (",
        "El discurso describe una postura (",
        "El discurso describe una condición económica (",
        'La frase "nació la pasión" afirma la emoción.',
        "No termina con puntuación",
        "Corto.",
        "Dos líneas\nno corresponden.",
    ],
)
def test_actants_justification_rejects_known_failure_shapes(texto: str) -> None:
    with pytest.raises(ValidationError):
        _mediador(texto)


def test_actants_grammar_has_hard_sentence_rule_only_for_justifications() -> None:
    grammar = schema_to_gbnf(ListaActantesBatchSchema, max_items=1)

    assert 'actants-justification-char ::= [^"\\\\\\x7F\\x00-\\x1F]' in grammar
    assert "actants-justification-8-240 ::=" in grammar
    assert "x-emoparse-gbnf" not in ListaActantesBatchSchema.model_json_schema().__repr__()
    assert '[.!?] "\\""' in grammar
    # La primitiva global permanece disponible e idéntica para otros strings.
    assert 'string ::= "\\"" strchar ( strsep? strchar )* "\\""' in grammar


def test_all_enabled_prompt_does_not_expose_disabled_placeholder_or_instruction() -> None:
    prompt = prompts.render_system(
        enabled_components=ACTANTS_COMPONENTS,
        disabled_components=(),
    )

    assert "componente deshabilitado por configuración" not in prompt
    assert "Componentes fuera de análisis en este run" not in prompt


def test_partial_prompt_names_disabled_components_without_canonical_placeholder() -> None:
    prompt = prompts.render_system(
        enabled_components=("operador_modificacion", "polaridad"),
        disabled_components=(
            "mediador",
            "verificador_normativo",
            "verificador_observacional",
        ),
    )

    assert "Componentes fuera de análisis en este run" in prompt
    assert "mediador" in prompt
    assert "verificador_normativo" in prompt
    assert "verificador_observacional" in prompt
    assert "componente deshabilitado por configuración" not in prompt


def test_deterministic_disabled_placeholders_satisfy_new_contract() -> None:
    placeholders = (
        _disabled_mediador(),
        _disabled_verificador_normativo(),
        _disabled_verificador_observacional(),
        _disabled_operador_modificacion(),
        _disabled_polaridad(),
    )
    for item in placeholders:
        assert item.justificacion == "componente deshabilitado por configuración."


def test_agent_component_universe_remains_unchanged() -> None:
    assert ACTANTS_COMPONENTS == (
        "mediador",
        "verificador_normativo",
        "verificador_observacional",
        "operador_modificacion",
        "polaridad",
    )


def test_actants_user_prompt_exposes_fixed_source_and_mark() -> None:
    agent = ActantsAgent(FakeBackend(), enabled_components=ACTANTS_COMPONENTS)
    batch = pd.DataFrame(
        [
            {
                "codigo": "doc:1",
                "frase": "La medida fue presentada como una vulneración de derechos.",
                "experienciador": "actor canónico",
                "fuente_inferencia": "la medida",
                "fuente_marca": "La medida",
                "tipo_emocion": "indignación",
                "modo_existencia": "efectiva",
                "tipo_configuracion": "indicadores axiológicos",
            }
        ]
    )

    user = agent._build_user(batch)

    assert "Experienciador:    actor canónico" in user
    assert "Fuente fijada:     la medida" in user
    assert "Marca de fuente:   La medida" in user
    assert "Frase de origen:   La medida fue presentada" in user


def test_actants_normative_rule_is_generic_and_source_anchored() -> None:
    from pathlib import Path

    root = Path(__file__).parents[2]
    heuristics = (root / "knowledge/heuristicas/actants.md").read_text(encoding="utf-8")
    template = (root / "src/emoparse/core/prompts/templates/actants_system.jinja2").read_text(
        encoding="utf-8"
    )

    markers = (
        "Puede hacerlo directamente",
        "tipifica la fuente",
        "fundamento explícito",
        "Debe poder nombrarse la norma",
        "`evaluacion=legitima` valida la emoción",
        "no significa que la fuente sea ilegítima o transgresora",
    )
    for marker in markers:
        assert marker in heuristics
        assert marker not in template
