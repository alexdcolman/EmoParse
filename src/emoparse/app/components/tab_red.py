# ══════════════════════════════════════════════════════════════════════════════
#  emoparse.app.components.tab_red
#
#  Tab Red: grafos de interacción persistidos por `emoparse network`.
# ══════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

from pathlib import Path

import streamlit as st

from emoparse.app import data
from emoparse.viz.network_charts import fig_red


def render(db_path: Path) -> None:
    """Renderiza la tab de red."""
    st.markdown("#### 🕸 Red de interacción")
    grafos = data.list_red_grafos(db_path)
    if not grafos:
        st.info(
            "Sin grafos persistidos. Corré `emoparse network --db <run>` "
            "para construirlos (requiere el extra [network])."
        )
        return

    col1, col2 = st.columns([1, 3])
    with col1:
        grafo = st.selectbox("Grafo", grafos)
        df_metricas = data.get_red_metricas(db_path, grafo)
        if not df_metricas.empty and df_metricas["comunidad"].notna().any():
            n_com = int(df_metricas["comunidad"].nunique())
            st.metric("Comunidades", n_com)
        st.metric("Nodos", len(df_metricas))

    df_aristas = data.get_red_aristas(db_path, grafo)
    with col2:
        try:
            st.plotly_chart(
                fig_red(df_aristas, df_metricas),
                use_container_width=True,
            )
        except ImportError:
            st.warning("Instalá el extra [network] para el grafo interactivo.")

    st.markdown("##### Nodos por PageRank")
    if not df_metricas.empty:
        st.dataframe(
            df_metricas[
                ["nodo", "grado_in", "grado_out", "grado_total",
                 "pagerank", "intermediacion", "comunidad"]
            ].head(100),
            use_container_width=True,
            hide_index=True,
        )
