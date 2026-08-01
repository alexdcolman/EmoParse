# ══════════════════════════════════════════════════════════════════════════════
#  emoparse.viz.network_charts
#
#  Figuras Plotly para las tabs de tecnodiscurso (hilos, red, hashtags).
#  Complementa a viz.charts sin tocarlo; misma filosofía: funciones puras
#  DataFrame → Figure, sin Streamlit.
# ══════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

import math
from typing import Any

import pandas as pd
import plotly.graph_objects as go

from emoparse.viz import foria
from emoparse.viz.theme import BORDER, DIM, base_layout, titulo

#: Reexport de la paleta fórica canónica (definida en `viz.foria`), que las
#: tabs de tecnodiscurso ya importaban desde acá.
FORIA_COLORS = foria.FORIA_COLORS


def fig_red(
    df_aristas: pd.DataFrame,
    df_metricas: pd.DataFrame,
    max_nodos: int = 400,
    etiquetas: dict[str, str] | None = None,
) -> go.Figure:
    """Grafo de interacción con layout de resortes y color por comunidad.

    El layout se calcula acá (networkx spring, seed fija) sobre los
    `max_nodos` de mayor PageRank: para redes grandes, Gephi (export GEXF
    de `emoparse network`) es la herramienta adecuada.

    `etiquetas` mapea nodo → texto a mostrar al pasar el cursor. En los
    grafos de cuentas el identificador ya dice todo, pero en los de contenido
    y de parecido narrativo el nodo es un id opaco: sin esto, el grafo no se
    puede leer.
    """
    import networkx as nx

    if df_aristas.empty:
        return _fig_vacia("Sin aristas para este grafo.")

    top = set(
        df_metricas.sort_values("pagerank", ascending=False)["nodo"]
        .head(max_nodos)
        .astype(str)
    ) if not df_metricas.empty else None

    G = nx.Graph()
    for r in df_aristas.to_dict(orient="records"):
        u, v = str(r["origen"]), str(r["destino"])
        if top is not None and (u not in top or v not in top):
            continue
        w = float(r.get("peso", 1.0))
        if G.has_edge(u, v):
            G[u][v]["weight"] += w
        else:
            G.add_edge(u, v, weight=w)
    if G.number_of_nodes() == 0:
        return _fig_vacia("Sin nodos tras el filtro.")

    pos = nx.spring_layout(G, seed=42, weight="weight")
    metricas = (
        df_metricas.set_index("nodo") if not df_metricas.empty else None
    )

    edge_x: list[float | None] = []
    edge_y: list[float | None] = []
    for u, v in G.edges():
        edge_x += [pos[u][0], pos[v][0], None]
        edge_y += [pos[u][1], pos[v][1], None]

    node_x, node_y, textos, colores, tamanios = [], [], [], [], []
    for nodo in G.nodes():
        node_x.append(pos[nodo][0])
        node_y.append(pos[nodo][1])
        comunidad = None
        pagerank = 0.0
        if metricas is not None and nodo in metricas.index:
            fila = metricas.loc[nodo]
            comunidad = fila.get("comunidad")
            pagerank = float(fila.get("pagerank") or 0.0)
        encabezado = (etiquetas or {}).get(str(nodo)) or str(nodo)
        textos.append(
            f"{encabezado}<br>pagerank={pagerank:.4f}"
            + (f"<br>comunidad={int(comunidad)}" if comunidad is not None
               and not pd.isna(comunidad) else "")
        )
        colores.append(
            _color_comunidad(comunidad) if comunidad is not None else DIM
        )
        tamanios.append(8 + 60 * math.sqrt(pagerank))

    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=edge_x, y=edge_y, mode="lines",
        line=dict(width=0.5, color=BORDER),
        hoverinfo="none", showlegend=False,
    ))
    fig.add_trace(go.Scatter(
        x=node_x, y=node_y, mode="markers",
        marker=dict(size=tamanios, color=colores, line=dict(width=0)),
        text=textos, hoverinfo="text", showlegend=False,
    ))
    fig.update_layout(**base_layout(
        xaxis=dict(visible=False), yaxis=dict(visible=False),
        margin=dict(l=10, r=10, t=10, b=10), height=620,
    ))
    return fig


def fig_matriz_forica(matrix: pd.DataFrame) -> go.Figure:
    """Heatmap de la matriz de transición fórica padre→respuesta."""
    fig = go.Figure(go.Heatmap(
        z=matrix.values,
        x=list(matrix.columns),
        y=list(matrix.index),
        colorscale=[
            [0.0, "#16181f"],
            [0.5, foria.FORIA_COLORS["ambiforico"]],
            [1.0, foria.FORIA_COLORS["disforico"]],
        ],
        text=matrix.values,
        texttemplate="%{text}",
    ))
    fig.update_layout(**base_layout(
        title=titulo("Transición fórica padre → respuesta"),
        xaxis_title="foria de la respuesta",
        yaxis_title="foria del post padre",
        margin=dict(l=10, r=10, t=40, b=10), height=420,
    ))
    return fig


def fig_perfil_forico(perfil: pd.DataFrame) -> go.Figure:
    """Barras apiladas con la composición fórica de cada comunidad."""
    if perfil.empty:
        return _fig_vacia("Sin perfil emocional por comunidad.")
    forias = [f for f in foria.FORIA_ORDEN if f in perfil.columns]
    agg = perfil.groupby("comunidad")[forias].sum().sort_index()
    etiquetas = [f"comunidad {c}" for c in agg.index]

    fig = go.Figure()
    for f in forias:
        fig.add_trace(go.Bar(
            x=agg[f], y=etiquetas, name=foria.etiqueta(f), orientation="h",
            marker_color=foria.FORIA_COLORS[f],
            hovertemplate="%{y}<br>" + f + ": %{x}<extra></extra>",
        ))
    fig.update_layout(**base_layout(
        barmode="stack",
        margin=dict(l=10, r=10, t=10, b=10),
        height=max(260, 44 * len(agg)),
        xaxis_title="emociones",
        legend=dict(orientation="h", y=-0.2, font=dict(size=10)),
    ))
    return fig


def fig_hashtags_top(df: pd.DataFrame, top: int = 25) -> go.Figure:
    """Barras horizontales de hashtags por uso, coloreadas por foria del entorno."""
    if df.empty:
        return _fig_vacia("Sin hashtags en el corpus.")
    head = df.head(top).iloc[::-1]
    colores = [foria.color(f) for f in head["foria_entorno"]]
    fig = go.Figure(go.Bar(
        x=head["n_usos"], y=["#" + v for v in head["valor_norm"]],
        orientation="h", marker_color=colores,
        customdata=head[["funcion", "acoplamiento"]].fillna("-").values,
        hovertemplate="%{y}: %{x} usos<br>función: %{customdata[0]}"
                      "<br>%{customdata[1]}<extra></extra>",
    ))
    fig.update_layout(**base_layout(
        margin=dict(l=10, r=10, t=10, b=10),
        height=max(300, 22 * len(head)),
        xaxis_title="usos",
    ))
    return fig


def _color_comunidad(comunidad: Any) -> str:
    """Color estable por id de comunidad."""
    paleta = [
        "#6c5ce7", "#2e9e6b", "#d1495b", "#c9a227", "#3d9be9",
        "#e07be0", "#e6873c", "#4dd0c4", "#9e6b2e", "#8a8799",
    ]
    try:
        return paleta[int(comunidad) % len(paleta)]
    except (TypeError, ValueError):
        return DIM


def _fig_vacia(mensaje: str) -> go.Figure:
    fig = go.Figure()
    fig.add_annotation(text=mensaje, showarrow=False, font=dict(color=DIM))
    fig.update_layout(**base_layout(
        xaxis=dict(visible=False), yaxis=dict(visible=False), height=240,
    ))
    return fig
