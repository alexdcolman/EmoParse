# ══════════════════════════════════════════════════════════════════════════════
#  emoparse.app.components.tab_actores
#
#  Tab de análisis por actor: heatmap actor×emoción y scatter de foria.
# ══════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

from pathlib import Path

import pandas as pd
import streamlit as st

from emoparse.app import data as data_layer
from emoparse.viz import charts


def render(db_path: Path) -> None:
    """Renderiza la tab de análisis por actor."""
    st.markdown("### Emociones por actor")

    df_em = data_layer.get_emociones(db_path)
    if df_em.empty:
        st.info("No hay emociones cargadas para este run.")
        return
    if "experienciador" not in df_em.columns:
        st.warning("Datos sin columna `experienciador`.")
        return

    subtab_heat, subtab_scatter = st.tabs(["🗂 Heatmap actor×emoción", "⊕ Scatter foria"])

    # ── Heatmap ─────────────────────────────────────────────────────────
    with subtab_heat:
        col_a, col_b, col_c = st.columns([1, 1, 1])
        with col_a:
            top_act = st.slider("Top actores", 3, 20, 10, key="heat_top_act")
        with col_b:
            top_emo = st.slider("Top emociones", 3, 15, 8, key="heat_top_emo")
        with col_c:
            normalize = st.toggle("Normalizar (proporción por actor)",
                                  value=True, key="heat_norm")

        fig_heat = charts.heatmap_actor_emocion(
            df_em,
            top_actores=top_act,
            top_emociones=top_emo,
            normalize=normalize,
        )
        st.plotly_chart(fig_heat, use_container_width=True)

        st.markdown("<hr class='ep-divider'>", unsafe_allow_html=True)
        _render_resumen_actores(df_em, top_act=top_act)

    # ── Scatter foria × intensidad ──────────────────────────────────────
    with subtab_scatter:
        if "foria" not in df_em.columns or "intensidad" not in df_em.columns:
            st.info(
                "El scatter foria × intensidad requiere la stage "
                "`characterizer` ejecutada. Corré el pipeline completo."
            )
            return

        codigos = ["(todos)"] + sorted(df_em["codigo"].unique().tolist())
        col_d, col_e = st.columns([2, 1])
        with col_d:
            codigo_sel = st.selectbox("Discurso", codigos, key="scatter_codigo")
        with col_e:
            top_act_s = st.slider("Top actores", 3, 12, 6, key="scatter_top_act")

        codigo_arg = None if codigo_sel == "(todos)" else codigo_sel
        fig_scatter = charts.scatter_foria_intensidad(
            df_em, codigo=codigo_arg, top_actores=top_act_s,
        )
        st.plotly_chart(fig_scatter, use_container_width=True)


def _render_resumen_actores(df_em: pd.DataFrame, top_act: int) -> None:
    """Renderiza una tabla resumen con los actores más activos."""
    if "tipo_emocion" not in df_em.columns:
        return
    resumen = (
        df_em.groupby("experienciador")
        .agg(
            n_emociones=("tipo_emocion", "count"),
            emociones_distintas=("tipo_emocion", "nunique"),
            emocion_principal=(
                "tipo_emocion",
                lambda x: x.value_counts().index[0] if len(x) else None,
            ),
        )
        .reset_index()
        .sort_values("n_emociones", ascending=False)
        .head(top_act)
    )
    st.markdown(
        f"<p style='font-size:0.78rem;color:#5a5d6e;'>Top {top_act} actores</p>",
        unsafe_allow_html=True,
    )
    st.dataframe(resumen, use_container_width=True, height=280, hide_index=True)
