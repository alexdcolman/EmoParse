# ══════════════════════════════════════════════════════════════════════════════
#  tests.unit.test_actants_agent
#
#  Cobertura del ActantsAgent: composición del system prompt según
#  enabled_components, mapeo del schema a columnas planas, comportamiento
#  determinístico ante componentes deshabilitados.
# ══════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

from typing import TypeVar

import pandas as pd
import pytest
from pydantic import BaseModel

from emoparse.agents.actants import (
    ACTANTS_COMPONENTS,
    ActantsAgent,
)
from emoparse.core.backend.base import LLMBackend, LLMResponse, TokenUsage
from emoparse.core.schemas import (
    ActantesBatchItemSchema,
    ActantesEmocionSchema,
    ListaActantesBatchSchema,
    MediadorSchema,
    OperadorModificacionSchema,
    VerificadorNormativoSchema,
    VerificadorObservacionalSchema,
)

T = TypeVar("T", bound=BaseModel)


class _FakeBackend(LLMBackend):
    def __init__(self, responses: list[BaseModel | Exception]) -> None:
        self.alias = "fake"
        self._responses = list(responses)
        self.calls: list[dict[str, object]] = []

    def generate(
        self,
        system: str,
        user: str,
        *,
        schema: type[T] | None = None,
        max_tokens: int | None = None,
        temperature: float | None = None,
        seed: int | None = None,
        stop: list[str] | None = None,
        reset_before: bool = False,
    ) -> LLMResponse:
        self.calls.append({"system": system, "user": user})
        nxt = self._responses.pop(0)
        if isinstance(nxt, Exception):
            raise nxt
        return LLMResponse(
            parsed=nxt, raw="(fake)",
            usage=TokenUsage(prompt_tokens=10, completion_tokens=20),
            latency_ms=1.0, model_alias=self.alias,
            cache_hit=False, finish_reason="stop",
        )

    def healthcheck(self) -> bool:
        return True


def _full_actantes_response(unit_idx: int = 0) -> ActantesBatchItemSchema:
    """Helper: response del LLM con los 4 componentes presentes."""
    return ActantesBatchItemSchema(
        unit_idx=unit_idx,
        actantes=ActantesEmocionSchema(
            mediador=MediadorSchema(
                presente=True, descripcion="el propio discurso",
                tipo="discurso_propio",
                justificacion="El enunciador vehiculiza la emoción.",
            ),
            verificador_normativo=VerificadorNormativoSchema(
                presente=True, descripcion="norma moral",
                tipo="norma_moral_o_etica", evaluacion="legitima",
                justificacion="Se valida la emoción.",
            ),
            verificador_observacional=VerificadorObservacionalSchema(
                presente=False, descripcion=None, tipo="ausente",
                evaluacion="sin_evaluacion",
                justificacion="No se evalúa autenticidad.",
            ),
            operador_modificacion=OperadorModificacionSchema(
                presente=True, descripcion="apelación",
                funcion="activacion_emocional",
                justificacion="Se busca generar la emoción.",
            ),
        ),
    )


def _resp(items: list[ActantesBatchItemSchema]) -> ListaActantesBatchSchema:
    return ListaActantesBatchSchema(root=items)


def _emocion_row(unit_idx: int = 0, **overrides) -> dict:
    base = {
        "codigo": "A",
        "frase_idx": unit_idx,
        "emocion_idx": 0,
        "experienciador": "el pueblo",
        "tipo_emocion": "indignación",
        "modo_existencia": "realizada",
        "tipo_configuracion": "cualificacion_por_indicadores_axiologicos",
        "frase": "Hay razones para indignarse.",
    }
    base.update(overrides)
    return base


# ══════════════════════════════════════════════════════════════════════════════
#  System prompt
# ══════════════════════════════════════════════════════════════════════════════


class TestSystemPrompt:

    def test_incluye_definiciones_de_los_cuatro_componentes_por_default(self) -> None:
        backend = _FakeBackend([_resp([_full_actantes_response()])])
        agent = ActantsAgent(
            backend,
            titulo="Discurso X",
            tipo_discurso="discurso político",
            heuristicas="HEURISTICA_MARK",
        )
        df = pd.DataFrame([_emocion_row()])
        agent.run(df)

        system = backend.calls[0]["system"]
        assert "MEDIADOR" in system
        assert "VERIFICADOR NORMATIVO" in system
        assert "VERIFICADOR OBSERVACIONAL" in system
        assert "OPERADOR DE MODIFICACIÓN" in system
        assert "HEURISTICA_MARK" in system

    def test_filtra_componentes_no_habilitados(self) -> None:
        backend = _FakeBackend([_resp([_full_actantes_response()])])
        agent = ActantsAgent(
            backend,
            enabled_components=("mediador",),
        )
        df = pd.DataFrame([_emocion_row()])
        agent.run(df)

        system = backend.calls[0]["system"]
        assert "MEDIADOR" in system
        assert "VERIFICADOR NORMATIVO" not in system
        assert "OPERADOR DE MODIFICACIÓN" not in system

    def test_rechaza_componentes_desconocidos(self) -> None:
        backend = _FakeBackend([])
        with pytest.raises(ValueError):
            ActantsAgent(
                backend,
                enabled_components=("mediador", "componente_invalido"),
            )

    def test_rechaza_lista_vacia_de_componentes(self) -> None:
        backend = _FakeBackend([])
        with pytest.raises(ValueError):
            ActantsAgent(backend, enabled_components=())


# ══════════════════════════════════════════════════════════════════════════════
#  User prompt
# ══════════════════════════════════════════════════════════════════════════════


class TestUserPrompt:

    def test_incluye_contexto_de_la_emocion(self) -> None:
        backend = _FakeBackend([_resp([_full_actantes_response()])])
        agent = ActantsAgent(backend)
        df = pd.DataFrame([
            _emocion_row(
                experienciador="el pueblo",
                tipo_emocion="indignación",
                modo_existencia="realizada",
                frase="Hay razones para indignarse.",
            )
        ])
        agent.run(df)

        user = backend.calls[0]["user"]
        assert "el pueblo" in user
        assert "indignación" in user
        assert "realizada" in user
        assert "Hay razones para indignarse." in user

    def test_indexa_unidades_localmente_desde_cero(self) -> None:
        backend = _FakeBackend([
            _resp([
                _full_actantes_response(unit_idx=0),
                _full_actantes_response(unit_idx=1),
            ])
        ])
        agent = ActantsAgent(backend)
        df = pd.DataFrame([_emocion_row(0), _emocion_row(1)])
        agent.run(df)

        user = backend.calls[0]["user"]
        assert "EMOCIÓN [0]" in user
        assert "EMOCIÓN [1]" in user


# ══════════════════════════════════════════════════════════════════════════════
#  Output mapping
# ══════════════════════════════════════════════════════════════════════════════


class TestOutputMapping:

    def test_output_columns_declara_los_17_campos(self) -> None:
        # 4 del mediador, 5 de cada verificador (incluye evaluacion), 4 del op_mod = 18.
        # Verificamos contra la lista explícita.
        cols = set(ActantsAgent.OUTPUT_COLUMNS)
        expected = {
            "mediador_presente", "mediador_descripcion",
            "mediador_tipo", "mediador_justificacion",
            "verificador_normativo_presente",
            "verificador_normativo_descripcion",
            "verificador_normativo_tipo",
            "verificador_normativo_evaluacion",
            "verificador_normativo_justificacion",
            "verificador_observacional_presente",
            "verificador_observacional_descripcion",
            "verificador_observacional_tipo",
            "verificador_observacional_evaluacion",
            "verificador_observacional_justificacion",
            "operador_modificacion_presente",
            "operador_modificacion_descripcion",
            "operador_modificacion_funcion",
            "operador_modificacion_justificacion",
        }
        assert cols == expected

    def test_mapea_campos_planos_desde_schema_anidado(self) -> None:
        backend = _FakeBackend([_resp([_full_actantes_response()])])
        agent = ActantsAgent(backend)
        df = pd.DataFrame([_emocion_row()])
        out = agent.run(df)

        row = out.iloc[0]
        assert bool(row["mediador_presente"]) is True
        assert row["mediador_tipo"] == "discurso_propio"
        assert row["verificador_normativo_evaluacion"] == "legitima"
        assert bool(row["verificador_observacional_presente"]) is False
        assert row["verificador_observacional_descripcion"] is None
        assert row["operador_modificacion_funcion"] == "activacion_emocional"


# ══════════════════════════════════════════════════════════════════════════════
#  Placeholders determinísticos para componentes deshabilitados
# ══════════════════════════════════════════════════════════════════════════════


class TestDisabledComponents:

    def test_componente_deshabilitado_se_sobreescribe_con_placeholder(self) -> None:
        # El modelo devuelve un mediador "presente=True" pero el run lo
        # tiene deshabilitado: el agente debe reemplazarlo por placeholder.
        backend = _FakeBackend([_resp([_full_actantes_response()])])
        agent = ActantsAgent(
            backend,
            enabled_components=("verificador_normativo",),
        )
        df = pd.DataFrame([_emocion_row()])
        out = agent.run(df)

        row = out.iloc[0]
        # Mediador: deshabilitado → placeholder.
        assert bool(row["mediador_presente"]) is False
        assert row["mediador_tipo"] == "ausente"
        assert row["mediador_descripcion"] is None
        assert "deshabilitado" in str(row["mediador_justificacion"])
        # Verificador normativo: habilitado → respuesta del modelo.
        assert bool(row["verificador_normativo_presente"]) is True
        assert row["verificador_normativo_tipo"] == "norma_moral_o_etica"
        # Operador: deshabilitado → placeholder.
        assert bool(row["operador_modificacion_presente"]) is False
        assert row["operador_modificacion_funcion"] == "ausente"

    def test_todos_componentes_habilitados_no_modifica_respuesta(self) -> None:
        backend = _FakeBackend([_resp([_full_actantes_response()])])
        agent = ActantsAgent(backend, enabled_components=ACTANTS_COMPONENTS)
        df = pd.DataFrame([_emocion_row()])
        out = agent.run(df)

        row = out.iloc[0]
        # Todos los componentes mantienen los valores del modelo.
        assert bool(row["mediador_presente"]) is True
        assert row["mediador_tipo"] == "discurso_propio"
        assert row["operador_modificacion_funcion"] == "activacion_emocional"
