# ══════════════════════════════════════════════════════════════════════════════
#  emoparse.app.components.tab_correlacion
#
#  Copresencia de emociones en una misma frase: cuántas veces dos emociones
#  aparecen juntas en la misma unidad, y el detalle por pares.
# ══════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

from collections import Counter
from itertools import combinations
from pathlib import Path

import pandas as pd
import streamlit as st

from emoparse.app import data as data_layer


def render(db_path: Path) -> None:
    """Renderiza la tab de co-ocurrencia de emociones."""
    st.markdown("### Co-ocurrencia de emociones")
    st.caption("Pares de emociones que caen en una misma frase.")

    df = data_layer.get_emociones(db_path)
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
    n_frases_multi = 0
    for emos in por_frase:
        for e in emos:
            solo_counts[e] += 1
        if len(emos) >= 2:
            n_frases_multi += 1
            for a, b in combinations(emos, 2):
                pair_counts[(a, b)] += 1

    if not pair_counts:
        st.info("No hay frases con dos o más emociones distintas.")
        return

    st.markdown(
        f"<p style='color:#8a8799;font-size:0.85rem;'>"
        f"{n_frases_multi} frases con copresencia · "
        f"{len(pair_counts)} pares distintos.</p>",
        unsafe_allow_html=True,
    )

    # ── Matriz de copresencia ─────────────────────────────────────────────────
    top = [e for e, _ in solo_counts.most_common(25)]
    idx = sorted(top)
    matrix = pd.DataFrame(0, index=idx, columns=idx, dtype=int)
    for (a, b), n in pair_counts.items():
        if a in matrix.index and b in matrix.columns:
            matrix.loc[a, b] = n
            matrix.loc[b, a] = n
    for e in idx:
        matrix.loc[e, e] = solo_counts[e]

    st.markdown("#### Matriz (diagonal = total de la emoción)")
    try:
        styled = matrix.style.background_gradient(cmap="magma").format(precision=0)
        st.dataframe(styled, use_container_width=True)
    except Exception:
        st.dataframe(matrix, use_container_width=True)

    # ── Ranking de pares ──────────────────────────────────────────────────────
    st.markdown("#### Pares más frecuentes")
    pares = pd.DataFrame(
        [(a, b, n) for (a, b), n in pair_counts.items()],
        columns=["emoción A", "emoción B", "frases juntas"],
    ).sort_values("frases juntas", ascending=False).reset_index(drop=True)
    st.dataframe(pares, use_container_width=True, hide_index=True)
