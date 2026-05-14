# ══════════════════════════════════════════════════════════════════════════════
#  tests/unit/test_viz_charts.py
#
#  Smoke tests de las visualizaciones plotly.
#
#  Las funciones devuelven go.Figure incluso cuando el input es vacío
#  o le faltan columnas (con un mensaje incrustado). Acá se testea:
#    - Que devuelven go.Figure (no exception).
#    - Que para input válido tienen ≥1 trace.
#    - Que para input vacío tienen 0 traces (caso `_empty_figure`).
#    - Que `curva_emocional_comparada` apila N paneles.
# ══════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import pytest

from emoparse.viz import charts


# ══════════════════════════════════════════════════════════════════════════════
#  Fixtures
# ══════════════════════════════════════════════════════════════════════════════

@pytest.fixture
def df_emociones() -> pd.DataFrame:
    """DataFrame de emociones similar al output de `data.get_emociones`."""
    return pd.DataFrame([
        {"codigo": "D1", "frase_idx": 0, "emocion_idx": 0,
         "experienciador": "yo", "tipo_emocion": "indignación",
         "modo_existencia": "actualizado", "frase": "Es una vergüenza.",
         "foria": "disfórico", "intensidad": "alta", "dominancia": "alta",
         "fuente": "moral",
         "discurso__fecha": "2024-12-15", "discurso__titulo": "D1 título"},
        {"codigo": "D1", "frase_idx": 1, "emocion_idx": 0,
         "experienciador": "yo", "tipo_emocion": "esperanza",
         "modo_existencia": "virtualizado", "frase": "Tengo esperanza.",
         "foria": "eufórico", "intensidad": "media", "dominancia": "media",
         "fuente": "personal",
         "discurso__fecha": "2024-12-15", "discurso__titulo": "D1 título"},
        {"codigo": "D1", "frase_idx": 2, "emocion_idx": 0,
         "experienciador": "ellos", "tipo_emocion": "miedo",
         "modo_existencia": "potencializado", "frase": "Tienen miedo.",
         "foria": "disfórico", "intensidad": "media", "dominancia": "baja",
         "fuente": "social",
         "discurso__fecha": "2024-12-15", "discurso__titulo": "D1 título"},
        {"codigo": "D2", "frase_idx": 0, "emocion_idx": 0,
         "experienciador": "yo", "tipo_emocion": "tristeza",
         "modo_existencia": "actualizado", "frase": "Estoy triste.",
         "foria": "disfórico", "intensidad": "baja", "dominancia": "baja",
         "fuente": "personal",
         "discurso__fecha": "2025-01-20", "discurso__titulo": "D2 título"},
        {"codigo": "D2", "frase_idx": 1, "emocion_idx": 0,
         "experienciador": "nosotros", "tipo_emocion": "esperanza",
         "modo_existencia": "virtualizado", "frase": "Hay esperanza.",
         "foria": "eufórico", "intensidad": "alta", "dominancia": "alta",
         "fuente": "colectiva",
         "discurso__fecha": "2025-01-20", "discurso__titulo": "D2 título"},
    ])


@pytest.fixture
def df_vacio() -> pd.DataFrame:
    return pd.DataFrame()


# ══════════════════════════════════════════════════════════════════════════════
#  curva_emocional
# ══════════════════════════════════════════════════════════════════════════════

def test_curva_emocional_returns_figure(df_emociones: pd.DataFrame) -> None:
    fig = charts.curva_emocional(df_emociones, "D1")
    assert isinstance(fig, go.Figure)
    # 3 emociones distintas en D1 → 3 traces.
    assert len(fig.data) == 3


def test_curva_emocional_empty_df_returns_empty_fig(df_vacio: pd.DataFrame) -> None:
    fig = charts.curva_emocional(df_vacio, "D1")
    assert isinstance(fig, go.Figure)
    assert len(fig.data) == 0  # _empty_figure no agrega traces


def test_curva_emocional_codigo_no_existe(df_emociones: pd.DataFrame) -> None:
    fig = charts.curva_emocional(df_emociones, "Dnoexiste")
    assert isinstance(fig, go.Figure)
    assert len(fig.data) == 0


def test_curva_emocional_respects_max_frases(df_emociones: pd.DataFrame) -> None:
    """Con max_frases=1, solo se rendea la primera frase."""
    fig = charts.curva_emocional(df_emociones, "D1", max_frases=1)
    # 1 frase → 1 emoción única → 1 trace.
    assert len(fig.data) == 1


def test_curva_emocional_acepta_recorte_id_legacy() -> None:
    """Si solo viene `recorte_id` (formato v1), extrae la posición del sufijo."""
    df = pd.DataFrame([
        {"codigo": "D1", "recorte_id": "frase_001",
         "tipo_emocion": "alegría", "experienciador": "yo",
         "modo_existencia": "actualizado", "frase": "x"},
        {"codigo": "D1", "recorte_id": "frase_002",
         "tipo_emocion": "tristeza", "experienciador": "yo",
         "modo_existencia": "actualizado", "frase": "y"},
    ])
    fig = charts.curva_emocional(df, "D1")
    assert isinstance(fig, go.Figure)
    assert len(fig.data) == 2


# ══════════════════════════════════════════════════════════════════════════════
#  curva_emocional_comparada
# ══════════════════════════════════════════════════════════════════════════════

def test_curva_comparada_dos_discursos(df_emociones: pd.DataFrame) -> None:
    fig = charts.curva_emocional_comparada(df_emociones, ["D1", "D2"])
    assert isinstance(fig, go.Figure)
    # Hay traces para ambos discursos.
    assert len(fig.data) > 0
    # Subplot apila por filas: el layout debe tener al menos yaxis2.
    assert "yaxis2" in fig.layout


def test_curva_comparada_sin_codigos(df_emociones: pd.DataFrame) -> None:
    fig = charts.curva_emocional_comparada(df_emociones, [])
    assert isinstance(fig, go.Figure)
    assert len(fig.data) == 0


def test_curva_comparada_codigos_inexistentes(df_emociones: pd.DataFrame) -> None:
    fig = charts.curva_emocional_comparada(df_emociones, ["X", "Y"])
    assert isinstance(fig, go.Figure)
    assert len(fig.data) == 0


def test_curva_comparada_un_solo_codigo(df_emociones: pd.DataFrame) -> None:
    """Con 1 código se comporta como un solo panel (no crashea)."""
    fig = charts.curva_emocional_comparada(df_emociones, ["D1"])
    assert isinstance(fig, go.Figure)
    assert len(fig.data) > 0


def test_curva_comparada_legend_no_duplica_emos() -> None:
    """Si una emoción está en ambos discursos, aparece UNA vez en la leyenda."""
    df = pd.DataFrame([
        {"codigo": "D1", "frase_idx": 0, "emocion_idx": 0,
         "tipo_emocion": "alegría", "experienciador": "yo",
         "modo_existencia": "actualizado", "frase": "x"},
        {"codigo": "D2", "frase_idx": 0, "emocion_idx": 0,
         "tipo_emocion": "alegría", "experienciador": "yo",
         "modo_existencia": "actualizado", "frase": "y"},
    ])
    fig = charts.curva_emocional_comparada(df, ["D1", "D2"])
    # Solo el primer trace de "alegría" tiene showlegend=True.
    showlegends = [t.showlegend for t in fig.data if t.name == "alegría"]
    assert showlegends.count(True) == 1
    assert showlegends.count(False) == 1


# ══════════════════════════════════════════════════════════════════════════════
#  distribucion_emociones
# ══════════════════════════════════════════════════════════════════════════════

def test_distribucion_returns_figure(df_emociones: pd.DataFrame) -> None:
    fig = charts.distribucion_emociones(df_emociones)
    assert isinstance(fig, go.Figure)
    assert len(fig.data) == 1  # un solo Bar trace


def test_distribucion_filtrada_por_codigo(df_emociones: pd.DataFrame) -> None:
    fig = charts.distribucion_emociones(df_emociones, codigo="D1")
    assert isinstance(fig, go.Figure)


def test_distribucion_empty(df_vacio: pd.DataFrame) -> None:
    fig = charts.distribucion_emociones(df_vacio)
    assert len(fig.data) == 0


# ══════════════════════════════════════════════════════════════════════════════
#  heatmap_actor_emocion
# ══════════════════════════════════════════════════════════════════════════════

def test_heatmap_returns_figure(df_emociones: pd.DataFrame) -> None:
    fig = charts.heatmap_actor_emocion(df_emociones)
    assert isinstance(fig, go.Figure)
    assert len(fig.data) == 1
    assert isinstance(fig.data[0], go.Heatmap)


def test_heatmap_normalize_off(df_emociones: pd.DataFrame) -> None:
    """Sin normalizar, los valores son enteros ≥0."""
    fig = charts.heatmap_actor_emocion(df_emociones, normalize=False)
    z = fig.data[0].z
    # Todos los valores deben ser >= 0 e integrales.
    flat = [v for row in z for v in row]
    assert all(v >= 0 for v in flat)
    assert all(int(v) == v for v in flat)


def test_heatmap_sin_columnas() -> None:
    df = pd.DataFrame([{"codigo": "D1"}])
    fig = charts.heatmap_actor_emocion(df)
    assert len(fig.data) == 0


# ══════════════════════════════════════════════════════════════════════════════
#  perfil_comparado
# ══════════════════════════════════════════════════════════════════════════════

def test_perfil_comparado(df_emociones: pd.DataFrame) -> None:
    fig = charts.perfil_comparado(df_emociones, ["D1", "D2"])
    assert isinstance(fig, go.Figure)
    # Una traza por emoción única (las 4 distintas del fixture).
    assert len(fig.data) == 4


def test_perfil_comparado_no_normalize(df_emociones: pd.DataFrame) -> None:
    fig = charts.perfil_comparado(df_emociones, ["D1", "D2"], normalize=False)
    assert isinstance(fig, go.Figure)


def test_perfil_comparado_codigos_vacios(df_emociones: pd.DataFrame) -> None:
    fig = charts.perfil_comparado(df_emociones, [])
    assert len(fig.data) == 0


# ══════════════════════════════════════════════════════════════════════════════
#  radar_discurso
# ══════════════════════════════════════════════════════════════════════════════

def test_radar_returns_figure(df_emociones: pd.DataFrame) -> None:
    fig = charts.radar_discurso(df_emociones, ["D1", "D2"])
    assert isinstance(fig, go.Figure)
    # Una traza Scatterpolar por discurso.
    assert len(fig.data) == 2


def test_radar_emociones_ref_explicit(df_emociones: pd.DataFrame) -> None:
    fig = charts.radar_discurso(
        df_emociones, ["D1", "D2"],
        emociones_ref=["esperanza", "indignación"],
    )
    assert len(fig.data) == 2


def test_radar_sin_codigos() -> None:
    df = pd.DataFrame([{"codigo": "D1", "tipo_emocion": "x"}])
    fig = charts.radar_discurso(df, [])
    assert len(fig.data) == 0


# ══════════════════════════════════════════════════════════════════════════════
#  scatter_foria_intensidad
# ══════════════════════════════════════════════════════════════════════════════

def test_scatter_foria_intensidad(df_emociones: pd.DataFrame) -> None:
    fig = charts.scatter_foria_intensidad(df_emociones)
    assert isinstance(fig, go.Figure)
    # Al menos un trace (por actor).
    assert len(fig.data) >= 1


def test_scatter_foria_filtrado(df_emociones: pd.DataFrame) -> None:
    fig = charts.scatter_foria_intensidad(df_emociones, codigo="D1")
    assert isinstance(fig, go.Figure)


def test_scatter_foria_sin_columnas() -> None:
    df = pd.DataFrame([{"codigo": "D1"}])
    fig = charts.scatter_foria_intensidad(df)
    assert len(fig.data) == 0


def test_scatter_foria_jitter_es_deterministico(df_emociones: pd.DataFrame) -> None:
    """Misma seed → misma posición de los puntos. Importante en Streamlit:
    cada interacción re-ejecuta el script y los puntos no deben saltar."""
    fig1 = charts.scatter_foria_intensidad(df_emociones)
    fig2 = charts.scatter_foria_intensidad(df_emociones)
    assert list(fig1.data[0].x) == list(fig2.data[0].x)
    assert list(fig1.data[0].y) == list(fig2.data[0].y)


# ══════════════════════════════════════════════════════════════════════════════
#  timeline_corpus
# ══════════════════════════════════════════════════════════════════════════════

def test_timeline_returns_figure(df_emociones: pd.DataFrame) -> None:
    fig = charts.timeline_corpus(df_emociones)
    assert isinstance(fig, go.Figure)
    # Al menos un trace por emoción dominante.
    assert len(fig.data) >= 1


def test_timeline_emocion_especifica(df_emociones: pd.DataFrame) -> None:
    fig = charts.timeline_corpus(df_emociones, emocion="esperanza")
    assert isinstance(fig, go.Figure)
    assert len(fig.data) == 1


def test_timeline_sin_fechas() -> None:
    df = pd.DataFrame([{"codigo": "D1", "tipo_emocion": "x"}])
    fig = charts.timeline_corpus(df)
    assert len(fig.data) == 0


def test_timeline_fechas_invalidas() -> None:
    df = pd.DataFrame([
        {"codigo": "D1", "tipo_emocion": "x", "discurso__fecha": "no-es-fecha"},
    ])
    fig = charts.timeline_corpus(df)
    assert len(fig.data) == 0


# ══════════════════════════════════════════════════════════════════════════════
#  trayectoria_comparada
# ══════════════════════════════════════════════════════════════════════════════

def test_trayectoria_returns_figure(df_emociones: pd.DataFrame) -> None:
    fig = charts.trayectoria_comparada(df_emociones, ["D1", "D2"], n_bins=5)
    assert isinstance(fig, go.Figure)
    assert len(fig.data) > 0


def test_trayectoria_codigos_vacios(df_emociones: pd.DataFrame) -> None:
    fig = charts.trayectoria_comparada(df_emociones, [])
    assert len(fig.data) == 0


# ══════════════════════════════════════════════════════════════════════════════
#  Helpers
# ══════════════════════════════════════════════════════════════════════════════

def test_emo_color_match_parcial() -> None:
    """'indignación profunda' debe caer en 'indignación'."""
    color = charts._emo_color("indignación profunda")
    assert color == charts.EMOTION_COLORS["indignación"]


def test_emo_color_string_vacio() -> None:
    assert charts._emo_color("") == charts.EMOTION_COLORS["neutro"]


def test_emo_color_emocion_desconocida_fallback() -> None:
    assert charts._emo_color("xyzzz") == charts.ACCENT2


def test_resolve_posicion_desde_frase_idx() -> None:
    df = pd.DataFrame([{"frase_idx": 0}, {"frase_idx": 5}])
    out = charts._resolve_posicion(df)
    assert out["posicion"].tolist() == [0.0, 5.0]


def test_resolve_posicion_desde_recorte_id_legacy() -> None:
    df = pd.DataFrame([{"recorte_id": "frase_001"}, {"recorte_id": "frase_042"}])
    out = charts._resolve_posicion(df)
    assert out["posicion"].tolist() == [1.0, 42.0]


def test_resolve_posicion_no_muta_input() -> None:
    df = pd.DataFrame([{"frase_idx": 0}])
    df_orig_cols = df.columns.tolist()
    charts._resolve_posicion(df)
    assert df.columns.tolist() == df_orig_cols  # input sin tocar
