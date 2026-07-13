# ══════════════════════════════════════════════════════════════════════════════
#  Tests de emoparse.pipeline.thread_builder
# ══════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

import json

import pandas as pd
import pytest

from emoparse.pipeline.thread_builder import build_threads

pytestmark = pytest.mark.unit


def _df(rows: list[dict]) -> pd.DataFrame:
    base = {
        "plataforma": "bluesky", "texto": "x", "fecha": None,
        "conversacion_id": None, "en_respuesta_a": None,
    }
    return pd.DataFrame([{**base, **r} for r in rows])


class TestBuildThreads:
    def test_cadena_lineal(self):
        df, hilos = build_threads(_df([
            {"post_id": "a", "autor_handle": "u1", "fecha": "2026-01-01"},
            {"post_id": "b", "autor_handle": "u2", "en_respuesta_a": "a",
             "fecha": "2026-01-02"},
            {"post_id": "c", "autor_handle": "u1", "en_respuesta_a": "b",
             "fecha": "2026-01-03"},
        ]))
        assert df["conversacion_id"].tolist() == ["a", "a", "a"]
        assert df["profundidad"].tolist() == [0, 1, 2]
        assert df["huerfano"].tolist() == [0, 0, 0]

        (hilo,) = hilos.to_dict(orient="records")
        assert hilo["conversacion_id"] == "a"
        assert hilo["post_raiz"] == "a"
        assert hilo["n_posts"] == 3
        assert hilo["profundidad_max"] == 2
        assert json.loads(hilo["participantes"]) == ["u1", "u2"]
        assert hilo["fecha_inicio"] == "2026-01-01"
        assert hilo["fecha_fin"] == "2026-01-03"

    def test_ramificacion(self):
        df, hilos = build_threads(_df([
            {"post_id": "a", "autor_handle": "u1"},
            {"post_id": "b", "autor_handle": "u2", "en_respuesta_a": "a"},
            {"post_id": "c", "autor_handle": "u3", "en_respuesta_a": "a"},
        ]))
        assert set(df["conversacion_id"]) == {"a"}
        assert sorted(df["profundidad"].tolist()) == [0, 1, 1]

    def test_huerfano(self):
        df, hilos = build_threads(_df([
            {"post_id": "x", "autor_handle": "u1", "en_respuesta_a": "no-capturado"},
        ]))
        row = df.iloc[0]
        assert row["huerfano"] == 1
        assert row["conversacion_id"] == "no-capturado"
        assert pd.isna(row["profundidad"])

    def test_conversacion_de_fuente_tiene_prioridad(self):
        df, _ = build_threads(_df([
            {"post_id": "x", "autor_handle": "u1", "en_respuesta_a": "padre-ausente",
             "conversacion_id": "raiz-verdadera"},
        ]))
        assert df.iloc[0]["conversacion_id"] == "raiz-verdadera"
        assert df.iloc[0]["huerfano"] == 1

    def test_posts_sueltos_una_conversacion_cada_uno(self):
        df, hilos = build_threads(_df([
            {"post_id": "a", "autor_handle": "u1"},
            {"post_id": "b", "autor_handle": "u2"},
        ]))
        assert df["conversacion_id"].tolist() == ["a", "b"]
        assert len(hilos) == 2
        assert set(hilos["n_posts"]) == {1}

    def test_ciclo_no_cuelga(self):
        df, _ = build_threads(_df([
            {"post_id": "a", "autor_handle": "u1", "en_respuesta_a": "b"},
            {"post_id": "b", "autor_handle": "u2", "en_respuesta_a": "a"},
        ]))
        # No importa el resultado exacto: importa terminar y marcar anómalos.
        assert len(df) == 2
