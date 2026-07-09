# ══════════════════════════════════════════════════════════════════════════════
#  emoparse.viz.charts
#
#  Visualizaciones con plotly.
# ══════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

import unicodedata
from typing import Optional

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots


def _fold(s: object) -> str:
    """minúsculas sin acentos, para comparar valores de vocabulario de forma robusta."""
    txt = unicodedata.normalize("NFKD", str(s or ""))
    return "".join(c for c in txt if not unicodedata.combining(c)).strip().lower()


def _short_codigo(codigo: object, keep: int = 24) -> str:
    """Comprime un código largo dejando inicio y fin (para ejes de barras/subplots)."""
    c = str(codigo)
    if len(c) <= keep:
        return c
    head = keep // 2 - 1
    return f"{c[:head]}…{c[-head:]}"


# ══════════════════════════════════════════════════════════════════════════════
#  Constantes de estilo
# ══════════════════════════════════════════════════════════════════════════════

BG       = "#0e0f13"
SURFACE  = "#16181f"
BORDER   = "#252730"
ACCENT   = "#c8a96e"
ACCENT2  = "#7c9ec8"
TEXT_DIM = "#8a8799"
TEXT     = "#e8e4dc"
FONT     = "DM Mono, monospace"


#: Mapping emoción → color. Match parcial (substring) dentro de _emo_color.
EMOTION_COLORS: dict[str, str] = {
    "miedo":         "#7c9ec8",
    "indignación":   "#c86e6e",
    "ira":           "#c86e6e",
    "enojo":         "#c86e6e",
    "alegría":       "#c8a96e",
    "felicidad":     "#c8a96e",
    "orgullo":       "#e8c87a",
    "tristeza":      "#8a8799",
    "melancolía":    "#8a8799",
    "esperanza":     "#6ec89a",
    "optimismo":     "#6ec89a",
    "vergüenza":     "#9e7cc8",
    "culpa":         "#9e7cc8",
    "preocupación":  "#7caec8",
    "angustia":      "#7c8ec8",
    "amor":          "#c87ca0",
    "gratitud":      "#7cc8b8",
    "desprecio":     "#a87c5e",
    "desconfianza":  "#a8a07c",
    "neutro":        "#3a3d4e",
}

FORIA_COLORS: dict[str, str] = {
    "eufórico":      "#6ec89a",
    "disfórico":     "#c86e6e",
    "afórico":       "#5a5d6e",
    "ambifórico":    "#c8a96e",
    "indeterminado": "#3a3d4e",
}

INTENSIDAD_ORDER = ["muy baja", "baja", "media", "alta", "muy alta"]


def emo_color(emocion: str) -> str:
    """Color de una emoción por substring match."""
    if not emocion:
        return EMOTION_COLORS["neutro"]
    emo_lower = str(emocion).lower()
    for key, color in EMOTION_COLORS.items():
        if key in emo_lower:
            return color
    return ACCENT2


def _base_layout(**kwargs) -> dict:
    """Layout base compartido por todas las figuras."""
    base = dict(
        paper_bgcolor=BG,
        plot_bgcolor=SURFACE,
        font=dict(family=FONT, color=TEXT_DIM, size=11),
        xaxis=dict(gridcolor=BORDER, zerolinecolor=BORDER),
        yaxis=dict(gridcolor=BORDER, zerolinecolor=BORDER),
        legend=dict(
            bgcolor=SURFACE, bordercolor=BORDER, borderwidth=1,
            font=dict(size=10),
        ),
        margin=dict(l=10, r=10, t=40, b=10),
        hoverlabel=dict(
            bgcolor=SURFACE, bordercolor=BORDER,
            font=dict(family=FONT, size=11),
        ),
    )
    base.update(kwargs)
    return base


def _resolve_posicion(df: pd.DataFrame) -> pd.DataFrame:
    """Asegura una columna `posicion` (float) en el DataFrame."""
    if "posicion" in df.columns:
        return df
    out = df.copy()
    if "frase_idx" in out.columns:
        out["posicion"] = pd.to_numeric(out["frase_idx"], errors="coerce")
    elif "recorte_id" in out.columns:
        out["posicion"] = (
            out["recorte_id"].astype(str)
            .str.extract(r"(\d+)$")[0]
            .astype(float)
        )
    return out


def _empty_figure(msg: str = "Sin datos") -> go.Figure:
    """Figura vacía con un mensaje centrado."""
    fig = go.Figure()
    fig.add_annotation(
        text=msg, xref="paper", yref="paper", x=0.5, y=0.5,
        showarrow=False,
        font=dict(color=TEXT_DIM, size=13, family=FONT),
    )
    fig.update_layout(
        paper_bgcolor=BG, plot_bgcolor=SURFACE,
        xaxis=dict(visible=False), yaxis=dict(visible=False),
        height=250, margin=dict(l=10, r=10, t=10, b=10),
    )
    return fig


# ══════════════════════════════════════════════════════════════════════════════
#  1. Curva emocional frase a frase
# ══════════════════════════════════════════════════════════════════════════════

def _apply_relative_pos(df: pd.DataFrame, relativa: bool) -> pd.DataFrame:
    """Convierte `posicion` a porcentaje del discurso (0–100) si `relativa`.

    Usa `pos_max_discurso` (longitud real del discurso) cuando está disponible;
    si no, cae al máximo observado dentro del propio discurso.
    """
    if not relativa or "posicion" not in df.columns:
        return df
    out = df.copy()
    if "pos_max_discurso" in out.columns and out["pos_max_discurso"].notna().any():
        denom = pd.to_numeric(out["pos_max_discurso"], errors="coerce")
    else:
        denom = out["posicion"]
    denom = denom.where(denom > 0, other=pd.NA)
    out["posicion"] = out["posicion"] / denom * 100.0
    return out


def _curva_hover(
    df_emo: pd.DataFrame, emo: str, *, text_col: str, actor_col: str,
    fuente_col: Optional[str], relativa: bool, prefix: str = "",
) -> list[str]:
    """Texto de tooltip de cada punto de la curva (actor/fuente canónicos + posición)."""
    n = len(df_emo)
    textos = df_emo[text_col] if text_col in df_emo.columns else pd.Series([""] * n)
    actores = df_emo[actor_col] if actor_col in df_emo.columns else pd.Series(["?"] * n)
    modos = df_emo["modo_existencia"] if "modo_existencia" in df_emo.columns else pd.Series(["?"] * n)
    fuentes = (
        df_emo[fuente_col] if fuente_col and fuente_col in df_emo.columns
        else pd.Series([None] * n)
    )
    pos_fmt = (lambda p: f"{p:.0f}%") if relativa else (lambda p: f"{int(p)}")
    out: list[str] = []
    for p, a, m, f, t in zip(df_emo["posicion"], actores, modos, fuentes, textos):
        linea_f = f"<br>Fuente: {f}" if f not in (None, "", "—") else ""
        out.append(
            f"<b>{emo}</b>{prefix}<br>Pos: {pos_fmt(p)}<br>Actor: {a}<br>"
            f"Modo: {m}{linea_f}<br><i>{str(t)[:120]}…</i>"
        )
    return out


def curva_emocional(
    df: pd.DataFrame,
    codigo: str,
    *,
    text_col: str = "frase",
    max_frases: int = 200,
    actor_col: str = "experienciador",
    fuente_col: Optional[str] = None,
    posicion_relativa: bool = False,
) -> go.Figure:
    """Scatter plot de emociones detectadas a lo largo de un discurso.

    `actor_col`/`fuente_col` eligen qué columnas mostrar en el tooltip (p. ej. el
    experienciador/fuente canónicos, o los crudos del LLM). `posicion_relativa`
    normaliza el eje X a porcentaje del discurso.
    """
    if "codigo" in df.columns:
        df_sel = df[df["codigo"] == codigo].copy()
    else:
        df_sel = df.copy()

    if df_sel.empty:
        return _empty_figure(f"Sin datos para {codigo}")

    df_sel = _resolve_posicion(df_sel)
    if "posicion" not in df_sel.columns:
        return _empty_figure("Sin columna de posición (frase_idx)")
    df_sel = df_sel.dropna(subset=["posicion"]).sort_values("posicion").head(max_frases)
    df_sel = _apply_relative_pos(df_sel, posicion_relativa)

    if df_sel.empty:
        return _empty_figure("Sin frases con posición válida")

    if "tipo_emocion" not in df_sel.columns:
        return _empty_figure("Sin columna 'tipo_emocion'")

    emociones = df_sel["tipo_emocion"].dropna().unique().tolist()
    fig = go.Figure()

    for emo in emociones:
        df_emo = df_sel[df_sel["tipo_emocion"] == emo]
        color = emo_color(emo)
        hover_text = _curva_hover(
            df_emo, emo, text_col=text_col, actor_col=actor_col,
            fuente_col=fuente_col, relativa=posicion_relativa,
        )
        fig.add_trace(go.Scatter(
            x=df_emo["posicion"], y=[emo] * len(df_emo),
            mode="markers", name=emo,
            marker=dict(
                color=color, size=10, symbol="circle",
                line=dict(color=BORDER, width=1), opacity=0.85,
            ),
            hovertext=hover_text, hoverinfo="text",
        ))

    xtitle = "Posición relativa (%)" if posicion_relativa else "Posición en el discurso"
    fig.update_layout(**_base_layout(
        title=dict(text=f"Trayectoria emocional · {codigo}", font=dict(color=ACCENT, size=13)),
        xaxis_title=xtitle,
        yaxis_title="Emoción",
        height=max(300, len(emociones) * 50 + 100),
    ))
    return fig


def curva_emocional_comparada(
    df: pd.DataFrame,
    codigos: list[str],
    *,
    text_col: str = "frase",
    max_frases: int = 200,
    actor_col: str = "experienciador",
    fuente_col: Optional[str] = None,
    posicion_relativa: bool = False,
) -> go.Figure:
    """Curva emocional comparada: un panel por discurso, eje X compartido.

    En comparación, cada panel puede recibir un sub-DataFrame ya filtrado de forma
    independiente (el llamador concatena los recortes por discurso). `actor_col`/
    `fuente_col` y `posicion_relativa` se comportan igual que en `curva_emocional`.
    """
    if not codigos:
        return _empty_figure("Sin discursos")
    if "codigo" not in df.columns:
        return _empty_figure("Falta columna 'codigo'")

    n = len(codigos)
    fig = make_subplots(
        rows=n, cols=1, shared_xaxes=True,
        subplot_titles=[f"· {_short_codigo(c)}" for c in codigos],
        vertical_spacing=0.10,
    )

    df_all = df[df["codigo"].isin(codigos)].copy()
    df_all = _resolve_posicion(df_all)
    if df_all.empty or "tipo_emocion" not in df_all.columns:
        return _empty_figure("Sin datos para los discursos seleccionados")

    emociones_globales = df_all["tipo_emocion"].dropna().unique().tolist()
    seen_emos: set[str] = set()

    for row_idx, codigo in enumerate(codigos, start=1):
        df_sel = df_all[df_all["codigo"] == codigo]
        df_sel = df_sel.dropna(subset=["posicion"]).sort_values("posicion").head(max_frases)
        df_sel = _apply_relative_pos(df_sel, posicion_relativa)
        if df_sel.empty:
            continue

        for emo in emociones_globales:
            df_emo = df_sel[df_sel["tipo_emocion"] == emo]
            if df_emo.empty:
                continue
            color = emo_color(emo)
            hover = _curva_hover(
                df_emo, emo, text_col=text_col, actor_col=actor_col,
                fuente_col=fuente_col, relativa=posicion_relativa,
                prefix=f"<br>{_short_codigo(codigo)}",
            )
            show_in_legend = emo not in seen_emos
            seen_emos.add(emo)
            fig.add_trace(
                go.Scatter(
                    x=df_emo["posicion"], y=[emo] * len(df_emo),
                    mode="markers", name=emo,
                    marker=dict(
                        color=color, size=9, symbol="circle",
                        line=dict(color=BORDER, width=1), opacity=0.85,
                    ),
                    legendgroup=emo,
                    showlegend=show_in_legend,
                    hovertext=hover, hoverinfo="text",
                ),
                row=row_idx, col=1,
            )

    fig.update_layout(
        paper_bgcolor=BG, plot_bgcolor=SURFACE,
        font=dict(family=FONT, color=TEXT_DIM, size=11),
        title=dict(
            text=f"Curva emocional comparada · {len(codigos)} discursos",
            font=dict(color=ACCENT, size=13),
        ),
        height=max(280, 240 * n + 60),
        margin=dict(l=10, r=10, t=60, b=10),
        legend=dict(
            bgcolor=SURFACE, bordercolor=BORDER, borderwidth=1,
            font=dict(size=10),
        ),
        hoverlabel=dict(bgcolor=SURFACE, bordercolor=BORDER, font=dict(family=FONT, size=11)),
    )
    xtitle = "Posición relativa (%)" if posicion_relativa else "Posición"
    fig.update_xaxes(gridcolor=BORDER, zerolinecolor=BORDER, title_text=xtitle)
    fig.update_yaxes(gridcolor=BORDER, zerolinecolor=BORDER)
    # Los títulos de subplot (códigos comprimidos) van más chicos para no saturar.
    for ann in fig.layout.annotations:
        ann.font = dict(size=10, color=TEXT_DIM, family=FONT)
    return fig


# ══════════════════════════════════════════════════════════════════════════════
#  2. Distribución de emociones (barras)
# ══════════════════════════════════════════════════════════════════════════════

def distribucion_emociones(
    df: pd.DataFrame,
    codigo: Optional[str] = None,
    *,
    por: str = "tipo_emocion",
) -> go.Figure:
    """Barras horizontales de frecuencia."""
    df_f = df[df["codigo"] == codigo].copy() if codigo and "codigo" in df.columns else df.copy()
    if df_f.empty or por not in df_f.columns:
        return _empty_figure("Sin datos")

    counts = df_f[por].value_counts().reset_index()
    counts.columns = ["emocion", "n"]
    counts = counts.sort_values("n")
    colors = [emo_color(e) for e in counts["emocion"]]

    fig = go.Figure(go.Bar(
        x=counts["n"], y=counts["emocion"], orientation="h",
        marker=dict(color=colors, line=dict(color=BORDER, width=0.5)),
        hovertemplate="<b>%{y}</b><br>%{x} ocurrencias<extra></extra>",
    ))
    titulo = f"Distribución · {codigo}" if codigo else "Distribución de emociones"
    fig.update_layout(**_base_layout(
        title=dict(text=titulo, font=dict(color=ACCENT, size=13)),
        xaxis_title="Frecuencia", yaxis_title="",
        height=max(250, len(counts) * 35 + 80),
        showlegend=False,
    ))
    return fig


# ══════════════════════════════════════════════════════════════════════════════
#  3. Heatmap actores × emociones
# ══════════════════════════════════════════════════════════════════════════════

def heatmap_actor_emocion(
    df: pd.DataFrame,
    *,
    top_actores: int = 12,
    top_emociones: int = 10,
    normalize: bool = True,
    actor_col: str = "experienciador",
) -> go.Figure:
    """Co-ocurrencia actor × tipo_emocion. `actor_col` elige la columna de actor
    (p. ej. el experienciador canónico o el crudo del LLM)."""
    if actor_col not in df.columns or "tipo_emocion" not in df.columns:
        return _empty_figure(f"Faltan columnas '{actor_col}' y/o 'tipo_emocion'")

    df = df[df[actor_col].astype(str).str.strip().replace("—", "") != ""]
    top_act = df[actor_col].value_counts().head(top_actores).index.tolist()
    top_emo = df["tipo_emocion"].value_counts().head(top_emociones).index.tolist()
    if not top_act or not top_emo:
        return _empty_figure("Sin datos suficientes")

    df_f = df[df[actor_col].isin(top_act) & df["tipo_emocion"].isin(top_emo)]
    pivot = (
        df_f.groupby([actor_col, "tipo_emocion"])
        .size().unstack(fill_value=0)
        .reindex(index=top_act, columns=top_emo, fill_value=0)
    )
    if normalize:
        pivot = pivot.div(pivot.sum(axis=1).replace(0, 1), axis=0)
        label = "proporción"
    else:
        label = "frecuencia"

    text_df = pivot.map(lambda v: f"{v:.1%}" if normalize else str(int(v)))

    fig = go.Figure(go.Heatmap(
        z=pivot.values, x=pivot.columns.tolist(), y=pivot.index.tolist(),
        text=text_df.values.tolist(), texttemplate="%{text}",
        colorscale=[
            [0.0, SURFACE], [0.3, "#1e3040"], [0.6, "#2a5070"],
            [0.85, ACCENT2], [1.0, "#c8e0f0"],
        ],
        showscale=True,
        colorbar=dict(
            title=label, tickfont=dict(family=FONT, size=10),
            outlinecolor=BORDER, outlinewidth=1,
        ),
        hovertemplate="<b>Actor:</b> %{y}<br><b>Emoción:</b> %{x}<br><b>Valor:</b> %{text}<extra></extra>",
    ))
    fig.update_layout(**_base_layout(
        title=dict(text="Actor × Emoción", font=dict(color=ACCENT, size=13)),
        height=max(300, len(top_act) * 40 + 120),
        xaxis=dict(tickangle=-35, gridcolor=BORDER),
        yaxis=dict(gridcolor=BORDER),
    ))
    return fig


# ══════════════════════════════════════════════════════════════════════════════
#  4. Perfil emocional comparado (barras apiladas)
# ══════════════════════════════════════════════════════════════════════════════

def perfil_comparado(
    df: pd.DataFrame,
    codigos: list[str],
    *,
    normalize: bool = True,
) -> go.Figure:
    """Barras apiladas: perfil emocional de N discursos en una sola figura."""
    if not codigos or "codigo" not in df.columns:
        return _empty_figure("Sin datos para comparar")

    df_f = df[df["codigo"].isin(codigos)]
    if df_f.empty or "tipo_emocion" not in df_f.columns:
        return _empty_figure("Sin emociones en los discursos seleccionados")

    pivot = (
        df_f.groupby(["codigo", "tipo_emocion"])
        .size().unstack(fill_value=0)
        .reindex(codigos, fill_value=0)
    )
    if normalize:
        pivot = pivot.div(pivot.sum(axis=1).replace(0, 1), axis=0)

    fig = go.Figure()
    labels = [_short_codigo(c) for c in pivot.index]
    full = list(pivot.index)
    for emocion in pivot.columns:
        color = emo_color(emocion)
        vals = pivot[emocion].tolist()
        fmt = [f"{v:.1%}" if normalize else str(int(v)) for v in vals]
        fig.add_trace(go.Bar(
            name=emocion, x=labels, y=vals,
            marker_color=color, marker_line=dict(color=BORDER, width=0.5),
            text=fmt, textposition="inside",
            textfont=dict(size=9, color="#ffffff"),
            customdata=full,
            hovertemplate=f"<b>{emocion}</b><br>%{{customdata}}<br>%{{text}}<extra></extra>",
        ))

    fig.update_layout(**_base_layout(
        title=dict(text="Perfil emocional comparado", font=dict(color=ACCENT, size=13)),
        barmode="stack",
        xaxis=dict(tickangle=-20, gridcolor=BORDER, automargin=True,
                   tickfont=dict(size=10)),
        yaxis=dict(
            gridcolor=BORDER,
            tickformat=".0%" if normalize else "",
            title="proporción" if normalize else "frecuencia",
        ),
        height=560,
        bargap=0.35,
        legend=dict(
            orientation="h", yanchor="bottom", y=-0.28,
            xanchor="center", x=0.5,
            font=dict(size=10), bgcolor=SURFACE, bordercolor=BORDER,
        ),
    ))
    return fig


# ══════════════════════════════════════════════════════════════════════════════
#  5. Trayectoria emocional comparada (líneas por segmentos)
# ══════════════════════════════════════════════════════════════════════════════

def trayectoria_comparada(
    df: pd.DataFrame,
    codigos: list[str],
    *,
    n_bins: int = 10,
) -> go.Figure:
    """Emoción dominante por segmento, una línea por discurso."""
    if not codigos:
        return _empty_figure("Sin discursos seleccionados")
    if "codigo" not in df.columns:
        return _empty_figure("Falta columna 'codigo'")

    df_f = df[df["codigo"].isin(codigos)].copy()
    if df_f.empty:
        return _empty_figure("Sin datos")
    df_f = _resolve_posicion(df_f)
    if "posicion" not in df_f.columns:
        return _empty_figure("Sin posición de frases")

    fig = go.Figure()
    all_emociones: set[str] = set()

    for codigo in codigos:
        df_disc = df_f[df_f["codigo"] == codigo].dropna(subset=["posicion"])
        if df_disc.empty:
            continue
        pos_min = df_disc["posicion"].min()
        pos_max = df_disc["posicion"].max()

        bins_data = []
        for b in range(n_bins):
            lo = pos_min + (pos_max - pos_min) * b / n_bins
            hi = pos_min + (pos_max - pos_min) * (b + 1) / n_bins
            segmento = df_disc[(df_disc["posicion"] >= lo) & (df_disc["posicion"] < hi)]
            if not segmento.empty and "tipo_emocion" in segmento.columns:
                emo_dom = segmento["tipo_emocion"].value_counts().index[0]
            else:
                emo_dom = "neutro"
            bins_data.append((b + 0.5, emo_dom))
            all_emociones.add(emo_dom)

        xs = [b[0] for b in bins_data]
        ys = [b[1] for b in bins_data]

        for i in range(len(xs) - 1):
            color = emo_color(ys[i])
            fig.add_trace(go.Scatter(
                x=[xs[i], xs[i + 1]], y=[ys[i], ys[i + 1]],
                mode="lines",
                line=dict(color=color, width=2.5),
                showlegend=False, hoverinfo="skip",
            ))

        fig.add_trace(go.Scatter(
            x=xs, y=ys, mode="markers+text", name=codigo,
            text=[str(int(x)) for x in xs], textposition="top center",
            textfont=dict(size=8, color=TEXT_DIM),
            marker=dict(
                color=[emo_color(e) for e in ys], size=12,
                line=dict(color=BORDER, width=1),
            ),
            hovertemplate=f"<b>{codigo}</b><br>Segmento %{{x:.0f}}<br>Emoción: %{{y}}<extra></extra>",
        ))

    fig.update_layout(**_base_layout(
        title=dict(text="Trayectoria emocional comparada", font=dict(color=ACCENT, size=13)),
        xaxis=dict(
            title=f"Segmento del discurso (1–{n_bins})",
            gridcolor=BORDER, tickvals=list(range(1, n_bins + 1)),
        ),
        yaxis=dict(
            title="Emoción dominante", gridcolor=BORDER,
            categoryorder="array", categoryarray=sorted(all_emociones),
        ),
        height=560,
    ))
    return fig


# ══════════════════════════════════════════════════════════════════════════════
#  6. Radar emocional
# ══════════════════════════════════════════════════════════════════════════════

def radar_discurso(
    df: pd.DataFrame,
    codigos: list[str],
    *,
    emociones_ref: Optional[list[str]] = None,
) -> go.Figure:
    """Radar comparando perfil emocional. Hasta ~5 discursos legibles."""
    if not codigos:
        return _empty_figure("Sin discursos")
    df_f = df[df["codigo"].isin(codigos)] if "codigo" in df.columns else df
    if df_f.empty or "tipo_emocion" not in df_f.columns:
        return _empty_figure("Sin emociones")

    if emociones_ref is None:
        emociones_ref = df_f["tipo_emocion"].value_counts().head(8).index.tolist()
    if not emociones_ref:
        return _empty_figure("Sin emociones para el radar")

    fig = go.Figure()
    disc_colors = [ACCENT, ACCENT2, "#6ec89a", "#c86e6e", "#9e7cc8"]

    for i, codigo in enumerate(codigos):
        df_disc = df_f[df_f["codigo"] == codigo] if "codigo" in df_f.columns else df_f
        counts = df_disc["tipo_emocion"].value_counts()
        total = counts.sum() or 1
        vals = [counts.get(e, 0) / total for e in emociones_ref]
        vals_cerrado = vals + [vals[0]]
        cats_cerrado = emociones_ref + [emociones_ref[0]]
        color = disc_colors[i % len(disc_colors)]
        r, g, b = int(color[1:3], 16), int(color[3:5], 16), int(color[5:7], 16)
        fillcolor = f"rgba({r},{g},{b},0.13)"
        fig.add_trace(go.Scatterpolar(
            r=vals_cerrado, theta=cats_cerrado,
            fill="toself", fillcolor=fillcolor,
            line=dict(color=color, width=2),
            name=codigo,
            hovertemplate=f"<b>{codigo}</b><br>%{{theta}}: %{{r:.1%}}<extra></extra>",
        ))

    fig.update_layout(
        polar=dict(
            bgcolor=SURFACE,
            radialaxis=dict(
                visible=True, range=[0, 1], tickformat=".0%",
                gridcolor=BORDER, linecolor=BORDER,
                tickfont=dict(size=9, color=TEXT_DIM),
            ),
            angularaxis=dict(
                gridcolor=BORDER, linecolor=BORDER,
                tickfont=dict(size=10, color=TEXT),
            ),
        ),
        paper_bgcolor=BG, font=dict(family=FONT, color=TEXT_DIM),
        title=dict(text="Radar emocional", font=dict(color=ACCENT, size=13)),
        legend=dict(bgcolor=SURFACE, bordercolor=BORDER, borderwidth=1),
        height=620, margin=dict(l=60, r=60, t=70, b=50),
        hoverlabel=dict(bgcolor=SURFACE, bordercolor=BORDER),
    )
    return fig


# ══════════════════════════════════════════════════════════════════════════════
#  7. Scatter foria × intensidad
# ══════════════════════════════════════════════════════════════════════════════

def scatter_foria_intensidad(
    df: pd.DataFrame,
    codigo: Optional[str] = None,
    *,
    top_actores: int = 8,
    actor_col: str = "experienciador",
) -> go.Figure:
    """Scatter foria × intensidad, color por actor (`actor_col`)."""
    cols_req = {"foria", "intensidad", "tipo_emocion"}
    if not cols_req.issubset(df.columns):
        return _empty_figure(f"Faltan columnas: {cols_req - set(df.columns)}")

    df_f = df[df["codigo"] == codigo].copy() if codigo and "codigo" in df.columns else df.copy()
    if df_f.empty:
        return _empty_figure("Sin datos")

    # Mapas insensibles a acentos y tolerantes a los distintos vocabularios de la
    # ontología (foria sin acentos; intensidad de 3 niveles baja/neutra/alta, o el
    # esquema previo de 5). Sin esto, un desajuste de acentos dropea todas las filas.
    foria_map = {
        "euforico": 1, "ambiforico": 0, "aforico": 0,
        "disforico": -1, "indeterminado": None,
    }
    df_f["foria_num"] = df_f["foria"].map(lambda v: foria_map.get(_fold(v)))
    df_f = df_f.dropna(subset=["foria_num"])

    intens_map = {
        "muy baja": 1, "baja": 2, "neutra_ambivalente": 3, "neutra ambivalente": 3,
        "media": 3, "neutra": 3, "alta": 4, "muy alta": 5,
    }
    df_f["intens_num"] = df_f["intensidad"].map(lambda v: intens_map.get(_fold(v)))
    df_f = df_f.dropna(subset=["intens_num"])

    if df_f.empty:
        return _empty_figure("Sin datos de foria/intensidad válidos")

    if actor_col in df_f.columns:
        df_f = df_f[df_f[actor_col].astype(str).str.strip().replace("—", "") != ""]
        top_act = df_f[actor_col].value_counts().head(top_actores).index.tolist()
        df_f = df_f[df_f[actor_col].isin(top_act)]

    act_colors = [
        ACCENT, ACCENT2, "#6ec89a", "#c86e6e", "#9e7cc8",
        "#c87ca0", "#7cc8b8", "#a87c5e",
    ]

    fig = go.Figure()
    actores = (
        df_f[actor_col].unique() if actor_col in df_f.columns else ["(todos)"]
    )

    import numpy as np
    rng = np.random.default_rng(seed=42)

    for i, actor in enumerate(actores):
        df_act = (
            df_f[df_f[actor_col] == actor]
            if actor_col in df_f.columns else df_f
        )
        color = act_colors[i % len(act_colors)]
        jitter_x = df_act["foria_num"].values + (rng.random(len(df_act)) - 0.5) * 0.15
        jitter_y = df_act["intens_num"].values + (rng.random(len(df_act)) - 0.5) * 0.2

        fig.add_trace(go.Scatter(
            x=jitter_x, y=jitter_y, mode="markers", name=str(actor),
            marker=dict(
                color=color, size=9, opacity=0.75,
                line=dict(color=BORDER, width=0.5),
            ),
            text=df_act["tipo_emocion"].astype(str),
            hovertemplate=(
                f"<b>{actor}</b><br>Emoción: %{{text}}<br>"
                "Foria: %{x:.1f}<br>Intensidad: %{y:.1f}<extra></extra>"
            ),
        ))

    fig.add_vline(x=0, line=dict(color=BORDER, width=1, dash="dot"))
    fig.add_hline(y=3, line=dict(color=BORDER, width=1, dash="dot"))

    fig.update_layout(**_base_layout(
        title=dict(text="Foria × Intensidad por actor", font=dict(color=ACCENT, size=13)),
        xaxis=dict(
            title="← Disfórico | Eufórico →", range=[-1.5, 1.5],
            tickvals=[-1, 0, 1],
            ticktext=["disfórico", "afórico/ambifórico", "eufórico"],
            gridcolor=BORDER,
        ),
        yaxis=dict(
            title="Intensidad", range=[0.5, 5.5],
            tickvals=[1, 2, 3, 4, 5],
            ticktext=["muy baja", "baja", "neutra/media", "alta", "muy alta"],
            gridcolor=BORDER,
        ),
        height=440,
    ))
    return fig


# ══════════════════════════════════════════════════════════════════════════════
#  8. Timeline histórico del corpus
# ══════════════════════════════════════════════════════════════════════════════

def timeline_corpus(
    df_em: pd.DataFrame,
    *,
    emocion: Optional[str] = None,
) -> go.Figure:
    """Evolución temporal de la emoción dominante (o de una específica)."""
    if "codigo" not in df_em.columns or "discurso__fecha" not in df_em.columns:
        return _empty_figure("Falta 'codigo' o 'discurso__fecha' (¿está la stage `metadata`?)")

    fechas = df_em.dropna(subset=["discurso__fecha"]).copy()
    fechas["fecha_dt"] = pd.to_datetime(fechas["discurso__fecha"], errors="coerce")
    fechas = fechas.dropna(subset=["fecha_dt"])
    if fechas.empty:
        return _empty_figure("Sin fechas válidas")

    puntos: list[dict] = []
    for codigo, df_disc in fechas.groupby("codigo"):
        if df_disc.empty:
            continue
        fecha_dt = df_disc["fecha_dt"].iloc[0]
        titulo = str(df_disc.get("discurso__titulo", pd.Series([codigo])).iloc[0])[:50]
        enunciador = (
            str(df_disc["enunciador"].iloc[0]) if "enunciador" in df_disc.columns else ""
        )
        if emocion:
            total = len(df_disc)
            n_emo = (df_disc["tipo_emocion"] == emocion).sum()
            prop = n_emo / total if total > 0 else 0
            label = emocion
        else:
            counts = df_disc["tipo_emocion"].value_counts()
            if counts.empty:
                continue
            label = counts.index[0]
            prop = counts.iloc[0] / counts.sum()
        puntos.append({
            "fecha": fecha_dt, "codigo": codigo,
            "titulo": titulo, "enunciador": enunciador,
            "emocion": label, "prop": prop,
        })

    if not puntos:
        return _empty_figure("Sin datos para el timeline")

    df_plot = pd.DataFrame(puntos).sort_values("fecha")

    if emocion:
        color = emo_color(emocion)
        fig = go.Figure(go.Scatter(
            x=df_plot["fecha"], y=df_plot["prop"],
            mode="lines+markers",
            line=dict(color=color, width=2),
            marker=dict(color=color, size=8, line=dict(color=BORDER, width=1)),
            customdata=df_plot[["codigo", "enunciador"]].values,
            hovertemplate=(
                "<b>%{text}</b><br>%{customdata[0]}<br>"
                "Enunciador: %{customdata[1]}<br>%{x|%Y-%m-%d}<br>"
                "Proporción: %{y:.1%}<extra></extra>"
            ),
            text=df_plot["titulo"],
            name=emocion,
        ))
        titulo_fig = f"Evolución de '{emocion}' en el corpus"
    else:
        fig = go.Figure()
        for emo in df_plot["emocion"].unique():
            df_emo = df_plot[df_plot["emocion"] == emo]
            fig.add_trace(go.Scatter(
                x=df_emo["fecha"], y=df_emo["prop"],
                mode="markers", name=emo,
                marker=dict(
                    color=emo_color(emo), size=10,
                    line=dict(color=BORDER, width=1),
                ),
                text=df_emo["titulo"],
                customdata=df_emo[["codigo", "enunciador"]].values,
                hovertemplate=(
                    "<b>%{text}</b><br>%{customdata[0]}<br>"
                    "Enunciador: %{customdata[1]}<br>%{x|%Y-%m-%d}<br>"
                    f"{emo}: %{{y:.1%}}<extra></extra>"
                ),
            ))
        titulo_fig = "Emoción dominante por discurso (corpus)"

    fig.update_layout(**_base_layout(
        title=dict(text=titulo_fig, font=dict(color=ACCENT, size=13)),
        xaxis=dict(title="Fecha", gridcolor=BORDER, type="date"),
        yaxis=dict(title="Proporción", tickformat=".0%", gridcolor=BORDER),
        height=380,
    ))
    return fig


def filtrar_por_canonicos(
    df: pd.DataFrame,
    canonicos: set[str] | list[str],
    col: str = "experienciador_canonico",
) -> pd.DataFrame:
    """Filtra un DataFrame de emociones por referentes canónicos.

    Pensado para los semas: el llamador obtiene el conjunto de canónicos que
    tienen un sema dado y filtra las emociones cuyo experienciador (o fuente)
    canónico pertenece a ese conjunto. Soporta columnas escalares
    (`experienciador_canonico`) y de lista (`experienciador_canonicos`): en el
    segundo caso, conserva la fila si la intersección con `canonicos` no es vacía.
    Si la columna no existe o el conjunto está vacío, devuelve el DF sin cambios.
    """
    canonicos = set(canonicos)
    if df.empty or not canonicos or col not in df.columns:
        return df
    sample = df[col].dropna()
    if not sample.empty and isinstance(sample.iloc[0], (list, tuple, set)):
        mask = df[col].apply(
            lambda v: bool(canonicos & set(v)) if isinstance(v, (list, tuple, set)) else False
        )
        return df[mask]
    return df[df[col].isin(canonicos)]
