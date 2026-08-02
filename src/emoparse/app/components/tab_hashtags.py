# ══════════════════════════════════════════════════════════════════════════════
#  emoparse.app.components.tab_hashtags
#
#  Tab Hashtags: ranking, caracterización semiótica por uso y drill-down a
#  los posts con el funcionamiento del hashtag en cada uno.
# ══════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

import html
from pathlib import Path

import streamlit as st

from emoparse.app import data
from emoparse.viz import foria as foria_viz
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
    st.markdown("##### Caracterización semiótica (derivada de los usos)")
    st.caption(
        "Un hashtag no funciona siempre igual: la función se analiza en cada "
        "post. La columna `funcion` es la dominante ('mixto' si no hay "
        "dominante clara) y `distribucion` muestra todas las funciones "
        "identificadas con su frecuencia."
    )
    st.dataframe(
        analizados[
            [
                "valor_norm",
                "n_usos",
                "funcion",
                "distribucion",
                "foria_entorno",
                "acoplamiento",
                "justificacion",
            ]
        ],
        use_container_width=True,
        hide_index=True,
        column_config={
            "valor_norm": st.column_config.TextColumn("hashtag"),
            # La barra hace comparable el ranking de un vistazo; el número
            # solo obliga a compararlos de a pares.
            "n_usos": st.column_config.ProgressColumn(
                "usos",
                format="%d",
                min_value=0,
                max_value=int(analizados["n_usos"].max() or 1),
            ),
            "foria_entorno": st.column_config.TextColumn("foria"),
        },
    )

    seleccion = st.selectbox(
        "Ver usos de un hashtag",
        ["(elegir)"] + analizados["valor_norm"].tolist(),
    )
    if seleccion == "(elegir)":
        return

    usos = data.get_usos_hashtag(db_path, seleccion)
    if usos.empty:
        st.info("Sin usos registrados para ese hashtag.")
        return

    funciones = sorted(f for f in usos["funcion"].dropna().unique() if str(f).strip())
    filtro = st.multiselect("Filtrar por función del uso", funciones, key=f"hash_ffn_{seleccion}")
    sub = usos[usos["funcion"].isin(filtro)] if filtro else usos
    st.caption(f"{len(sub)} uso(s) de #{seleccion}.")
    for _, u in sub.head(60).iterrows():
        _render_uso(u)


def _render_uso(u) -> None:
    """Un uso del hashtag: post + función, foria y acoplamiento de ese uso."""
    foria = str(u.get("foria_entorno") or "")
    color = foria_viz.color(foria)
    funcion = str(u.get("funcion") or "")
    encabezado = f"@{u['autor_handle']}" if u.get("autor_handle") else str(u["codigo"])
    fecha = str(u.get("fecha") or "s/f")
    st.markdown(
        f"<div style='border-left:3px solid {color};padding:0.35rem 0.7rem;"
        f"margin-bottom:0.4rem;background:var(--surface-sunken);border-radius:0 6px 6px 0;"
        f"font-size:0.84rem;line-height:1.55;'>"
        f"<span style='color:var(--text-dim);font-size:0.78rem;'>"
        f"{html.escape(encabezado)} · {html.escape(fecha)}"
        + (
            f" · <b style='color:var(--accent2);'>{html.escape(funcion)}</b>"
            if funcion
            else " · (uso sin analizar)"
        )
        + (f" · foria: {html.escape(foria)}" if foria else "")
        + "</span><br>"
        f"<span style='color:var(--text-soft);'>{html.escape(str(u.get('texto') or ''))}</span>"
        + (
            f"<br><span style='color:var(--dim);font-size:0.76rem;'>acoplamiento: "
            f"{html.escape(str(u['acoplamiento']))}</span>"
            if u.get("acoplamiento")
            else ""
        )
        + (
            f"<br><span style='color:var(--dim);font-style:italic;font-size:0.74rem;'>"
            f"{html.escape(str(u['justificacion']))}</span>"
            if u.get("justificacion")
            else ""
        )
        + "</div>",
        unsafe_allow_html=True,
    )
