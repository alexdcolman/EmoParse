# ══════════════════════════════════════════════════════════════════════════════
#  emoparse.app.components.tab_hashtags
#
#  Tab Hashtags: ranking, caracterización semiótica y drill-down a posts.
# ══════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

from pathlib import Path

import streamlit as st

from emoparse.app import data
from emoparse.viz.network_charts import fig_hashtags_top


def render(db_path: Path) -> None:
    """Renderiza la tab de hashtags."""
    st.markdown("#### #️⃣ Hashtags")
    df = data.get_hashtags_analizados(db_path)
    if df.empty:
        df_tecno = data.get_tecno_resumen(db_path)
        tags = df_tecno[df_tecno["tipo"] == "hashtag"] if not df_tecno.empty else df_tecno
        if tags is None or tags.empty:
            st.info("El corpus no contiene hashtags.")
            return
        st.info(
            "Hashtags sin caracterizar: corré la stage `hashtag_semiotics` "
            "(requiere modelo asignado en el config)."
        )
        st.dataframe(tags.head(50), use_container_width=True, hide_index=True)
        return

    st.plotly_chart(fig_hashtags_top(df), use_container_width=True)

    analizados = df[df["funcion"].notna()]
    if analizados.empty:
        return
    st.markdown("##### Caracterización semiótica")
    st.dataframe(
        analizados[
            ["valor_norm", "n_usos", "funcion", "foria_entorno",
             "acoplamiento", "justificacion"]
        ],
        use_container_width=True,
        hide_index=True,
    )

    seleccion = st.selectbox(
        "Ver posts de un hashtag",
        ["(elegir)"] + analizados["valor_norm"].tolist(),
    )
    if seleccion != "(elegir)":
        posts = data.get_posts_con_hashtag(db_path, seleccion)
        for _, p in posts.iterrows():
            st.markdown(
                f"- **@{p['autor_handle']}** ({p['fecha'] or 's/f'}): "
                f"{p['texto']}"
            )
