from __future__ import annotations

from typing import Any

import pytest

from emoparse.pipeline.modalidad_nlp import ModalidadNLP
from emoparse.pipeline.stages import ModalidadStage


class _Morph:
    def __init__(self, values: dict[str, list[str]] | None = None) -> None:
        self._values = values or {}

    def get(self, key: str) -> list[str]:
        return self._values.get(key, [])


class _Token:
    def __init__(
        self,
        pos: str,
        *,
        dep: str = "",
        verb_form: str | None = None,
        person: str | None = None,
        number: str | None = None,
    ) -> None:
        values: dict[str, list[str]] = {}
        if verb_form:
            values["VerbForm"] = [verb_form]
        if person:
            values["Person"] = [person]
        if number:
            values["Number"] = [number]
        self.pos_ = pos
        self.dep_ = dep
        self.morph = _Morph(values)
        self.is_space = False
        self.is_punct = False


class _Doc(list[_Token]):
    ents: tuple[Any, ...] = ()


def _classifier_for(doc: _Doc) -> ModalidadNLP:
    classifier = ModalidadNLP()
    classifier._loaded = True
    classifier._ok = True
    classifier._nlp = lambda _text: doc
    return classifier


@pytest.mark.unit
def test_flexion_personal_con_vinculo_gramatical_es_referencia_gramatical() -> None:
    classifier = _classifier_for(_Doc([_Token("VERB", dep="ROOT", verb_form="Fin", person="1")]))

    guess = classifier.classify(
        "Avanzamos",
        canonical_id="javier_milei",
        link_origin="deixis_llm",
    )

    assert guess.modalidad == "referencia_gramatical"
    assert guess.confident is True


@pytest.mark.unit
def test_flexion_personal_con_linking_llm_no_se_cierra_automaticamente() -> None:
    classifier = _classifier_for(_Doc([_Token("VERB", dep="ROOT", verb_form="Fin", person="1")]))

    guess = classifier.classify(
        "Avanzamos",
        canonical_id="gobierno",
        link_origin="llm",
    )

    assert guess.modalidad == "referencia_gramatical"
    assert guess.confident is False


@pytest.mark.unit
def test_nucleo_nominal_que_coincide_con_target_es_designacion_segura() -> None:
    classifier = _classifier_for(
        _Doc(
            [
                _Token("DET", dep="det"),
                _Token("NOUN", dep="ROOT", number="Plur"),
            ]
        )
    )

    guess = classifier.classify(
        "nuestros productores",
        canonical_id="productores",
        link_origin="llm",
    )

    assert guess.modalidad == "designacion"
    assert guess.confident is True


@pytest.mark.unit
def test_mismo_sintagma_hacia_otro_target_queda_ambiguo() -> None:
    classifier = _classifier_for(
        _Doc(
            [
                _Token("DET", dep="det"),
                _Token("NOUN", dep="ROOT", number="Plur"),
            ]
        )
    )

    guess = classifier.classify(
        "nuestros productores",
        canonical_id="javier_milei",
        link_origin="llm",
    )

    assert guess.confident is False


@pytest.mark.unit
def test_predicado_verbal_no_asigna_predicacion_por_heuristica() -> None:
    classifier = _classifier_for(
        _Doc(
            [
                _Token("VERB", dep="ROOT", verb_form="Fin", person="3"),
                _Token("DET", dep="det"),
                _Token("NOUN", dep="obj", number="Sing"),
            ]
        )
    )

    guess = classifier.classify(
        "tiró a la calle",
        canonical_id="gobierno",
        link_origin="llm",
    )

    assert guess.modalidad is None
    assert guess.confident is False


class _DiscursosRepo:
    def list_codigos(self) -> list[str]:
        return ["D001"]

    def get_payload(self, codigo: str, stage: str) -> dict[str, Any] | None:
        return None

    def get_input(self, codigo: str) -> dict[str, Any]:
        return {"contenido": "Avanzamos."}


class _MencionesRepo:
    def __init__(self) -> None:
        self.writes: list[dict[str, Any]] = []

    def list_links_for_modalidad(self, codigo: str) -> list[dict[str, Any]]:
        return [
            {
                "mencion_id": 83,
                "canonical_id": "gobierno",
                "marca": "Avanzamos",
                "frase": "Avanzamos.",
                "origen_vinculo": "llm",
                "deixis_tipo": None,
                "funciones": "actor",
                "llm_inferencia": "gobierno",
            }
        ]

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


@pytest.mark.unit
def test_nlp_only_no_persiste_guess_ambiguo() -> None:
    menciones = _MencionesRepo()
    stage = ModalidadStage(
        _DiscursosRepo(),  # type: ignore[arg-type]
        menciones,  # type: ignore[arg-type]
        backend=None,
        use_llm=False,
        agent_version="v62",
    )
    stage._nlp = _classifier_for(_Doc([_Token("VERB", dep="ROOT", verb_form="Fin", person="1")]))

    processed = stage._classify_for_codigo("D001")

    assert processed == 0
    assert menciones.writes == []
