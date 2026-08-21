from __future__ import annotations

import re
from typing import Any

import pytest

from emoparse.core.backend.exceptions import SchemaViolationError
from emoparse.core.schemas import ModalidadRecoverySchema, ModalidadSchema
from emoparse.pipeline.stages import ModalidadStage
from tests.factories import FakeBackend


class _DiscursosRepo:
    def list_codigos(self) -> list[str]:
        return ["D001"]

    def get_payload(self, codigo: str, stage: str) -> dict[str, Any] | None:
        return {"resumen_global": "Discurso de prueba."}

    def get_input(self, codigo: str) -> dict[str, Any]:
        return {"contenido": "Discurso de prueba."}


class _MencionesRepo:
    def __init__(self, links: list[dict[str, Any]]) -> None:
        self.links = links
        self.writes: list[dict[str, Any]] = []

    def list_links_for_modalidad(self, codigo: str) -> list[dict[str, Any]]:
        return self.links

    def set_modalidad(
        self,
        mencion_id: int,
        canonical_id: str,
        modalidad: str | None,
        naturaleza: str | None,
        origin: str,
        **kwargs: Any,
    ) -> None:
        self.writes.append(
            {
                "mencion_id": mencion_id,
                "canonical_id": canonical_id,
                "modalidad": modalidad,
                "naturaleza": naturaleza,
                "origin": origin,
                **kwargs,
            }
        )


def _link(mid: int, canonical: str, *, marca: str = "tiró a la calle") -> dict[str, Any]:
    return {
        "mencion_id": mid,
        "canonical_id": canonical,
        "marca": marca,
        "frase": "El gobierno tiró a la calle a miles de personas.",
        "origen_vinculo": "llm",
        "deixis_tipo": None,
        "funciones": "actor",
        "llm_inferencia": canonical,
    }


def _force_ambiguous(stage: ModalidadStage) -> None:
    class _NLP:
        def classify(self, *args: Any, **kwargs: Any):
            from emoparse.pipeline.modalidad_nlp import ModalidadGuess

            return ModalidadGuess(None, confident=False)

    stage._nlp = _NLP()  # type: ignore[assignment]


@pytest.mark.unit
def test_link_id_distingue_dos_referentes_de_la_misma_marca() -> None:
    repo = _MencionesRepo([_link(10, "evento_expulsion"), _link(10, "gobierno")])
    response = ModalidadSchema.model_validate(
        {
            "clasificaciones": [
                {
                    "link_id": 0,
                    "modalidad": "predicacion",
                    "revisar_vinculo": False,
                    "justificacion": "Construye el evento.",
                },
                {
                    "link_id": 1,
                    "modalidad": "identificacion_inferencial",
                    "revisar_vinculo": False,
                    "justificacion": "Identifica al agente por la acción.",
                },
            ]
        }
    )
    backend = FakeBackend(responses=[response])
    stage = ModalidadStage(
        _DiscursosRepo(),  # type: ignore[arg-type]
        repo,  # type: ignore[arg-type]
        backend=backend,
        agent_version="v62",
        heuristicas="reglas",
        context_length=4096,
    )
    _force_ambiguous(stage)

    assert stage._classify_for_codigo("D001") == 2
    assert [(w["canonical_id"], w["modalidad"]) for w in repo.writes] == [
        ("evento_expulsion", "predicacion"),
        ("gobierno", "identificacion_inferencial"),
    ]
    assert "link_id=0" in backend.calls[0].user
    assert "link_id=1" in backend.calls[0].user
    assert backend.calls[0].max_tokens == 1024


@pytest.mark.unit
def test_item_incoherente_se_recupera_sin_descartar_su_hermano_valido() -> None:
    repo = _MencionesRepo([_link(10, "evento_expulsion"), _link(10, "gobierno")])
    backend = FakeBackend(
        responses=[
            {
                "clasificaciones": [
                    {
                        "link_id": 0,
                        "modalidad": "predicacion",
                        "revisar_vinculo": False,
                        "justificacion": "Construye el evento.",
                    },
                    {
                        "link_id": 1,
                        "modalidad": None,
                        "revisar_vinculo": False,
                        "justificacion": "Combinación incoherente deliberada.",
                    },
                ]
            },
            {
                "clasificaciones": [
                    {
                        "link_id": 1,
                        "modalidad": "identificacion_inferencial",
                        "revisar_vinculo": False,
                        "justificacion": "Identifica al agente por la acción.",
                    }
                ]
            },
        ]
    )
    stage = ModalidadStage(
        _DiscursosRepo(),  # type: ignore[arg-type]
        repo,  # type: ignore[arg-type]
        backend=backend,
        agent_version="v62",
        context_length=4096,
    )
    _force_ambiguous(stage)

    assert stage._classify_for_codigo("D001") == 2
    assert [(w["canonical_id"], w["modalidad"]) for w in repo.writes] == [
        ("evento_expulsion", "predicacion"),
        ("gobierno", "identificacion_inferencial"),
    ]
    assert len(backend.calls) == 2
    assert backend.calls[0].schema is ModalidadSchema
    assert backend.calls[1].schema is ModalidadRecoverySchema
    assert backend.calls[1].user.count("link_id=") == 1
    assert "link_id=1" in backend.calls[1].user
    assert stage.metrics.n_items_ok == 2
    assert stage.metrics.n_items_failed == 0


@pytest.mark.unit
def test_item_faltante_se_recupera_individualmente() -> None:
    repo = _MencionesRepo([_link(10, "evento_expulsion"), _link(10, "gobierno")])
    backend = FakeBackend(
        responses=[
            {
                "clasificaciones": [
                    {
                        "link_id": 0,
                        "modalidad": "predicacion",
                        "revisar_vinculo": False,
                        "justificacion": "Construye el evento.",
                    }
                ]
            },
            {
                "clasificaciones": [
                    {
                        "link_id": 1,
                        "modalidad": "identificacion_inferencial",
                        "revisar_vinculo": False,
                        "justificacion": "Identifica al agente por la acción.",
                    }
                ]
            },
        ]
    )
    stage = ModalidadStage(
        _DiscursosRepo(),  # type: ignore[arg-type]
        repo,  # type: ignore[arg-type]
        backend=backend,
        agent_version="v62",
        context_length=4096,
    )
    _force_ambiguous(stage)

    assert stage._classify_for_codigo("D001") == 2
    assert len(backend.calls) == 2
    assert "link_id=1" in backend.calls[1].user
    assert "link_id=0" not in backend.calls[1].user
    assert stage.metrics.n_items_ok == 2
    assert stage.metrics.n_items_failed == 0


@pytest.mark.unit
def test_item_duplicado_se_recupera_individualmente() -> None:
    repo = _MencionesRepo([_link(10, "evento_expulsion"), _link(10, "gobierno")])
    duplicate = {
        "link_id": 1,
        "modalidad": "identificacion_inferencial",
        "revisar_vinculo": False,
        "justificacion": "Identifica al agente por la acción.",
    }
    backend = FakeBackend(
        responses=[
            {
                "clasificaciones": [
                    {
                        "link_id": 0,
                        "modalidad": "predicacion",
                        "revisar_vinculo": False,
                        "justificacion": "Construye el evento.",
                    },
                    duplicate,
                    duplicate,
                ]
            },
            {"clasificaciones": [duplicate]},
        ]
    )
    stage = ModalidadStage(
        _DiscursosRepo(),  # type: ignore[arg-type]
        repo,  # type: ignore[arg-type]
        backend=backend,
        agent_version="v62",
        context_length=4096,
    )
    _force_ambiguous(stage)

    assert stage._classify_for_codigo("D001") == 2
    assert len(backend.calls) == 2
    assert stage.metrics.n_items_ok == 2
    assert stage.metrics.n_items_failed == 0


@pytest.mark.unit
def test_singleton_normal_coherente_usa_schema_normal_sin_recovery() -> None:
    repo = _MencionesRepo([_link(20, "referente_insostenible")])
    backend = FakeBackend(
        responses=[
            {
                "clasificaciones": [
                    {
                        "link_id": 0,
                        "modalidad": None,
                        "revisar_vinculo": True,
                        "justificacion": "La arista no está sostenida.",
                    }
                ]
            }
        ]
    )
    stage = ModalidadStage(
        _DiscursosRepo(),  # type: ignore[arg-type]
        repo,  # type: ignore[arg-type]
        backend=backend,
        agent_version="v62",
        context_length=4096,
    )
    _force_ambiguous(stage)

    assert stage._classify_for_codigo("D001") == 1
    assert len(backend.calls) == 1
    assert backend.calls[0].schema is ModalidadSchema
    assert stage.metrics.n_items_ok == 1
    assert stage.metrics.n_items_failed == 0


@pytest.mark.unit
def test_singleton_normal_incoherente_hace_un_recovery_estricto() -> None:
    repo = _MencionesRepo([_link(20, "referente_insostenible")])
    backend = FakeBackend(
        responses=[
            {
                "clasificaciones": [
                    {
                        "link_id": 0,
                        "modalidad": None,
                        "revisar_vinculo": False,
                        "justificacion": "Salida incoherente deliberada.",
                    }
                ]
            },
            {
                "clasificaciones": [
                    {
                        "link_id": 0,
                        "modalidad": None,
                        "revisar_vinculo": True,
                        "justificacion": "La arista no está sostenida.",
                    }
                ]
            },
        ]
    )
    stage = ModalidadStage(
        _DiscursosRepo(),  # type: ignore[arg-type]
        repo,  # type: ignore[arg-type]
        backend=backend,
        agent_version="v62",
        context_length=4096,
    )
    _force_ambiguous(stage)

    assert stage._classify_for_codigo("D001") == 1
    assert len(backend.calls) == 2
    assert backend.calls[0].schema is ModalidadSchema
    assert backend.calls[1].schema is ModalidadRecoverySchema
    assert repo.writes[0]["review_reason"] == "La arista no está sostenida."
    assert stage.metrics.n_items_ok == 1
    assert stage.metrics.n_items_failed == 0


@pytest.mark.unit
def test_singleton_recovery_fallido_queda_pendiente_sin_tercer_intento() -> None:
    repo = _MencionesRepo([_link(20, "referente_insostenible")])
    backend = FakeBackend(
        responses=[
            {
                "clasificaciones": [
                    {
                        "link_id": 0,
                        "modalidad": None,
                        "revisar_vinculo": False,
                        "justificacion": "Salida incoherente deliberada.",
                    }
                ]
            },
            {
                "clasificaciones": [
                    {
                        "link_id": 999,
                        "modalidad": None,
                        "revisar_vinculo": True,
                        "justificacion": "ID incorrecto deliberado.",
                    }
                ]
            },
        ]
    )
    stage = ModalidadStage(
        _DiscursosRepo(),  # type: ignore[arg-type]
        repo,  # type: ignore[arg-type]
        backend=backend,
        agent_version="v62",
        context_length=4096,
    )
    _force_ambiguous(stage)

    assert stage._classify_for_codigo("D001") == 0
    assert repo.writes == []
    assert len(backend.calls) == 2
    assert backend.calls[0].schema is ModalidadSchema
    assert backend.calls[1].schema is ModalidadRecoverySchema
    assert stage.metrics.n_items_ok == 0
    assert stage.metrics.n_items_failed == 1


@pytest.mark.unit
def test_singleton_no_recuperable_queda_pendiente_y_cuenta_un_fallo() -> None:
    repo = _MencionesRepo([_link(10, "evento_expulsion"), _link(10, "gobierno")])
    backend = FakeBackend(
        responses=[
            {
                "clasificaciones": [
                    {
                        "link_id": 0,
                        "modalidad": "predicacion",
                        "revisar_vinculo": False,
                        "justificacion": "Construye el evento.",
                    }
                ]
            },
            {
                "clasificaciones": [
                    {
                        "link_id": 999,
                        "modalidad": "identificacion_inferencial",
                        "revisar_vinculo": False,
                        "justificacion": "ID incorrecto deliberado.",
                    }
                ]
            },
        ]
    )
    stage = ModalidadStage(
        _DiscursosRepo(),  # type: ignore[arg-type]
        repo,  # type: ignore[arg-type]
        backend=backend,
        agent_version="v62",
        context_length=4096,
    )
    _force_ambiguous(stage)

    assert stage._classify_for_codigo("D001") == 1
    assert len(repo.writes) == 1
    assert repo.writes[0]["canonical_id"] == "evento_expulsion"
    assert len(backend.calls) == 2
    assert stage.metrics.n_items_ok == 1
    assert stage.metrics.n_items_failed == 1


@pytest.mark.unit
def test_revision_upstream_es_resultado_valido_y_versionado() -> None:
    repo = _MencionesRepo([_link(20, "referente_insostenible")])
    response = ModalidadSchema.model_validate(
        {
            "clasificaciones": [
                {
                    "link_id": 0,
                    "modalidad": None,
                    "revisar_vinculo": True,
                    "justificacion": "La arista no está sostenida.",
                }
            ]
        }
    )
    backend = FakeBackend(responses=[response])
    stage = ModalidadStage(
        _DiscursosRepo(),  # type: ignore[arg-type]
        repo,  # type: ignore[arg-type]
        backend=backend,
        agent_version="v62",
        context_length=4096,
    )
    _force_ambiguous(stage)

    assert stage._classify_for_codigo("D001") == 1
    assert len(backend.calls) == 1
    assert backend.calls[0].schema is ModalidadSchema
    assert repo.writes[0]["modalidad"] is None
    assert repo.writes[0]["review_reason"] == "La arista no está sostenida."
    assert repo.writes[0]["version"] == "v62"


@pytest.mark.unit
def test_budget_subdivide_antes_de_llamar_al_backend() -> None:
    class _EchoBackend(FakeBackend):
        def generate(self, system: str, user: str, **kwargs: Any):
            ids = [int(x) for x in re.findall(r"link_id=(\d+)", user)]
            self._responses.append(
                {
                    "clasificaciones": [
                        {
                            "link_id": i,
                            "modalidad": "identificacion_inferencial",
                            "revisar_vinculo": False,
                            "justificacion": "Relación sostenida por el contexto.",
                        }
                        for i in ids
                    ]
                }
            )
            return super().generate(system, user, **kwargs)

    long = "x" * 700
    links = []
    for i in range(6):
        lk = _link(100 + i, f"ref_{i}", marca=long)
        lk["frase"] = long
        links.append(lk)
    repo = _MencionesRepo(links)
    backend = _EchoBackend()
    stage = ModalidadStage(
        _DiscursosRepo(),  # type: ignore[arg-type]
        repo,  # type: ignore[arg-type]
        backend=backend,
        agent_version="v62",
        context_length=3000,
        marcas_per_call=8,  # una configuración mayor debe respetar el cap de modalidad
    )
    _force_ambiguous(stage)

    assert stage._marcas_per_call == 6
    assert stage._classify_for_codigo("D001") == 6
    assert len(backend.calls) > 1
    assert all(call.user.count("link_id=") <= 6 for call in backend.calls)


@pytest.mark.unit
def test_schema_violation_repetida_aborta_stage() -> None:
    repo = _MencionesRepo([_link(1, "a"), _link(2, "b")])
    backend = FakeBackend(
        responses=[
            SchemaViolationError("primera"),
            SchemaViolationError("segunda"),
        ]
    )
    stage = ModalidadStage(
        _DiscursosRepo(),  # type: ignore[arg-type]
        repo,  # type: ignore[arg-type]
        backend=backend,
        agent_version="v62",
        context_length=4096,
        marcas_per_call=1,
    )
    _force_ambiguous(stage)

    with pytest.raises(RuntimeError, match="errores estructurados repetidos"):
        stage._classify_for_codigo("D001")
    assert stage.metrics.n_items_failed == 2
