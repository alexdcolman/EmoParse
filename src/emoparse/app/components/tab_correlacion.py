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
from emoparse.app import styles
from emoparse.viz.theme import ACCENT, SURFACE, base_layout

#: Etiquetas y descripciones de la unidad de copresencia.
_UNIDADES: dict[str, tuple[str, str]] = {
    "frase": ("Por frase", "Pares de emociones que caen en una misma frase."),
    "hilo": ("Por hilo", "Pares de emociones que coexisten en una misma conversación (hilo)."),
    "hashtag": (
        "Por #hashtag",
        "Pares de emociones que coexisten en los posts de un mismo hashtag.",
    ),
}


def render(db_path: Path) -> None:
    """Renderiza la tab de co-ocurrencia de emociones."""
    st.markdown("### Co-ocurrencia de emociones")

    unidad = "frase"
    corpus_posts = data_layer.has_posts(db_path)
    if corpus_posts:
        unidad = st.radio(
            "Unidad de copresencia",
            list(_UNIDADES),
            horizontal=True,
            key="corr_unidad",
            format_func=lambda u: _UNIDADES[u][0],
        )
    st.caption(_UNIDADES[unidad][1])

    df = data_layer.get_emociones_enriched(db_path)
    if df.empty:
        st.info("No hay emociones materializadas para este run.")
        return

    df = df.copy()
    df["emo"] = df["tipo_emocion_canonico"].fillna("").replace("", pd.NA).fillna(df["tipo_emocion"])
    df = df[df["emo"].notna() & (df["emo"].astype(str).str.strip() != "")]
    if df.empty:
        st.info("Sin emociones tipificadas.")
        return

    # Grupo de copresencia → emoción → unidades (codigo, frase_idx).
    grupos = _agrupar(db_path, df, unidad)
    if not grupos:
        st.info("Sin unidades de copresencia para este corpus.")
        return

    if unidad in ("hilo", "hashtag"):
        etiqueta = "Hilos" if unidad == "hilo" else "Hashtags"
        sel_grupos = st.multiselect(
            f"{etiqueta} a incluir (vacío = todos)",
            sorted(grupos),
            key=f"corr_grupos_{unidad}",
        )
        if sel_grupos:
            grupos = {k: grupos[k] for k in sel_grupos if k in grupos}
        if not grupos:
            st.info("Sin grupos seleccionados.")
            return

    pair_counts: Counter = Counter()
    solo_counts: Counter = Counter()
    pair_frases: dict[tuple[str, str], list[tuple[str, int]]] = defaultdict(list)
    n_multi = 0
    for emo_units in grupos.values():
        emos = sorted(emo_units)
        for e in emos:
            solo_counts[e] += 1
        if len(emos) >= 2:
            n_multi += 1
            for a, b in combinations(emos, 2):
                pair_counts[(a, b)] += 1
                pair_frases[(a, b)].extend(sorted(emo_units[a] | emo_units[b]))

    unidad_n = {"frase": "frases", "hilo": "hilos", "hashtag": "hashtags"}[unidad]
    if not pair_counts:
        st.info(f"No hay {unidad_n} con dos o más emociones distintas.")
        return

    st.markdown(
        f"<p style='color:var(--text-dim);font-size:0.85rem;'>"
        f"{n_multi} {unidad_n} con copresencia · "
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

    st.markdown(f"#### Matriz (color = asociación · número = {unidad_n} juntas / diagonal = total)")
    _render_matrix(assoc, counts_m)

    # ── Ranking de pares ──────────────────────────────────────────────────────
    st.markdown("#### Pares más frecuentes")
    pares = (
        pd.DataFrame(
            [(a, b, n) for (a, b), n in pair_counts.items()],
            columns=["emoción A", "emoción B", f"{unidad_n} juntas"],
        )
        .sort_values(f"{unidad_n} juntas", ascending=False)
        .reset_index(drop=True)
    )
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
            tope = 40
            st.caption(
                f"{len(frases)} frase(s) del par «{emo_a}» × «{emo_b}»"
                + (f" (se muestran las primeras {tope})." if len(frases) > tope else ".")
            )
            for codigo, frase_idx in frases[:tope]:
                _render_frase_analisis(df, codigo, frase_idx)


def _agrupar(
    db_path: Path, df: pd.DataFrame, unidad: str
) -> dict[str, dict[str, set[tuple[str, int]]]]:
    """Grupo de copresencia → emoción → unidades (codigo, frase_idx).

    'frase' agrupa por (codigo, frase_idx); 'hilo' por conversación (los
    posts sin hilo forman su propio grupo); 'hashtag' por hashtag (un post
    con dos hashtags integra ambos grupos).
    """
    grupos: dict[str, dict[str, set[tuple[str, int]]]] = defaultdict(lambda: defaultdict(set))

    def _sumar(clave: str, row) -> None:
        grupos[clave][str(row.emo)].add((str(row.codigo), int(row.frase_idx)))

    if unidad == "frase":
        for row in df.itertuples(index=False):
            _sumar(f"{row.codigo}·u{row.frase_idx}", row)
    elif unidad == "hilo":
        ctx = data_layer.get_post_contexto(db_path)
        conv = dict(zip(ctx["codigo"].astype(str), ctx["conversacion_id"])) if not ctx.empty else {}
        for row in df.itertuples(index=False):
            clave = conv.get(str(row.codigo))
            if (
                clave is None
                or (isinstance(clave, float) and pd.isna(clave))
                or not str(clave).strip()
            ):
                clave = str(row.codigo)
            _sumar(str(clave), row)
    elif unidad == "hashtag":
        pares = data_layer.get_post_hashtags(db_path)
        if pares.empty:
            return {}
        tags_por_post: dict[str, list[str]] = defaultdict(list)
        for r in pares.itertuples(index=False):
            tags_por_post[str(r.codigo)].append(str(r.hashtag))
        for row in df.itertuples(index=False):
            for tag in tags_por_post.get(str(row.codigo), []):
                _sumar(f"#{tag}", row)
    return {k: dict(v) for k, v in grupos.items()}


def _pair(a: str, b: str) -> tuple[str, str]:
    return (a, b) if a <= b else (b, a)


def _render_matrix(assoc: pd.DataFrame, counts_m: pd.DataFrame) -> None:
    """Heatmap estético de la matriz de asociación (texto = frases juntas)."""
    text = counts_m.map(lambda v: str(int(v)))
    fig = go.Figure(
        go.Heatmap(
            z=assoc.values,
            x=assoc.columns.tolist(),
            y=assoc.index.tolist(),
            text=text.values.tolist(),
            texttemplate="%{text}",
            textfont=dict(size=9),
            # La asociación es intensidad, no foria: escala monocroma sobre el
            # acento, para no sugerir una lectura fórica donde no la hay. Los
            # colores van literales porque plotly no resuelve variables CSS: el
            # tema los expone como constantes para eso.
            colorscale=[
                [0.0, SURFACE],
                [0.35, "#3d3a30"],
                [0.7, "#8a7548"],
                [1.0, ACCENT],
            ],
            zmin=0,
            zmax=1,
            showscale=True,
            colorbar=dict(title="asociación", tickfont=dict(size=9)),
            hovertemplate="<b>%{y}</b> × <b>%{x}</b><br>frases juntas: %{text}"
            "<br>asociación: %{z:.0%}<extra></extra>",
        )
    )
    fig.update_layout(
        **base_layout(
            height=max(360, len(assoc) * 26 + 140),
            margin=dict(l=10, r=10, t=10, b=10),
            xaxis=dict(tickangle=-45),
            yaxis=dict(autorange="reversed"),
        )
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
            f"color:var(--dim);'>{html.escape(str(codigo))} · u{frase_idx}</span>"
            f"<div style='color:var(--text);font-size:0.9rem;line-height:1.6;"
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
                        f"<span style='color:var(--dim);'> · {label}:</span> "
                        f"<span style='color:var(--text-soft);'>"
                        f"{html.escape(val)}</span>"
                    )
            st.markdown(
                f"<div style='font-size:0.78rem;line-height:1.7;margin-top:0.2rem;'>"
                f"<span style='color:{styles.var('rol-emocion')};"
                f"font-weight:600;'>{emo}</span>"
                f"<span style='color:var(--dim);'> · exp:</span> "
                f"<span style='color:{styles.var('rol-experienciador')};'>{exp}</span>"
                f"<span style='color:var(--dim);'> · fuente:</span> "
                f"<span style='color:{styles.var('rol-fuente')};'>{fte}</span>"
                f"{extras}</div>",
                unsafe_allow_html=True,
            )
