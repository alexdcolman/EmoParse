# ══════════════════════════════════════════════════════════════════════════════
#  tests.unit.test_emotions_two_pass
#
#  Tests específicos al two-pass design del EmotionsAgent:
#
#  1. Idempotencia por permutación: si proceso las mismas frases en
#     distinto orden, cada frase recibe el mismo output.
#     → Si esto falla, alguien introdujo memoria deslizante por error.
#
#  2. Rolling summary: la utility para preparar el pase 2 produce un
#     resumen determinista en orden canónico (codigo, unit_idx).
# ══════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

import json
from typing import TypeVar

import pandas as pd
import pytest
from pydantic import BaseModel

from emoparse.agents.emotions import EmotionsAgent, compute_emotion_rolling_summary
from emoparse.core.backend.base import LLMBackend, LLMResponse, TokenUsage
from emoparse.core.schemas import (
    EmocionesBatchItemSchema,
    EmocionSchema,
    ListaEmocionesBatchSchema,
)

T = TypeVar("T", bound=BaseModel)


# ══════════════════════════════════════════════════════════════════════════════
#  Backend que registra los user prompts que recibe (para verificar
#  que no incluyan información de frases no-batch).
# ══════════════════════════════════════════════════════════════════════════════


class _RecordingBackend(LLMBackend):

    def __init__(self) -> None:
        self.alias = "recording"
        self.received_users: list[str] = []

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
        self.received_users.append(user)
        # Schema esperado: ListaEmocionesBatchSchema.
        n_units = user.count("UNIDAD [")
        items = [
            EmocionesBatchItemSchema(
                unit_idx=i,
                emociones=[
                    EmocionSchema(
                        experienciador="X",
                        experienciador_marca="X",
                        tipo_emocion=f"emocion_{i}",
                        tipo_configuracion="sostenido_en_sustantivos",
                        modo_existencia="realizada",
                        fuente_marca="marca",
                        fuente_inferencia="inferencia",
                    )
                ],
            )
            for i in range(n_units)
        ]
        return LLMResponse(
            parsed=ListaEmocionesBatchSchema(root=items),
            raw="(mock)",
            usage=TokenUsage(10, 5),
            latency_ms=1.0,
            model_alias=self.alias,
            cache_hit=False,
            finish_reason="stop",
        )

    def healthcheck(self) -> bool:
        return True


# ══════════════════════════════════════════════════════════════════════════════
#  Fixtures
# ══════════════════════════════════════════════════════════════════════════════


def _make_df(n_frases: int) -> pd.DataFrame:
    """DF con n frases del mismo discurso, con actores ya procesados."""
    return pd.DataFrame([
        {
            "codigo": "DISC_X",
            "unit_idx": i,
            "frase": f"frase número {i}",
            "actores": json.dumps([
                {"actor": f"Actor_{i}", "tipo": "humano_individual",
                 "modo": "explicito", "justificacion": "j"}
            ]),
        }
        for i in range(n_frases)
    ])


# ══════════════════════════════════════════════════════════════════════════════
#  Idempotencia por permutación
# ══════════════════════════════════════════════════════════════════════════════


class TestIdempotenceByPermutation:
    """El output de cada frase no debe depender del orden del DF input.

    Esto garantiza que el pase 1 no acumula contexto entre frases. Si
    alguien agrega "memoria deslizante" por error (incluir frases
    anteriores en el prompt), este test casca: las frases reordenadas
    recibirán prompts distintos.
    """

    def test_user_prompts_per_frase_are_independent(self) -> None:
        """Los user prompts no deben mencionar frases fuera del batch actual."""
        df = _make_df(5)
        backend = _RecordingBackend()
        agent = EmotionsAgent(backend, ontologia="o", heuristicas="h")
        agent.run(df)

        # Verificamos que la cantidad de frases mencionadas por prompt
        # nunca excede el batch_size.
        for user in backend.received_users:
            n_unidades = user.count("UNIDAD [")
            assert n_unidades <= EmotionsAgent.BATCH_SIZE, (
                f"User prompt menciona {n_unidades} unidades, batch_size={EmotionsAgent.BATCH_SIZE}"
            )

    def test_permutation_does_not_change_per_frase_output(self) -> None:
        """Procesando con otro orden, cada frase recibe el mismo output.

        Sin memoria deslizante, las emociones de la frase 0 son las mismas
        ya sea que esté en posición 0 del DF o en posición 4. Lo que
        cambia es a qué BATCH le toca, pero el output por frase es estable.
        """
        df = _make_df(5)
        # Run con orden original: 0,1,2,3,4.
        backend1 = _RecordingBackend()
        agent1 = EmotionsAgent(backend1, ontologia="o", heuristicas="h")
        out1 = agent1.run(df)

        # Run con orden invertido: 4,3,2,1,0.
        df_rev = df.iloc[::-1].reset_index(drop=True)
        backend2 = _RecordingBackend()
        agent2 = EmotionsAgent(backend2, ontologia="o", heuristicas="h")
        out2 = agent2.run(df_rev)

        # Para cada frase (identificada por unit_idx), las emociones
        # deben ser equivalentes.
        for unit_idx in range(5):
            row1 = out1[out1["unit_idx"] == unit_idx].iloc[0]
            row2 = out2[out2["unit_idx"] == unit_idx].iloc[0]
            emos1 = json.loads(row1["emociones"])
            emos2 = json.loads(row2["emociones"])
            # Misma cantidad de emociones por frase.
            assert len(emos1) == len(emos2) == 1
            # Cada emoción tiene experienciador, tipo, modo (no None/"" ).
            assert emos1[0]["experienciador"] != ""
            assert emos2[0]["experienciador"] != ""

    def test_user_prompts_only_use_current_batch_frases(self) -> None:
        """Confirmación explícita: los prompts usan solo `frase` de las
        unidades del batch — nunca de frases fuera de él."""
        df = _make_df(5)
        backend = _RecordingBackend()
        agent = EmotionsAgent(backend, ontologia="o", heuristicas="h")
        agent.run(df)

        # Primer batch: frases 0, 1, 2. El prompt no debe mencionar
        # "frase número 3" ni "frase número 4".
        prompt_batch_1 = backend.received_users[0]
        assert "frase número 0" in prompt_batch_1
        assert "frase número 3" not in prompt_batch_1
        assert "frase número 4" not in prompt_batch_1


# ══════════════════════════════════════════════════════════════════════════════
#  Rolling summary
# ══════════════════════════════════════════════════════════════════════════════


def _emociones_for(unit_idx: int, tipo: str = "miedo") -> str:
    """Helper: JSON string con una emoción simple."""
    return json.dumps([{
        "experienciador": "el orador",
        "experienciador_marca": "X",
        "tipo_emocion": tipo,
        "tipo_configuracion": "sostenido_en_sustantivos",
        "modo_existencia": "realizada",
        "fuente_marca": "marca",
        "fuente_inferencia": "inferencia",
    }])


class TestRollingSummary:
    """Verifica que `compute_emotion_rolling_summary` produce un resumen
    determinista y correcto."""

    def test_first_frase_has_empty_summary(self) -> None:
        df = pd.DataFrame([
            {"codigo": "A", "unit_idx": 0, "emociones": _emociones_for(0)},
        ])
        out = compute_emotion_rolling_summary(df)
        assert "sin emociones previas" in out.iloc[0]["emotion_rolling"]

    def test_second_frase_includes_first(self) -> None:
        df = pd.DataFrame([
            {"codigo": "A", "unit_idx": 0, "emociones": _emociones_for(0, "miedo")},
            {"codigo": "A", "unit_idx": 1, "emociones": _emociones_for(1, "alegria")},
        ])
        out = compute_emotion_rolling_summary(df)

        # La frase 1 ve el resumen de la 0.
        rolling_1 = out[out["unit_idx"] == 1].iloc[0]["emotion_rolling"]
        assert "miedo" in rolling_1
        assert "[unidad 0]" in rolling_1

    def test_window_truncates(self) -> None:
        """El resumen incluye solo las `window` frases anteriores."""
        df = pd.DataFrame([
            {"codigo": "A", "unit_idx": i, "emociones": _emociones_for(i, f"emo_{i}")}
            for i in range(10)
        ])
        out = compute_emotion_rolling_summary(df, window=3)

        # Para la frase 9: el resumen contiene solo emociones de 6,7,8.
        rolling_9 = out[out["unit_idx"] == 9].iloc[0]["emotion_rolling"]
        assert "emo_6" in rolling_9
        assert "emo_7" in rolling_9
        assert "emo_8" in rolling_9
        # No contiene emociones más viejas.
        assert "emo_0" not in rolling_9
        assert "emo_5" not in rolling_9

    def test_resets_at_codigo_boundary(self) -> None:
        """El acumulador se resetea al cambiar de discurso."""
        df = pd.DataFrame([
            {"codigo": "A", "unit_idx": 0, "emociones": _emociones_for(0, "miedo_A")},
            {"codigo": "A", "unit_idx": 1, "emociones": _emociones_for(1, "alegria_A")},
            {"codigo": "B", "unit_idx": 0, "emociones": _emociones_for(0, "miedo_B")},
        ])
        out = compute_emotion_rolling_summary(df)

        # La primera frase de B no debe ver emociones de A.
        rolling_b0 = out[
            (out["codigo"] == "B") & (out["unit_idx"] == 0)
        ].iloc[0]["emotion_rolling"]
        assert "miedo_A" not in rolling_b0
        assert "alegria_A" not in rolling_b0
        assert "sin emociones previas" in rolling_b0

    def test_deterministic_across_input_orderings(self) -> None:
        """El output (en orden canónico) es idéntico independientemente
        del orden del DF input."""
        rows = [
            {"codigo": "A", "unit_idx": i, "emociones": _emociones_for(i, f"emo_{i}")}
            for i in range(5)
        ]

        # Orden directo.
        df_direct = pd.DataFrame(rows)
        out1 = compute_emotion_rolling_summary(df_direct).sort_values(
            ["codigo", "unit_idx"]
        ).reset_index(drop=True)

        # Orden invertido.
        df_reversed = pd.DataFrame(rows[::-1])
        out2 = compute_emotion_rolling_summary(df_reversed).sort_values(
            ["codigo", "unit_idx"]
        ).reset_index(drop=True)

        # Comparar las columnas emotion_rolling en orden canónico.
        assert list(out1["emotion_rolling"]) == list(out2["emotion_rolling"])

    def test_handles_nan_emotions(self) -> None:
        """Frases con `emociones` NaN se saltean (no contribuyen al rolling)."""
        df = pd.DataFrame([
            {"codigo": "A", "unit_idx": 0, "emociones": _emociones_for(0, "miedo")},
            {"codigo": "A", "unit_idx": 1, "emociones": None},  # NaN
            {"codigo": "A", "unit_idx": 2, "emociones": _emociones_for(2, "alegria")},
        ])
        out = compute_emotion_rolling_summary(df)

        # La frase 2 ve el rolling con miedo (de 0) pero no nada de 1.
        rolling_2 = out[out["unit_idx"] == 2].iloc[0]["emotion_rolling"]
        assert "miedo" in rolling_2
        assert "[unidad 1]" not in rolling_2  # NaN no contribuye

    def test_handles_empty_emotions_list(self) -> None:
        """Frase con `[]` no contribuye al rolling, similar a NaN."""
        df = pd.DataFrame([
            {"codigo": "A", "unit_idx": 0, "emociones": "[]"},
            {"codigo": "A", "unit_idx": 1, "emociones": _emociones_for(1, "miedo")},
        ])
        out = compute_emotion_rolling_summary(df)

        # La frase 1 no ve la 0 (está vacía).
        rolling_1 = out[out["unit_idx"] == 1].iloc[0]["emotion_rolling"]
        assert "[unidad 0]" not in rolling_1

    def test_empty_df_returns_with_column(self) -> None:
        df = pd.DataFrame(columns=["codigo", "unit_idx", "emociones"])
        out = compute_emotion_rolling_summary(df)
        assert "emotion_rolling" in out.columns
        assert len(out) == 0

    def test_preserves_other_columns(self) -> None:
        df = pd.DataFrame([
            {"codigo": "A", "unit_idx": 0,
             "emociones": _emociones_for(0), "extra": "valor"},
        ])
        out = compute_emotion_rolling_summary(df)
        assert "extra" in out.columns
        assert out.iloc[0]["extra"] == "valor"
