# ══════════════════════════════════════════════════════════════════════════════
#  tests.unit.test_actantes_schema
#
#  Cobertura del schema ActantesEmocionSchema y sus sub-schemas:
#  validación de Literals, presencia/ausencia uniforme, extra="forbid"
#  y batch wrapper.
# ══════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

import pytest
from pydantic import ValidationError

from emoparse.core.schemas import (
    ActantesBatchItemSchema,
    ActantesEmocionSchema,
    ListaActantesBatchSchema,
    MediadorSchema,
    OperadorModificacionSchema,
    VerificadorNormativoSchema,
    VerificadorObservacionalSchema,
)


# ══════════════════════════════════════════════════════════════════════════════
#  Sub-schemas: presencia, ausencia y Literals
# ══════════════════════════════════════════════════════════════════════════════


class TestMediadorSchema:

    def test_presente_acepta_descripcion_y_tipo_concreto(self) -> None:
        m = MediadorSchema(
            presente=True,
            descripcion="el propio discurso",
            tipo="discurso_propio",
            justificacion="El enunciador busca activar la emoción.",
        )
        assert m.presente is True
        assert m.tipo == "discurso_propio"
        assert m.descripcion == "el propio discurso"

    def test_ausente_acepta_descripcion_null_y_tipo_ausente(self) -> None:
        m = MediadorSchema(
            presente=False,
            descripcion=None,
            tipo="ausente",
            justificacion="No hay vehículo identificable.",
        )
        assert m.presente is False
        assert m.descripcion is None
        assert m.tipo == "ausente"

    def test_descripcion_default_es_none(self) -> None:
        m = MediadorSchema(
            presente=False,
            tipo="ausente",
            justificacion="x",
        )
        assert m.descripcion is None

    @pytest.mark.parametrize(
        "tipo",
        [
            "discurso_propio",
            "discurso_ajeno",
            "documento_o_registro",
            "objeto_o_artefacto",
            "espacio_o_escena",
            "accion_o_comportamiento",
            "ausente",
        ],
    )
    def test_acepta_todos_los_tipos_validos(self, tipo: str) -> None:
        m = MediadorSchema(presente=True, tipo=tipo, justificacion="x")
        assert m.tipo == tipo

    def test_rechaza_tipo_invalido(self) -> None:
        with pytest.raises(ValidationError):
            MediadorSchema(
                presente=True,
                tipo="categoria_inexistente",
                justificacion="x",
            )

    def test_extra_forbid_activo(self) -> None:
        with pytest.raises(ValidationError):
            MediadorSchema(
                presente=True,
                tipo="ausente",
                justificacion="x",
                campo_extra="nope",  # type: ignore[call-arg]
            )


class TestVerificadorNormativoSchema:

    @pytest.mark.parametrize(
        "tipo",
        [
            "norma_sociocultural",
            "norma_moral_o_etica",
            "norma_juridica_o_institucional",
            "norma_ideologica_o_politica",
            "norma_estetica_o_de_gusto",
            "ausente",
        ],
    )
    def test_acepta_todos_los_tipos(self, tipo: str) -> None:
        v = VerificadorNormativoSchema(
            presente=True, tipo=tipo,
            evaluacion="legitima", justificacion="x",
        )
        assert v.tipo == tipo

    @pytest.mark.parametrize(
        "evaluacion", ["legitima", "deslegitima", "sin_evaluacion"]
    )
    def test_acepta_todas_las_evaluaciones(self, evaluacion: str) -> None:
        v = VerificadorNormativoSchema(
            presente=True, tipo="norma_sociocultural",
            evaluacion=evaluacion, justificacion="x",
        )
        assert v.evaluacion == evaluacion

    def test_rechaza_evaluacion_invalida(self) -> None:
        with pytest.raises(ValidationError):
            VerificadorNormativoSchema(
                presente=True, tipo="norma_sociocultural",
                evaluacion="otra_cosa", justificacion="x",
            )


class TestVerificadorObservacionalSchema:

    @pytest.mark.parametrize(
        "tipo",
        [
            "cuestionamiento_de_autenticidad",
            "reinterpretacion_del_desencadenante",
            "corroboracion_de_autenticidad",
            "corroboracion_del_desencadenante",
            "ausente",
        ],
    )
    def test_acepta_todos_los_tipos(self, tipo: str) -> None:
        v = VerificadorObservacionalSchema(
            presente=True, tipo=tipo,
            evaluacion="realizada", justificacion="x",
        )
        assert v.tipo == tipo

    @pytest.mark.parametrize(
        "evaluacion", ["realizada", "no_realizada", "sin_evaluacion"]
    )
    def test_acepta_todas_las_evaluaciones(self, evaluacion: str) -> None:
        v = VerificadorObservacionalSchema(
            presente=False, tipo="ausente",
            evaluacion=evaluacion, justificacion="x",
        )
        assert v.evaluacion == evaluacion


class TestOperadorModificacionSchema:

    @pytest.mark.parametrize(
        "funcion",
        [
            "argumentacion_de_la_emocion",
            "persuasion_afectiva",
            "activacion_emocional",
            "inhibicion",
            "ausente",
        ],
    )
    def test_acepta_todas_las_funciones(self, funcion: str) -> None:
        o = OperadorModificacionSchema(
            presente=True, funcion=funcion, justificacion="x",
        )
        assert o.funcion == funcion

    def test_rechaza_funcion_invalida(self) -> None:
        with pytest.raises(ValidationError):
            OperadorModificacionSchema(
                presente=True, funcion="manipulacion_x", justificacion="x",
            )


# ══════════════════════════════════════════════════════════════════════════════
#  Schema compuesto y batch
# ══════════════════════════════════════════════════════════════════════════════


def _full_actantes(**overrides):
    """Helper: actantes válidos con todos los componentes presentes."""
    base = ActantesEmocionSchema(
        mediador=MediadorSchema(
            presente=True, descripcion="discurso del enunciador",
            tipo="discurso_propio",
            justificacion="El propio enunciado opera como vehículo.",
        ),
        verificador_normativo=VerificadorNormativoSchema(
            presente=True, descripcion="evaluación moral",
            tipo="norma_moral_o_etica", evaluacion="legitima",
            justificacion="Se valida la emoción.",
        ),
        verificador_observacional=VerificadorObservacionalSchema(
            presente=False, descripcion=None, tipo="ausente",
            evaluacion="sin_evaluacion",
            justificacion="No se cuestiona la autenticidad.",
        ),
        operador_modificacion=OperadorModificacionSchema(
            presente=True, descripcion="activación afectiva",
            funcion="activacion_emocional",
            justificacion="Se busca generar indignación.",
        ),
    )
    return base


class TestActantesEmocionSchema:

    def test_actantes_completos_son_validos(self) -> None:
        a = _full_actantes()
        assert a.mediador.tipo == "discurso_propio"
        assert a.operador_modificacion.funcion == "activacion_emocional"

    def test_todos_los_componentes_ausentes_es_valido(self) -> None:
        a = ActantesEmocionSchema(
            mediador=MediadorSchema(
                presente=False, tipo="ausente", justificacion="x",
            ),
            verificador_normativo=VerificadorNormativoSchema(
                presente=False, tipo="ausente",
                evaluacion="sin_evaluacion", justificacion="x",
            ),
            verificador_observacional=VerificadorObservacionalSchema(
                presente=False, tipo="ausente",
                evaluacion="sin_evaluacion", justificacion="x",
            ),
            operador_modificacion=OperadorModificacionSchema(
                presente=False, funcion="ausente", justificacion="x",
            ),
        )
        assert a.mediador.presente is False
        assert a.operador_modificacion.presente is False

    def test_falta_sub_componente_falla(self) -> None:
        with pytest.raises(ValidationError):
            ActantesEmocionSchema(  # type: ignore[call-arg]
                mediador=MediadorSchema(
                    presente=False, tipo="ausente", justificacion="x",
                ),
                # falta verificador_normativo
                verificador_observacional=VerificadorObservacionalSchema(
                    presente=False, tipo="ausente",
                    evaluacion="sin_evaluacion", justificacion="x",
                ),
                operador_modificacion=OperadorModificacionSchema(
                    presente=False, funcion="ausente", justificacion="x",
                ),
            )

    def test_extra_forbid_en_compuesto(self) -> None:
        with pytest.raises(ValidationError):
            ActantesEmocionSchema(  # type: ignore[call-arg]
                mediador=MediadorSchema(
                    presente=False, tipo="ausente", justificacion="x",
                ),
                verificador_normativo=VerificadorNormativoSchema(
                    presente=False, tipo="ausente",
                    evaluacion="sin_evaluacion", justificacion="x",
                ),
                verificador_observacional=VerificadorObservacionalSchema(
                    presente=False, tipo="ausente",
                    evaluacion="sin_evaluacion", justificacion="x",
                ),
                operador_modificacion=OperadorModificacionSchema(
                    presente=False, funcion="ausente", justificacion="x",
                ),
                campo_extra="nope",
            )


class TestActantesBatch:

    def test_batch_item_acepta_unit_idx_y_actantes(self) -> None:
        item = ActantesBatchItemSchema(unit_idx=3, actantes=_full_actantes())
        assert item.unit_idx == 3
        assert item.actantes.mediador.tipo == "discurso_propio"

    def test_lista_batch_acepta_multiples_items(self) -> None:
        batch = ListaActantesBatchSchema(
            root=[
                ActantesBatchItemSchema(unit_idx=0, actantes=_full_actantes()),
                ActantesBatchItemSchema(unit_idx=1, actantes=_full_actantes()),
            ]
        )
        assert len(batch.root) == 2
        assert batch.root[1].unit_idx == 1
