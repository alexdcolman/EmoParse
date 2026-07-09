# ══════════════════════════════════════════════════════════════════════════════
#  emoparse.app.components.tab_correlacion
#
#  Copresencia de emociones en una misma frase: cuántas veces dos emociones
#  aparecen juntas en la misma unidad, el detalle por pares y las frases con su
#  análisis emocional al seleccionar un par.
# ══════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

import html
from collections import Counter, defaultdict
from itertools import combinations
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from emoparse.app import data as data_layer


def render(db_path: Path) -> None:
    """Renderiza la tab de co-ocurrencia de emociones."""
    st.markdown("### Co-ocurrencia de emociones")
    st.caption("Pares de emociones que caen en una misma frase.")

    df = data_layer.get_emociones_enriched(db_path)
    if df.empty:
        st.info("No hay emociones materializadas para este run.")
        return

    df = df.copy()
    df["emo"] = (
        df["tipo_emocion_canonico"].fillna("").replace("", pd.NA)
        .fillna(df["tipo_emocion"])
    )
    df = df[df["emo"].notna() & (df["emo"].astype(str).str.strip() != "")]
    if df.empty:
        st.info("Sin emociones tipificadas.")
        return

    # Conjunto de emociones distintas por frase.
    por_frase = (
        df.groupby(["codigo", "frase_idx"])["emo"]
        .agg(lambda s: sorted(set(s)))
    )

    pair_counts: Counter = Counter()
    solo_counts: Counter = Counter()
    pair_frases: dict[tuple[str, str], list[tuple[str, int]]] = defaultdict(list)
    n_frases_multi = 0
    for (codigo, frase_idx), emos in por_frase.items():
        for e in emos:
            solo_counts[e] += 1
        if len(emos) >= 2:
            n_frases_multi += 1
            for a, b in combinations(emos, 2):
                pair_counts[(a, b)] += 1
                pair_frases[(a, b)].append((codigo, int(frase_idx)))

    if not pair_counts:
        st.info("No hay frases con dos o más emociones distintas.")
        return

    st.markdown(
        f"<p style='color:#8a8799;font-size:0.85rem;'>"
        f"{n_frases_multi} frases con copresencia · "
        f"{len(pair_counts)} pares distintos.</p>",
        unsafe_allow_html=True,
    )

    # ── Matriz de copresencia (asociación estética) ───────────────────────────
    top = [e for e, _ in solo_counts.most_common(25)]
    idx = sorted(top)
    counts_m = pd.DataFrame(0, index=idx, columns=idx, dtype=int)
    for (a, b), n in pair_counts.items():
        if a in counts_m.index and b in counts_m.columns:
            counts_m.loc[a, b] = n
            counts_m.loc[b, a] = n
    for e in idx:
        counts_m.loc[e, e] = solo_counts[e]

    # Asociación en [0,1]: co-ocurrencia / min(total_a, total_b). Colorea "dónde
    # hay alta correlación" sin que la diagonal (totales) sature la escala.
    assoc = pd.DataFrame(0.0, index=idx, columns=idx)
    for a in idx:
        for b in idx:
            if a == b:
                assoc.loc[a, b] = 1.0
            else:
                denom = min(solo_counts[a], solo_counts[b]) or 1
                assoc.loc[a, b] = pair_counts.get(_pair(a, b), 0) / denom

    st.markdown("#### Matriz (color = asociación · número = frases juntas / diagonal = total)")
    _render_matrix(assoc, counts_m)

    # ── Ranking de pares ──────────────────────────────────────────────────────
    st.markdown("#### Pares más frecuentes")
    pares = pd.DataFrame(
        [(a, b, n) for (a, b), n in pair_counts.items()],
        columns=["emoción A", "emoción B", "frases juntas"],
    ).sort_values("frases juntas", ascending=False).reset_index(drop=True)
    st.dataframe(pares, use_container_width=True, hide_index=True)

    # ── Detalle de un par: frases con su análisis emocional ───────────────────
    st.markdown("#### Frases de un par")
    emos_all = sorted(solo_counts)
    c1, c2, c3 = st.columns([2, 2, 1])
    with c1:
        emo_a = st.selectbox("Emoción A", emos_all, key="corr_emo_a")
    with c2:
        opciones_b = [e for e in emos_all if e != emo_a]
        emo_b = st.selectbox("Emoción B", opciones_b, key="corr_emo_b") if opciones_b else None
    with c3:
        ver = st.button("Ver frases", key="corr_ver", use_container_width=True)

    if ver and emo_b:
        frases = sorted(set(pair_frases.get(_pair(emo_a, emo_b), [])))
        if not frases:
            st.info(f"No hay frases donde coexistan **{emo_a}** y **{emo_b}**.")
        else:
            st.caption(f"{len(frases)} frase(s) con copresencia de «{emo_a}» y «{emo_b}».")
            for codigo, frase_idx in frases:
                _render_frase_analisis(df, codigo, frase_idx)


def _pair(a: str, b: str) -> tuple[str, str]:
    return (a, b) if a <= b else (b, a)


def _render_matrix(assoc: pd.DataFrame, counts_m: pd.DataFrame) -> None:
    """Heatmap estético de la matriz de asociación (texto = frases juntas)."""
    text = counts_m.map(lambda v: str(int(v)))
    fig = go.Figure(go.Heatmap(
        z=assoc.values, x=assoc.columns.tolist(), y=assoc.index.tolist(),
        text=text.values.tolist(), texttemplate="%{text}",
        textfont=dict(size=9),
        colorscale="Magma", zmin=0, zmax=1, showscale=True,
        colorbar=dict(title="asociación", tickfont=dict(size=9)),
        hovertemplate="<b>%{y}</b> × <b>%{x}</b><br>frases juntas: %{text}"
                      "<br>asociación: %{z:.0%}<extra></extra>",
    ))
    fig.update_layout(
        paper_bgcolor="#0e0f13", plot_bgcolor="#16181f",
        font=dict(family="DM Mono, monospace", color="#8a8799", size=10),
        height=max(360, len(assoc) * 26 + 140),
        margin=dict(l=10, r=10, t=10, b=10),
        xaxis=dict(tickangle=-45, gridcolor="#252730"),
        yaxis=dict(gridcolor="#252730", autorange="reversed"),
    )
    st.plotly_chart(fig, use_container_width=True)


#: Elementos del análisis actancial mostrados por emoción.
_ACTANTES = (
    ("mediador", "mediador"),
    ("verificador_normativo", "verif. normativo"),
    ("verificador_observacional", "verif. observacional"),
    ("operador_modificacion", "operador de modificación"),
    ("polaridad", "polaridad"),
)


def _render_frase_analisis(df: pd.DataFrame, codigo: str, frase_idx: int) -> None:
    """Frase con sus emociones: experienciador y fuente canónicos + actantes."""
    sub = df[(df["codigo"] == codigo) & (df["frase_idx"] == frase_idx)]
    if sub.empty:
        return
    frase = str(sub["frase"].iloc[0]) if "frase" in sub.columns else ""
    with st.container(border=True):
        st.markdown(
            f"<span style='font-family:DM Mono,monospace;font-size:0.72rem;"
            f"color:#5a5d6e;'>{html.escape(str(codigo))} · u{frase_idx}</span>"
            f"<div style='color:#e8e4dc;font-size:0.9rem;line-height:1.6;"
            f"margin:0.15rem 0;'>{html.escape(frase)}</div>",
            unsafe_allow_html=True,
        )
        for _, row in sub.sort_values("emocion_idx").iterrows():
            emo = html.escape(str(row.get("emo", "") or "—"))
            exp = html.escape(str(row.get("experienciador_efectivo", "") or "—"))
            fte = html.escape(str(row.get("fuente_efectiva", "") or "—"))
            extras = ""
            for col, label in _ACTANTES:
                val = str(row.get(col, "") or "").strip()
                if val:
                    extras += (
                        f"<span style='color:#5a5d6e;'> · {label}:</span> "
                        f"<span style='color:#c2bdb4;'>{html.escape(val)}</span>"
                    )
            st.markdown(
                f"<div style='font-size:0.78rem;line-height:1.7;margin-top:0.2rem;'>"
                f"<span style='color:#b08ad0;font-weight:600;'>{emo}</span>"
                f"<span style='color:#5a5d6e;'> · exp:</span> "
                f"<span style='color:#7c9ec8;'>{exp}</span>"
                f"<span style='color:#5a5d6e;'> · fuente:</span> "
                f"<span style='color:#6ec89a;'>{fte}</span>{extras}</div>",
                unsafe_allow_html=True,
            )
