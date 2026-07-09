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
from emoparse.app._knowledge import semas_list
from emoparse.app.components import _emofilter
from emoparse.viz import charts


def render(db_path: Path) -> None:
    """Renderiza la tab de análisis por actor."""
    st.markdown("### Emociones por actor")

    df_em = data_layer.get_emociones_enriched(db_path)
    if df_em.empty:
        st.info("No hay emociones cargadas para este run.")
        return
    if "experienciador_efectivo" not in df_em.columns:
        st.warning("Datos sin columna de experienciador.")
        return

    usar_llm = st.toggle(
        "Usar resultados de la inferencia de los LLMs",
        value=False, key="act_usar_llm",
        help="Muestra el experienciador crudo del LLM en lugar del canónico (revisado en Referentes).",
    )
    actor_col = "experienciador" if usar_llm else "experienciador_efectivo"
    semas_opts = semas_list()
    codigos = sorted(df_em["codigo"].unique().tolist()) if "codigo" in df_em.columns else []

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

        discos = st.multiselect(
            "Discursos", codigos, default=codigos, key="heat_discos",
        ) if codigos else []
        df_heat = df_em[df_em["codigo"].isin(discos)] if discos else df_em
        df_heat = _emofilter.filter_panel(
            df_heat, key="heat_filter", semas_options=semas_opts,
            title="Filtros (semas / referentes / caracterización)",
        )

        fig_heat = charts.heatmap_actor_emocion(
            df_heat,
            top_actores=top_act,
            top_emociones=top_emo,
            normalize=normalize,
            actor_col=actor_col,
        )
        st.plotly_chart(fig_heat, use_container_width=True)

        st.markdown("<hr class='ep-divider'>", unsafe_allow_html=True)
        _render_resumen_actores(df_heat, top_act=top_act, actor_col=actor_col)

    # ── Scatter foria × intensidad ──────────────────────────────────────
    with subtab_scatter:
        if "foria" not in df_em.columns or "intensidad" not in df_em.columns:
            st.info(
                "El scatter foria × intensidad requiere la stage "
                "`characterizer` ejecutada. Corré el pipeline completo."
            )
            return

        codigos_opt = ["(todos)"] + codigos
        col_d, col_e = st.columns([2, 1])
        with col_d:
            codigo_sel = st.selectbox("Discurso", codigos_opt, key="scatter_codigo")
        with col_e:
            top_act_s = st.slider("Top actores", 3, 12, 6, key="scatter_top_act")

        df_sc = df_em if codigo_sel == "(todos)" else df_em[df_em["codigo"] == codigo_sel]
        df_sc = _emofilter.filter_panel(
            df_sc, key="scatter_filter", semas_options=semas_opts,
            title="Filtros (semas / referentes / caracterización)",
        )

        fig_scatter = charts.scatter_foria_intensidad(
            df_sc, codigo=None, top_actores=top_act_s, actor_col=actor_col,
        )
        st.plotly_chart(fig_scatter, use_container_width=True)


def _render_resumen_actores(
    df_em: pd.DataFrame, top_act: int, actor_col: str = "experienciador_efectivo",
) -> None:
    """Renderiza una tabla resumen con los actores más activos."""
    if "tipo_emocion" not in df_em.columns or actor_col not in df_em.columns:
        return
    df_r = df_em[df_em[actor_col].astype(str).str.strip().replace("—", "") != ""]
    if df_r.empty:
        return
    resumen = (
        df_r.groupby(actor_col)
        .agg(
            n_emociones=("tipo_emocion", "count"),
            emociones_distintas=("tipo_emocion", "nunique"),
            emocion_principal=(
                "tipo_emocion",
                lambda x: x.value_counts().index[0] if len(x) else None,
            ),
        )
        .reset_index()
        .rename(columns={actor_col: "experienciador"})
        .sort_values("n_emociones", ascending=False)
        .head(top_act)
    )
    st.markdown(
        f"<p style='font-size:0.78rem;color:#5a5d6e;'>Top {top_act} actores</p>",
        unsafe_allow_html=True,
    )
    st.dataframe(resumen, use_container_width=True, height=280, hide_index=True)
