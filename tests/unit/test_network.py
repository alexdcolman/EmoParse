# ══════════════════════════════════════════════════════════════════════════════
#  Tests de emoparse.network (builders, métricas, acoplamiento emocional)
# ══════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

import json

import pandas as pd
import pytest

from emoparse.network.builders import build_edges
from emoparse.network.emotion_coupling import (
    community_emotion_profile,
    foria_by_post,
    foria_transition_matrix,
)

nx = pytest.importorskip("networkx")

from emoparse.network.metrics import (  # noqa: E402  (tras importorskip)
    compute_node_metrics,
    detect_communities,
    to_graph,
)

pytestmark = pytest.mark.unit


def _posts() -> pd.DataFrame:
    base = {"en_respuesta_a": None, "reposteo_a": None, "cita_a": None,
            "fecha": "2026-05-01"}
    return pd.DataFrame([
        {**base, "post_id": "a", "autor_handle": "ana"},
        {**base, "post_id": "b", "autor_handle": "luis", "en_respuesta_a": "a"},
        {**base, "post_id": "c", "autor_handle": "ana", "en_respuesta_a": "b"},
        {**base, "post_id": "d", "autor_handle": "medio", "reposteo_a": "a"},
        {**base, "post_id": "e", "autor_handle": "irina", "cita_a": "a"},
        # referencia a post no capturado: no debe generar arista
        {**base, "post_id": "f", "autor_handle": "sol", "en_respuesta_a": "zzz"},
    ])


def _tecno() -> pd.DataFrame:
    return pd.DataFrame([
        {"codigo": "a", "unit_idx": 0, "tipo": "hashtag", "valor_norm": "tarifazo"},
        {"codigo": "a", "unit_idx": 0, "tipo": "hashtag", "valor_norm": "servicios"},
        {"codigo": "b", "unit_idx": 0, "tipo": "mencion", "valor_norm": "ana"},
        # automención: no debe generar arista
        {"codigo": "c", "unit_idx": 0, "tipo": "mencion", "valor_norm": "ana"},
        {"codigo": "e", "unit_idx": 0, "tipo": "emoji", "valor_norm": "cara"},
    ])


class TestBuilders:
    def test_reply_rt_qt(self):
        df = build_edges(_posts(), None, graphs=("reply", "rt", "qt"))
        por_grafo = {g: grp for g, grp in df.groupby("grafo")}
        assert [(r["origen"], r["destino"]) for _, r in por_grafo["reply"].iterrows()] == [
            ("luis", "ana"), ("ana", "luis"),
        ]
        assert por_grafo["rt"].iloc[0]["destino"] == "ana"
        assert por_grafo["qt"].iloc[0]["origen"] == "irina"

    def test_mention_excluye_automencion(self):
        df = build_edges(_posts(), _tecno(), graphs=("mention",))
        assert len(df) == 1
        assert (df.iloc[0]["origen"], df.iloc[0]["destino"]) == ("luis", "ana")

    def test_hashtag_co(self):
        df = build_edges(_posts(), _tecno(), graphs=("hashtag_co",))
        assert len(df) == 1
        assert (df.iloc[0]["origen"], df.iloc[0]["destino"]) == ("servicios", "tarifazo")

    def test_sin_aristas(self):
        vacio = pd.DataFrame(
            [{"post_id": "x", "autor_handle": "u", "en_respuesta_a": None,
              "reposteo_a": None, "cita_a": None, "fecha": None}]
        )
        df = build_edges(vacio, None)
        assert df.empty


class TestMetrics:
    def test_grafo_agrega_pesos(self):
        edges = pd.DataFrame([
            {"grafo": "reply", "origen": "a", "destino": "b", "peso": 1.0},
            {"grafo": "reply", "origen": "a", "destino": "b", "peso": 1.0},
        ])
        G = to_graph(edges)
        assert G["a"]["b"]["weight"] == 2.0

    def test_metricas_y_comunidades_deterministas(self):
        edges = pd.DataFrame([
            {"origen": a, "destino": b, "peso": 1.0}
            for a, b in [("a", "b"), ("b", "a"), ("a", "c"),
                         ("x", "y"), ("y", "z"), ("z", "x")]
        ])
        G = to_graph(edges)
        df = compute_node_metrics(G)
        assert set(df["nodo"]) == {"a", "b", "c", "x", "y", "z"}
        assert df["pagerank"].iloc[0] >= df["pagerank"].iloc[-1]
        c1 = detect_communities(G, seed=7)
        c2 = detect_communities(to_graph(edges), seed=7)
        assert c1 == c2
        # los dos triángulos separados caen en comunidades distintas
        assert c1["a"] == c1["b"] == c1["c"]
        assert c1["x"] == c1["y"] == c1["z"]
        assert c1["a"] != c1["x"]


class TestEmotionCoupling:
    def _emociones(self) -> pd.DataFrame:
        def car(foria):
            return json.dumps({"foria": foria})
        return pd.DataFrame([
            {"codigo": "a", "tipo_emocion": "indignación",
             "tipo_emocion_canonico": "indignación",
             "caracterizacion_payload": car("disforico")},
            {"codigo": "a", "tipo_emocion": "bronca",
             "tipo_emocion_canonico": "ira",
             "caracterizacion_payload": car("disforico")},
            {"codigo": "b", "tipo_emocion": "alegría",
             "tipo_emocion_canonico": "alegría",
             "caracterizacion_payload": car("euforico")},
            {"codigo": "c", "tipo_emocion": "esperanza",
             "tipo_emocion_canonico": None,
             "caracterizacion_payload": None},
        ])

    def test_foria_dominante(self):
        m = foria_by_post(self._emociones())
        assert m["a"] == "disforico"
        assert m["b"] == "euforico"
        assert m["c"] == "indeterminado"  # sin caracterización

    def test_transiciones(self):
        m = foria_by_post(self._emociones())
        matrix = foria_transition_matrix(_posts(), m)
        # a(disf) → b(euf) y b(euf) → c(indet)
        assert matrix.loc["disforico", "euforico"] == 1
        assert matrix.loc["euforico", "indeterminado"] == 1
        assert int(matrix.values.sum()) == 2

    def test_perfil_por_comunidad(self):
        m = {"ana": 0, "luis": 0, "irina": 1}
        perfil = community_emotion_profile(_posts(), m, self._emociones())
        com0 = perfil[perfil["comunidad"] == 0]
        assert set(com0["tipo_emocion"]) == {"indignación", "ira", "alegría", "esperanza"}
        fila = com0[com0["tipo_emocion"] == "indignación"].iloc[0]
        assert fila["n"] == 1 and fila["disforico"] == 1
