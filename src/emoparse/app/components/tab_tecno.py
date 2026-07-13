# ══════════════════════════════════════════════════════════════════════════════
#  emoparse.app.components.tab_tecno
#
#  Tab Tecno: distribución de tecnolingüísticos y afecto de emojis.
# ══════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

from pathlib import Path

import streamlit as st

from emoparse.app import data


def render(db_path: Path) -> None:
    """Renderiza la tab de tecnolingüísticos."""
    st.markdown("#### ✳ Tecnolingüísticos")
    df = data.get_tecno_resumen(db_path)
    if df.empty:
        st.info(
            "Sin tecno-entidades: corré la stage `technoparse` "
            "(el género tuit la habilita por defecto)."
        )
        return

    col1, col2 = st.columns(2)
    with col1:
        st.markdown("##### Por tipo")
        st.dataframe(
            df.groupby("tipo", as_index=False)
            .agg(entidades=("n", "sum"), distintos=("valor_norm", "count"))
            .sort_values("entidades", ascending=False),
            use_container_width=True,
            hide_index=True,
        )
    with col2:
        tipo = st.selectbox("Detalle de tipo", sorted(df["tipo"].unique()))
        st.dataframe(
            df[df["tipo"] == tipo].head(60),
            use_container_width=True,
            hide_index=True,
        )

    st.markdown("##### Afecto de emojis")
    df_emojis = data.get_emojis_con_afecto(db_path)
    if df_emojis.empty:
        return
    resueltos = df_emojis[df_emojis["candidato"].notna()]
    st.caption(
        f"{len(resueltos)} de {len(df_emojis)} usos con afecto resuelto "
        f"({int((resueltos['origin'] == 'lexico').sum())} por léxico, "
        f"{int((resueltos['origin'] == 'llm').sum())} por LLM en contexto)."
    )
    if not resueltos.empty:
        st.dataframe(
            resueltos.groupby(["emoji", "candidato", "foria"], as_index=False)
            .size()
            .rename(columns={"size": "usos"})
            .sort_values("usos", ascending=False)
            .head(60),
            use_container_width=True,
            hide_index=True,
        )
