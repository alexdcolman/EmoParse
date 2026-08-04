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


def _emotion(
    *,
    tipo: str,
    exp: str = "@cuenta.bsky.social",
    expm: str = "yo",
    fuem: str = "la situación",
    fue: str = "la situación",
    modo: str = "realizada",
    conf: int = 8,
) -> dict[str, object]:
    return {
        "exp": exp,
        "expm": expm,
        "emo": tipo,
        "fuem": fuem,
        "fue": fue,
        "modo": modo,
        "conf": conf,
    }


def test_emotions_keeps_open_labels_until_normalize_stage() -> None:
    agent = object.__new__(EmotionsAgent)
    item = EmocionesBatchItemSchema(
        unit_idx=0,
        emociones=[
            _emotion(tipo="agradecimiento"),
            _emotion(tipo="carencia"),
        ],
    )

    output = agent._map_item_to_columns(item, pd.Series(dtype="object"))
    emociones = json.loads(output["emociones"])

    assert [e["tipo_emocion"] for e in emociones] == [
        "agradecimiento",
        "carencia",
    ]


def test_emotions_pass2_keeps_open_labels_until_normalize_stage() -> None:
    agent = object.__new__(EmotionsAgentPass2)
    item = EmocionesBatchItemSchema(
        unit_idx=0,
        emociones=[
            _emotion(tipo="hartazgo"),
            _emotion(tipo="paciencia"),
        ],
    )

    output = agent._map_item_to_columns(item, pd.Series(dtype="object"))
    emociones = json.loads(output["emociones"])

    assert [e["tipo_emocion"] for e in emociones] == [
        "hartazgo",
        "paciencia",
    ]


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


def _mapped_emotions(
    *,
    text: str,
    enunciador: str,
    emociones: list[dict[str, object]],
) -> list[dict[str, object]]:
    agent = object.__new__(EmotionsAgent)
    agent._enunciador = enunciador
    item = EmocionesBatchItemSchema(unit_idx=0, emociones=emociones)
    output = agent._map_item_to_columns(item, pd.Series({"frase": text}))
    return json.loads(output["emociones"])


def test_agradezco_is_gratitude_not_hope_of_the_post_author() -> None:
    mapped = _mapped_emotions(
        text=("Agradezco estos mensajes de esperanza, porque de momento, carezco."),
        enunciador="@kualka.bsky.social",
        emociones=[
            _emotion(
                tipo="esperanza",
                exp="@kualka.bsky.social",
                expm="Agradezco",
                conf=3,
            )
        ],
    )

    assert [(e["tipo_emocion"], e["experienciador"]) for e in mapped] == [
        ("gratitud", "@kualka.bsky.social")
    ]


def test_hope_contained_in_messages_requires_another_experiencer() -> None:
    mapped = _mapped_emotions(
        text=("Agradezco estos mensajes de esperanza, porque de momento, carezco."),
        enunciador="@kualka.bsky.social",
        emociones=[
            _emotion(
                tipo="gratitud",
                exp="@kualka.bsky.social",
                expm="Agradezco",
                conf=3,
            ),
            _emotion(
                tipo="esperanza",
                exp="quienes enviaron los mensajes",
                expm="mensajes de esperanza",
                conf=1,
            ),
        ],
    )

    assert [(e["tipo_emocion"], e["experienciador"]) for e in mapped] == [
        ("gratitud", "@kualka.bsky.social"),
        ("esperanza", "quienes enviaron los mensajes"),
    ]


def test_siento_que_does_not_create_an_emotion_from_siento() -> None:
    mapped = _mapped_emotions(
        text=("Siento que hay un punto de quiebre. El pueblo se hartó. Espero no equivocarme."),
        enunciador="@caverno.bsky.social",
        emociones=[
            _emotion(
                tipo="ansiedad",
                exp="@caverno.bsky.social",
                expm="Siento",
                conf=3,
            ),
            _emotion(
                tipo="hartazgo",
                exp="El pueblo",
                expm="El pueblo",
                conf=3,
            ),
            _emotion(
                tipo="esperanza",
                exp="@caverno.bsky.social",
                expm="Espero",
                conf=4,
            ),
        ],
    )

    assert [e["tipo_emocion"] for e in mapped] == ["hartazgo", "esperanza"]
    assert mapped[0]["experienciador"] == "El pueblo"
    assert mapped[0]["experienciador_marca"] == "El pueblo"
    assert mapped[1]["experienciador"] == "@caverno.bsky.social"
    assert mapped[1]["experienciador_marca"] == "Espero"


def test_ojala_resolves_author_and_collapses_spurious_ambiguity() -> None:
    mapped = _mapped_emotions(
        text="Ojalá. Creo que hay una acumulación importante de hartazgo.",
        enunciador="@cali2027.bsky.social",
        emociones=[
            _emotion(tipo="ansiedad", exp="el hablante", expm="Ojalá", conf=1),
            _emotion(tipo="esperanza", exp="el hablante", expm="Ojalá", conf=1),
            _emotion(tipo="deseo", exp="el hablante", expm="Ojalá", conf=1),
        ],
    )

    assert len(mapped) == 1
    assert mapped[0]["tipo_emocion"] == "esperanza"
    assert mapped[0]["experienciador"] == "@cali2027.bsky.social"
    assert mapped[0]["tipo_configuracion"] == "cualificacion_por_indicadores_cognitivos"


def test_cansadisimo_uses_explicit_adjectival_state_configuration() -> None:
    mapped = _mapped_emotions(
        text="Estoy cansadísimo de los potenciales.",
        enunciador="@neonknightoa.bsky.social",
        emociones=[
            _emotion(
                tipo="hartazgo",
                exp="@neonknightoa.bsky.social",
                expm="Estoy",
                conf=5,
            )
        ],
    )

    assert mapped[0]["tipo_configuracion"] == "sostenido_en_adjetivos"


def test_characterizer_treats_ojala_as_self_attribution_of_author() -> None:
    agent = object.__new__(CharacterizerAgent)
    agent._enunciador = "@cali2027.bsky.social"
    item = CaracterizacionBatchItemSchema(
        unit_idx=0,
        caracterizacion=_characterization("sin_atribucion"),
    )
    row = pd.Series(
        {
            "experienciador": "@cali2027.bsky.social",
            "experienciador_marca": "Ojalá",
        }
    )

    output = agent._map_item_to_columns(item, row)

    assert output["tipo_atribucion"] == "auto_atribucion"
    assert "Ojalá" in output["tipo_atribucion_justificacion"]


def test_carecer_de_esperanza_does_not_create_tristeza() -> None:
    mapped = _mapped_emotions(
        text="Agradezco estos mensajes de esperanza, porque de momento, carezco.",
        enunciador="@kualka.bsky.social",
        emociones=[
            _emotion(
                tipo="gratitud",
                exp="@kualka.bsky.social",
                expm="Agradezco",
                conf=3,
            ),
            _emotion(
                tipo="tristeza",
                exp="@kualka.bsky.social",
                expm="carezco",
                fuem="esperanza",
                fue="esperanza",
                conf=6,
            ),
        ],
    )

    assert [e["tipo_emocion"] for e in mapped] == ["gratitud"]


def test_espero_collapses_interest_and_uses_the_literal_first_person_verb() -> None:
    mapped = _mapped_emotions(
        text="Espero tengas razon !!!",
        enunciador="@ruben24.bsky.social",
        emociones=[
            _emotion(
                tipo="esperanza",
                exp="@ruben24.bsky.social",
                expm="tú",
                modo="potencial",
                conf=8,
            ),
            _emotion(
                tipo="interés",
                exp="@ruben24.bsky.social",
                expm="tú",
                conf=8,
            ),
        ],
    )

    assert len(mapped) == 1
    assert mapped[0]["tipo_emocion"] == "esperanza"
    assert mapped[0]["experienciador"] == "@ruben24.bsky.social"
    assert mapped[0]["experienciador_marca"] == "Espero"
    assert mapped[0]["modo_existencia"] == "realizada"
    assert mapped[0]["tipo_configuracion"] == "ordenado_alrededor_de_verbos_psicologicos"


def test_conditional_belief_normalizes_detected_distrust() -> None:
    mapped = _mapped_emotions(
        text=("Cuando vea acciones, lo voy a creer. Estoy cansadísimo de los potenciales."),
        enunciador="@neonknightoa.bsky.social",
        emociones=[
            _emotion(
                tipo="desconfianza",
                exp="@neonknightoa.bsky.social",
                expm="voy a creer",
                fuem="acciones",
                fue="acciones",
                conf=6,
            ),
            _emotion(
                tipo="hartazgo",
                exp="@neonknightoa.bsky.social",
                expm="Estoy",
                fuem="los potenciales",
                fue="los potenciales",
                conf=5,
            ),
        ],
    )

    assert [e["tipo_emocion"] for e in mapped] == ["desconfianza", "hartazgo"]
    assert mapped[0]["experienciador_marca"] == "lo voy a creer"
    assert mapped[0]["fuente_marca"] == "acciones"
    assert mapped[0]["modo_existencia"] == "realizada"


def test_siento_que_post_drops_surprise_and_preserves_independent_emotions() -> None:
    mapped = _mapped_emotions(
        text=(
            "Siento que hay un punto de quiebre con éstos soretes ultraderechistas. "
            "El pueblo se hartó. Espero no equivocarme"
        ),
        enunciador="@caverno.bsky.social",
        emociones=[
            _emotion(
                tipo="sorpresa",
                exp="@caverno.bsky.social",
                expm="Siento que hay un punto de quiebre",
                fuem="punto de quiebre",
                fue="punto de quiebre",
                conf=6,
            ),
            _emotion(
                tipo="hartazgo",
                exp="El pueblo",
                expm="El pueblo",
                conf=3,
            ),
            _emotion(
                tipo="esperanza",
                exp="@caverno.bsky.social",
                expm="Espero",
                conf=4,
            ),
        ],
    )

    assert [e["tipo_emocion"] for e in mapped] == ["hartazgo", "esperanza"]
    assert mapped[0]["experienciador"] == "El pueblo"
    assert mapped[0]["tipo_configuracion"] == "ordenado_alrededor_de_verbos_psicologicos"
    assert mapped[1]["experienciador"] == "@caverno.bsky.social"


def test_characterizer_treats_explicit_third_party_hartarse_as_heteroattribution() -> None:
    agent = object.__new__(CharacterizerAgent)
    agent._enunciador = "@caverno.bsky.social"
    item = CaracterizacionBatchItemSchema(
        unit_idx=0,
        caracterizacion=_characterization("sin_atribucion"),
    )
    row = pd.Series(
        {
            "frase": "Siento que hay un punto de quiebre. El pueblo se hartó.",
            "experienciador": "El pueblo",
            "experienciador_marca": "El pueblo",
            "tipo_configuracion": "ordenado_alrededor_de_verbos_psicologicos",
        }
    )

    output = agent._map_item_to_columns(item, row)

    assert output["tipo_atribucion"] == "hetero_atribucion"
    assert "El pueblo" in output["tipo_atribucion_justificacion"]


def test_context_only_actor_mark_is_sanitized_and_spurious_author_readings_are_dropped() -> None:
    mapped = _mapped_emotions(
        text=(
            "Ojalá. Creo que hay una acumulación importante de hartazgo, ya nadie "
            "habla de Adorni, ni de la reforma esclavista o el 3%, pero todo eso, "
            "y el hambre, suma, y los intentos por disimular el cipayismo cuando "
            "el país salió con la bandera de la soberanía pueden ser la gota que "
            "colme la paciencia."
        ),
        enunciador="@cali2027.bsky.social",
        emociones=[
            _emotion(
                tipo="esperanza",
                exp="@cali2027.bsky.social",
                expm="Ojalá",
                fuem="no identificado",
                fue="no identificado",
                conf=4,
            ),
            _emotion(
                tipo="hartazgo",
                exp="el pueblo",
                expm="no identificado",
                fuem="no identificado",
                fue="la acumulación importante de hartazgo",
                conf=1,
            ),
            _emotion(
                tipo="ira",
                exp="@cali2027.bsky.social",
                expm="no identificado",
                fuem="los intentos por disimular el cipayismo",
                fue="los intentos por disimular el cipayismo",
                conf=6,
            ),
            _emotion(
                tipo="esperanza",
                exp="@cali2027.bsky.social",
                expm="no identificado",
                fuem="la gota que colme la paciencia",
                fue="la gota que colme la paciencia",
                conf=5,
            ),
        ],
    )

    assert [e["tipo_emocion"] for e in mapped] == ["esperanza", "hartazgo"]
    assert mapped[0]["experienciador_marca"] == "Ojalá"
    assert mapped[0]["fuente_marca"] == "no identificado"
    assert mapped[1]["experienciador"] == "el pueblo"
    assert mapped[1]["experienciador_marca"] == "no identificado"


def test_postprocessing_does_not_complete_emotions_omitted_by_the_model() -> None:
    mapped = _mapped_emotions(
        text=(
            "Agradezco el mensaje. Espero que mejore. "
            "Estoy cansado y cuando vea pruebas lo voy a creer."
        ),
        enunciador="@cuenta.bsky.social",
        emociones=[],
    )

    assert mapped == []


def test_cognitive_matrix_does_not_turn_embedded_emotions_into_author_emotions() -> None:
    mapped = _mapped_emotions(
        text=(
            "Ojalá. Creo que hay una acumulación importante de hartazgo "
            "y que la situación puede empeorar."
        ),
        enunciador="@cuenta.bsky.social",
        emociones=[
            _emotion(
                tipo="esperanza",
                exp="@cuenta.bsky.social",
                expm="Ojalá",
                conf=4,
            ),
            _emotion(
                tipo="hartazgo",
                exp="@cuenta.bsky.social",
                expm="Creo que hay una acumulación importante de hartazgo",
                conf=3,
            ),
            _emotion(
                tipo="ira",
                exp="@cuenta.bsky.social",
                expm="Creo que hay una acumulación importante de hartazgo",
                conf=6,
            ),
        ],
    )

    assert [e["tipo_emocion"] for e in mapped] == ["esperanza", "hartazgo"]
    assert mapped[1]["experienciador"] == "no identificado"
    assert mapped[1]["experienciador_marca"] == "no identificado"
    assert mapped[1]["tipo_configuracion"] == "sostenido_en_sustantivos"


def test_explicit_third_party_emotion_survives_a_cognitive_matrix() -> None:
    mapped = _mapped_emotions(
        text="Creo que la ministra está triste por la derrota.",
        enunciador="@cuenta.bsky.social",
        emociones=[
            _emotion(
                tipo="tristeza",
                exp="la ministra",
                expm="la ministra",
                fuem="la derrota",
                fue="la derrota",
                conf=2,
            )
        ],
    )

    assert len(mapped) == 1
    assert mapped[0]["experienciador"] == "la ministra"
    assert mapped[0]["experienciador_marca"] == "la ministra"


def test_characterizer_marks_inferred_conditional_distrust_as_unattributed() -> None:
    agent = object.__new__(CharacterizerAgent)
    agent._enunciador = "@neonknightoa.bsky.social"
    item = CaracterizacionBatchItemSchema(
        unit_idx=0,
        caracterizacion=_characterization("auto_atribucion"),
    )
    row = pd.Series(
        {
            "frase": "Cuando vea acciones, lo voy a creer.",
            "experienciador": "@neonknightoa.bsky.social",
            "experienciador_marca": "lo voy a creer",
            "tipo_configuracion": "cualificacion_por_indicadores_cognitivos",
        }
    )

    output = agent._map_item_to_columns(item, row)

    assert output["tipo_atribucion"] == "sin_atribucion"


def test_characterizer_marks_explicit_third_party_emotion_as_heteroattribution() -> None:
    agent = object.__new__(CharacterizerAgent)
    agent._enunciador = "@caverno.bsky.social"
    item = CaracterizacionBatchItemSchema(
        unit_idx=0,
        caracterizacion=_characterization("auto_atribucion"),
    )
    row = pd.Series(
        {
            "frase": "El pueblo se hartó.",
            "experienciador": "El pueblo",
            "experienciador_marca": "El pueblo",
            "tipo_configuracion": "ordenado_alrededor_de_verbos_psicologicos",
        }
    )

    output = agent._map_item_to_columns(item, row)

    assert output["tipo_atribucion"] == "hetero_atribucion"


def test_characterizer_context_only_experiencer_has_no_explicit_attribution() -> None:
    agent = object.__new__(CharacterizerAgent)
    agent._enunciador = "@cali2027.bsky.social"
    item = CaracterizacionBatchItemSchema(
        unit_idx=0,
        caracterizacion=_characterization("hetero_atribucion"),
    )
    row = pd.Series(
        {
            "frase": "Creo que hay una acumulación importante de hartazgo.",
            "experienciador": "el pueblo",
            "experienciador_marca": "no identificado",
            "tipo_configuracion": "sostenido_en_sustantivos",
        }
    )

    output = agent._map_item_to_columns(item, row)

    assert output["tipo_atribucion"] == "sin_atribucion"
