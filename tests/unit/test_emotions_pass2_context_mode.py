# ══════════════════════════════════════════════════════════════════════════════
#  tests.unit.test_emotions_pass2_context_mode
#
#  Verifica que EmotionsAgentPass2 acepta context_mode y que
#  compute_emotion_full_summary produce el contexto correcto.
# ══════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

import json
from typing import TypeVar
from unittest.mock import MagicMock

import pandas as pd
import pytest
from pydantic import BaseModel, ValidationError

from emoparse.agents.emotions import (
    compute_emotion_full_summary,
    compute_emotion_rolling_summary,
)
from emoparse.agents.emotions_pass2 import EmotionsAgentPass2
from emoparse.config.models import PipelineConfig
from emoparse.core.backend.base import LLMBackend, LLMResponse, TokenUsage
from emoparse.core.schemas import (
    EmocionesBatchItemSchema,
    ListaEmocionesBatchSchema,
)

T = TypeVar("T", bound=BaseModel)


# ══════════════════════════════════════════════════════════════════════════════
#  Fake backend (igual que test_emotions_agent.py para mantener consistencia)
# ══════════════════════════════════════════════════════════════════════════════


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


def _resp(items: list[EmocionesBatchItemSchema]) -> ListaEmocionesBatchSchema:
    return ListaEmocionesBatchSchema(root=items)


def _emo_json(*types: str) -> str:
    """Genera JSON de emociones de test con tipos dados."""
    return json.dumps([
        {
            "experienciador": "el pueblo",
            "tipo_emocion": t,
            "tipo_configuracion": "sostenido_en_sustantivos",
            "modo_existencia": "realizada",
            "fuente_marca": "la riqueza",
            "fuente_inferencia": "riqueza",
            "justificacion": "test",
        }
        for t in types
    ], ensure_ascii=False)


# ══════════════════════════════════════════════════════════════════════════════
#  Tests: compute_emotion_full_summary
# ══════════════════════════════════════════════════════════════════════════════


class TestComputeEmotionFullSummary:

    def test_empty_df_returns_empty(self) -> None:
        df = pd.DataFrame(columns=["codigo", "unit_idx", "emociones"])
        out = compute_emotion_full_summary(df)
        assert out.empty
        assert "emotion_rolling" in out.columns

    def test_first_frase_has_no_previous(self) -> None:
        df = pd.DataFrame([
            {"codigo": "D1", "unit_idx": 0, "emociones": _emo_json("orgullo")},
        ])
        out = compute_emotion_full_summary(df)
        assert out.iloc[0]["emotion_rolling"] == "(sin emociones previas en este discurso)"

    def test_second_frase_sees_first(self) -> None:
        df = pd.DataFrame([
            {"codigo": "D1", "unit_idx": 0, "emociones": _emo_json("orgullo")},
            {"codigo": "D1", "unit_idx": 1, "emociones": _emo_json("alegría")},
        ])
        out = compute_emotion_full_summary(df)
        # frase 0: sin previas
        assert "sin emociones previas" in out.iloc[0]["emotion_rolling"]
        # frase 1: ve la frase 0
        rolling_1 = out.iloc[1]["emotion_rolling"]
        assert "unidad 0" in rolling_1
        assert "orgullo" in rolling_1

    def test_full_accumulates_all_previous(self) -> None:
        """A diferencia del rolling con window chica, el full no descarta nada."""
        frases = [
            {"codigo": "D1", "unit_idx": i, "emociones": _emo_json(f"emo{i}")}
            for i in range(6)
        ]
        df = pd.DataFrame(frases)
        out = compute_emotion_full_summary(df)

        # La última frase (idx=5) debe ver todas las anteriores (0..4).
        rolling_last = out.iloc[5]["emotion_rolling"]
        for i in range(5):
            assert f"unidad {i}" in rolling_last, (
                f"Esperaba 'unidad {i}' en el rolling de la última frase"
            )

    def test_resets_between_discursos(self) -> None:
        df = pd.DataFrame([
            {"codigo": "D1", "unit_idx": 0, "emociones": _emo_json("orgullo")},
            {"codigo": "D1", "unit_idx": 1, "emociones": _emo_json("alegría")},
            # Nuevo discurso: no debe ver emociones de D1.
            {"codigo": "D2", "unit_idx": 0, "emociones": _emo_json("tristeza")},
            {"codigo": "D2", "unit_idx": 1, "emociones": _emo_json("miedo")},
        ])
        out = compute_emotion_full_summary(df)
        d2_frase0 = out[out["codigo"] == "D2"].iloc[0]["emotion_rolling"]
        assert "sin emociones previas" in d2_frase0
        assert "orgullo" not in d2_frase0

    def test_order_independent(self) -> None:
        """Permutar el input no cambia el output (post-sort por codigo,unit_idx)."""
        frases = [
            {"codigo": "D1", "unit_idx": i, "emociones": _emo_json(f"emo{i}")}
            for i in range(4)
        ]
        df_ordered = pd.DataFrame(frases)
        df_shuffled = df_ordered.sample(frac=1, random_state=7).reset_index(drop=True)

        out_ordered = compute_emotion_full_summary(df_ordered)
        out_shuffled = compute_emotion_full_summary(df_shuffled)

        # Comparar en orden canónico.
        out_ordered_sorted = out_ordered.sort_values(["codigo", "unit_idx"])
        out_shuffled_sorted = out_shuffled.sort_values(["codigo", "unit_idx"])

        assert list(out_ordered_sorted["emotion_rolling"]) == list(
            out_shuffled_sorted["emotion_rolling"]
        )

    def test_frase_with_null_emociones_skipped_in_history(self) -> None:
        """Frases con emociones NaN no contribuyen al rolling del resto."""
        df = pd.DataFrame([
            {"codigo": "D1", "unit_idx": 0, "emociones": None},  # sin emociones
            {"codigo": "D1", "unit_idx": 1, "emociones": _emo_json("orgullo")},
            {"codigo": "D1", "unit_idx": 2, "emociones": _emo_json("alegría")},
        ])
        out = compute_emotion_full_summary(df)
        # frase 2 ve solo frase 1 (frase 0 no aportó).
        rolling_2 = out.iloc[2]["emotion_rolling"]
        assert "unidad 1" in rolling_2
        assert "unidad 0" not in rolling_2


# ══════════════════════════════════════════════════════════════════════════════
#  Tests: full vs rolling difieren cuando hay más de window frases
# ══════════════════════════════════════════════════════════════════════════════


class TestFullVsRolling:

    def test_full_context_larger_than_rolling_window(self) -> None:
        """Con window=2 y 5 frases, rolling descarta las más viejas; full no."""
        frases = [
            {"codigo": "D1", "unit_idx": i, "emociones": _emo_json(f"emo{i}")}
            for i in range(5)
        ]
        df = pd.DataFrame(frases)

        out_rolling = compute_emotion_rolling_summary(df, window=2)
        out_full = compute_emotion_full_summary(df)

        # Para la última frase (idx=4):
        rolling_last = out_rolling.iloc[4]["emotion_rolling"]
        full_last = out_full.iloc[4]["emotion_rolling"]

        # Rolling con window=2 solo ve idx 2 y 3.
        assert "unidad 0" not in rolling_last
        assert "unidad 1" not in rolling_last

        # Full ve todas.
        assert "unidad 0" in full_last
        assert "unidad 1" in full_last

    def test_both_agree_on_first_frase(self) -> None:
        """Ambos modos coinciden en la primera frase (sin previas)."""
        df = pd.DataFrame([
            {"codigo": "D1", "unit_idx": 0, "emociones": _emo_json("orgullo")},
        ])
        out_rolling = compute_emotion_rolling_summary(df, window=5)
        out_full = compute_emotion_full_summary(df)

        assert out_rolling.iloc[0]["emotion_rolling"] == out_full.iloc[0]["emotion_rolling"]


# ══════════════════════════════════════════════════════════════════════════════
#  Tests: EmotionsAgentPass2 acepta context_mode
# ══════════════════════════════════════════════════════════════════════════════


class TestEmotionsAgentPass2ContextMode:

    def test_default_is_rolling(self) -> None:
        backend = _FakeBackend([])
        agent = EmotionsAgentPass2(backend, ontologia="o", heuristicas="h")
        assert agent._context_mode == "rolling"

    def test_accepts_full_mode(self) -> None:
        backend = _FakeBackend([])
        agent = EmotionsAgentPass2(
            backend, ontologia="o", heuristicas="h", context_mode="full"
        )
        assert agent._context_mode == "full"

    def test_rolling_mode_runs_without_error(self) -> None:
        backend = _FakeBackend([
            _resp([EmocionesBatchItemSchema(unit_idx=0, emociones=[])]),
        ])
        agent = EmotionsAgentPass2(
            backend, ontologia="o", heuristicas="h", context_mode="rolling"
        )
        df = pd.DataFrame([{
            "codigo": "D1", "unit_idx": 0,
            "frase": "Frase de prueba.",
            "actores": "[]",
            "emotion_rolling": "(sin emociones previas en este discurso)",
        }])
        out = agent.run(df)
        assert "emociones" in out.columns

    def test_full_mode_runs_without_error(self) -> None:
        backend = _FakeBackend([
            _resp([EmocionesBatchItemSchema(unit_idx=0, emociones=[])]),
        ])
        agent = EmotionsAgentPass2(
            backend, ontologia="o", heuristicas="h", context_mode="full"
        )
        df = pd.DataFrame([{
            "codigo": "D1", "unit_idx": 0,
            "frase": "Frase de prueba.",
            "actores": "[]",
            "emotion_rolling": "(sin emociones previas en este discurso)",
        }])
        out = agent.run(df)
        assert "emociones" in out.columns

    def test_context_included_in_user_prompt(self) -> None:
        """El emotion_rolling se incluye en el user prompt del agente."""
        backend = _FakeBackend([
            _resp([EmocionesBatchItemSchema(unit_idx=0, emociones=[])]),
        ])
        agent = EmotionsAgentPass2(
            backend, ontologia="o", heuristicas="h", context_mode="full"
        )
        df = pd.DataFrame([{
            "codigo": "D1", "unit_idx": 0,
            "frase": "Frase de prueba.",
            "actores": "[]",
            "emotion_rolling": "CONTEXTO_FULL_MARK",
        }])
        agent.run(df)
        user = backend.calls[0]["user"]
        assert "CONTEXTO_FULL_MARK" in user


# ══════════════════════════════════════════════════════════════════════════════
#  Tests: EmotionsPass2Stage propaga context_mode
# ══════════════════════════════════════════════════════════════════════════════


class TestEmotionsPass2StageContextMode:

    def _make_stage(self, context_mode: str = "rolling"):
        from emoparse.pipeline.stages import EmotionsPass2Stage

        backend = MagicMock()
        d_repo = MagicMock()
        f_repo = MagicMock()
        # Simular nada pendiente para que run_pending() retorne inmediatamente.
        f_repo.list_pending.return_value = []

        return EmotionsPass2Stage(
            backend=backend,
            discursos_repo=d_repo,
            frases_repo=f_repo,
            ontologia="ontologia_test",
            heuristicas="heuristicas_test",
            context_mode=context_mode,
        )

    def test_default_context_mode_is_rolling(self) -> None:
        stage = self._make_stage()
        assert stage._context_mode == "rolling"

    def test_full_context_mode_stored(self) -> None:
        stage = self._make_stage(context_mode="full")
        assert stage._context_mode == "full"

    def test_run_pending_noop_when_nothing_pending(self) -> None:
        stage = self._make_stage(context_mode="full")
        result = stage.run_pending()
        assert result == 0


# ══════════════════════════════════════════════════════════════════════════════
#  Tests: PipelineConfig.pass2_context_mode
# ══════════════════════════════════════════════════════════════════════════════


class TestPipelineConfigPass2ContextMode:

    def test_default_is_rolling(self) -> None:
        cfg = PipelineConfig()
        assert cfg.pass2_context_mode == "rolling"

    def test_accepts_full(self) -> None:
        cfg = PipelineConfig(pass2_context_mode="full")
        assert cfg.pass2_context_mode == "full"

    def test_rejects_invalid_value(self) -> None:
        with pytest.raises(ValidationError):
            PipelineConfig(pass2_context_mode="sliding")  # type: ignore[arg-type]

    def test_serializes_to_yaml_friendly_value(self) -> None:
        cfg = PipelineConfig(pass2_context_mode="full")
        d = cfg.model_dump()
        assert d["pass2_context_mode"] == "full"
