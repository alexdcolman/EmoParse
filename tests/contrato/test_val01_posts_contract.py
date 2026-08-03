"""Contratos semánticos derivados del smoke de posts VAL-01."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pandas as pd

from emoparse.agents.characterizer import CharacterizerAgent
from emoparse.agents.emotions import EmotionsAgent
from emoparse.agents.emotions_pass2 import EmotionsAgentPass2
from emoparse.core.schemas import (
    CaracterizacionBatchItemSchema,
    EmocionesBatchItemSchema,
)

_REPLY_PATH = Path(__file__).parents[2] / "src" / "emoparse" / "pipeline" / "reply_context.py"
_REPLY_SPEC = importlib.util.spec_from_file_location("reply_context_contract", _REPLY_PATH)
assert _REPLY_SPEC is not None and _REPLY_SPEC.loader is not None
_REPLY_MODULE = importlib.util.module_from_spec(_REPLY_SPEC)
_REPLY_SPEC.loader.exec_module(_REPLY_MODULE)
reply_target = _REPLY_MODULE.reply_target


def _emotion(*, tipo: str) -> dict[str, object]:
    return {
        "exp": "@cuenta.bsky.social",
        "expm": "yo",
        "emo": tipo,
        "fuem": "la situación",
        "fue": "la situación",
        "modo": "realizada",
        "conf": 8,
    }


def test_emotions_close_output_to_effective_ontology() -> None:
    agent = object.__new__(EmotionsAgent)
    agent._emotion_alias_lookup = {
        "esperanza": "esperanza",
        "gratitud": "gratitud",
        "agradecimiento": "gratitud",
    }
    item = EmocionesBatchItemSchema(
        unit_idx=0,
        emociones=[
            _emotion(tipo="agradecimiento"),
            _emotion(tipo="carencia"),
        ],
    )

    output = agent._map_item_to_columns(item, pd.Series(dtype="object"))
    emociones = json.loads(output["emociones"])

    assert [e["tipo_emocion"] for e in emociones] == ["gratitud"]


def test_emotions_pass2_uses_the_same_ontology_closure() -> None:
    agent = object.__new__(EmotionsAgentPass2)
    agent._emotion_alias_lookup = {"hartazgo": "hartazgo"}
    item = EmocionesBatchItemSchema(
        unit_idx=0,
        emociones=[
            _emotion(tipo="hartazgo"),
            _emotion(tipo="paciencia"),
        ],
    )

    output = agent._map_item_to_columns(item, pd.Series(dtype="object"))
    emociones = json.loads(output["emociones"])

    assert [e["tipo_emocion"] for e in emociones] == ["hartazgo"]


def _characterization(tipo: str) -> dict[str, str]:
    return {
        "foria": "disforico",
        "foria_justificacion": "El hartazgo tiene valencia negativa.",
        "dominancia": "cognoscitiva",
        "dominancia_justificacion": "Se formula como evaluación política.",
        "intensidad": "alta",
        "intensidad_justificacion": "La forma 'se hartó' es intensa.",
        "duracion": "durable",
        "duracion_justificacion": "El hartazgo resulta de una acumulación.",
        "tipo_atribucion": tipo,
        "tipo_atribucion_justificacion": "El hablante usa 'siento que'.",
        "temporalidad": "contemporanea",
        "temporalidad_justificacion": "Se presenta como estado actual.",
        "aspecto": "perfectivo",
        "aspecto_justificacion": "La forma 'se hartó' presenta resultado.",
    }


def test_characterizer_cannot_autoattribute_to_third_party() -> None:
    agent = object.__new__(CharacterizerAgent)
    agent._enunciador = "@caverno.bsky.social"
    item = CaracterizacionBatchItemSchema(
        unit_idx=0,
        caracterizacion=_characterization("auto_atribucion"),
    )
    row = pd.Series(
        {
            "experienciador": "el pueblo",
            "experienciador_marca": "El pueblo",
        }
    )

    output = agent._map_item_to_columns(item, row)

    assert output["tipo_atribucion"] == "hetero_atribucion"
    assert "el pueblo" in output["tipo_atribucion_justificacion"]


def test_characterizer_preserves_real_first_person_autoattribution() -> None:
    agent = object.__new__(CharacterizerAgent)
    agent._enunciador = "Javier Milei"
    item = CaracterizacionBatchItemSchema(
        unit_idx=0,
        caracterizacion=_characterization("auto_atribucion"),
    )
    row = pd.Series(
        {
            "experienciador": "el Gobierno",
            "experienciador_marca": "nuestro",
        }
    )

    output = agent._map_item_to_columns(item, row)

    assert output["tipo_atribucion"] == "auto_atribucion"


class _PostsRepo:
    def get_post(self, post_id: str):
        if post_id == "respuesta":
            return {"en_respuesta_a": "raiz", "autor_handle": "reply.bsky.social"}
        if post_id == "raiz":
            return {"en_respuesta_a": None, "autor_handle": "caverno.bsky.social"}
        return None


def test_reply_target_comes_from_thread_relation_not_from_textual_mention() -> None:
    target = reply_target("respuesta", _PostsRepo())

    assert target == {
        "actor": "@caverno.bsky.social",
        "tipo": "destinatario_mencionado",
        "justificacion": "Cuenta autora del post al que responde directamente.",
    }
    assert "mención" not in target["justificacion"]
