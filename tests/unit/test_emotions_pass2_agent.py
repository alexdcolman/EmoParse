# ══════════════════════════════════════════════════════════════════════════════
#  tests.unit.test_emotions_pass2_agent
#
#  Tests específicos del EmotionsAgentPass2:
#    - El user prompt incluye la columna `emotion_rolling` correctamente.
#    - El system prompt difiere del pase 1 (instrucciones de uso de contexto).
#    - Mapeo del schema → columnas.
# ══════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

import json
from typing import TypeVar

import pandas as pd
from pydantic import BaseModel

from emoparse.agents.emotions_pass2 import EmotionsAgentPass2
from emoparse.core.backend.base import LLMBackend, LLMResponse, TokenUsage
from emoparse.core.schemas import (
    EmocionesBatchItemSchema,
    EmocionSchema,
    ListaEmocionesBatchSchema,
)

T = TypeVar("T", bound=BaseModel)


class _RecordingBackend(LLMBackend):
    def __init__(self) -> None:
        self.alias = "rec"
        self.calls: list[dict[str, object]] = []

    def generate(
        self,
        system: str,
        user: str,
        *,
        schema: type[T] | None = None,
        max_tokens: int | None = None,
        max_items: int | None = None,
        temperature: float | None = None,
        seed: int | None = None,
        stop: list[str] | None = None,
        reset_before: bool = False,
    ) -> LLMResponse:
        self.calls.append({"system": system, "user": user})
        n = user.count("UNIDAD [")
        items = [
            EmocionesBatchItemSchema(unit_idx=i, emociones=[
                EmocionSchema(experienciador="X", experienciador_marca="X", tipo_emocion="miedo",
                              tipo_configuracion="cualificacion_por_componentes_descriptivo_narrativos",
                              fuente_marca="la pobreza", fuente_inferencia="pobreza",
                              modo_existencia="realizada")
            ])
            for i in range(n)
        ]
        return LLMResponse(
            parsed=ListaEmocionesBatchSchema(root=items),
            raw="(rec)",
            usage=TokenUsage(10, 5),
            latency_ms=1.0,
            model_alias=self.alias,
            cache_hit=False,
            finish_reason="stop",
        )

    def healthcheck(self) -> bool:
        return True


def _make_df(n: int, with_rolling: bool = True) -> pd.DataFrame:
    rows = [
        {
            "codigo": "DISC_X",
            "unit_idx": i,
            "frase": f"frase {i}",
            "actores": json.dumps([
                {"actor": "X", "tipo": "humano_individual",
                 "modo": "explicito", "justificacion": "j"}
            ]),
        }
        for i in range(n)
    ]
    if with_rolling:
        for i, row in enumerate(rows):
            if i == 0:
                row["emotion_rolling"] = "(sin emociones previas en este discurso)"
            else:
                row["emotion_rolling"] = f"[unidad {i - 1}] X siente miedo (realizada)"
    return pd.DataFrame(rows)


# ══════════════════════════════════════════════════════════════════════════════
#  System prompt: difiere del pase 1
# ══════════════════════════════════════════════════════════════════════════════


class TestSystemPrompt:

    def test_mentions_pase_2_explicitly(self) -> None:
        backend = _RecordingBackend()
        agent = EmotionsAgentPass2(backend, ontologia="o", heuristicas="h")
        df = _make_df(1)
        agent.run(df)

        system = backend.calls[0]["system"]
        # El system del pase 2 debe instruir sobre uso de contexto.
        assert "SEGUNDA PASADA" in system or "pase 2" in system.lower()
        assert (
            "CONTEXTO GLOBAL DEL DISCURSO" in system
            or "frases anteriores" in system
        )

    def test_includes_anti_alucinacion_rules(self) -> None:
        """El prompt debe instruir explícitamente: no inventar."""
        backend = _RecordingBackend()
        agent = EmotionsAgentPass2(backend, ontologia="o", heuristicas="h")
        agent.run(_make_df(1))

        system = backend.calls[0]["system"]
        # Alguna mención a no alucinar / inventar.
        assert (
            "Cada frase se evalúa por lo que dice" in system
            or "NO heredes" in system
            or "PROHIBIDO" in system
        )


# ══════════════════════════════════════════════════════════════════════════════
#  User prompt: incluye rolling
# ══════════════════════════════════════════════════════════════════════════════


class TestUserPromptIncludesRolling:

    def test_rolling_appears_per_unit(self) -> None:
        backend = _RecordingBackend()
        agent = EmotionsAgentPass2(backend, ontologia="o", heuristicas="h")
        df = _make_df(2)
        agent.run(df)

        user = backend.calls[0]["user"]
        # CONTEXTO ANTERIOR debe aparecer una vez por unidad del batch.
        assert user.count("EMOCIONES EN FRASES PREVIAS") == 2
        # Y el rolling de la unidad 1 (que cita la 0) debe estar.
        assert "[unidad 0]" in user

    def test_empty_rolling_shown_as_no_context(self) -> None:
        backend = _RecordingBackend()
        agent = EmotionsAgentPass2(backend, ontologia="o", heuristicas="h")
        # Manualmente crear un row con rolling vacío.
        df = pd.DataFrame([{
            "codigo": "X", "unit_idx": 0, "frase": "f",
            "actores": "[]", "emotion_rolling": "",
        }])
        agent.run(df)

        user = backend.calls[0]["user"]
        assert "(sin emociones previas)" in user

    def test_missing_rolling_column_handled(self) -> None:
        """Si el DF no tiene `emotion_rolling`, el agente no debe crashear:
        usa empty + cae en el branch '(sin emociones previas)'."""
        backend = _RecordingBackend()
        agent = EmotionsAgentPass2(backend, ontologia="o", heuristicas="h")
        df = _make_df(1, with_rolling=False)  # sin la columna
        agent.run(df)

        user = backend.calls[0]["user"]
        # No crasheó; el contexto se llena con default.
        assert "(sin emociones previas)" in user


# ══════════════════════════════════════════════════════════════════════════════
#  Output mapping
# ══════════════════════════════════════════════════════════════════════════════


class TestOutputMapping:

    def test_output_column_emociones(self) -> None:
        backend = _RecordingBackend()
        agent = EmotionsAgentPass2(backend, ontologia="o", heuristicas="h")
        out = agent.run(_make_df(1))
        assert "emociones" in out.columns

    def test_emociones_serialized_as_json(self) -> None:
        backend = _RecordingBackend()
        agent = EmotionsAgentPass2(backend, ontologia="o", heuristicas="h")
        out = agent.run(_make_df(1))

        emociones_str = out.iloc[0]["emociones"]
        parsed = json.loads(emociones_str)
        assert isinstance(parsed, list)
        assert len(parsed) == 1
        assert parsed[0]["tipo_emocion"] == "miedo"
