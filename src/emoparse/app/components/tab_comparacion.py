# ══════════════════════════════════════════════════════════════════════════════
#  emoparse.app.components.tab_comparacion
#
#  Tab de comparación entre discursos dentro del dashboard Streamlit.
#
#  Permite seleccionar múltiples discursos del run activo y explorar
#  visualizaciones comparativas de perfil emocional, radar, trayectoria
#  y distribución temporal.
# ══════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

from pathlib import Path

import streamlit as st

from emoparse.app import data as data_layer
from emoparse.viz import charts


def render(db_path: Path) -> None:
    """Renderiza la tab de comparación entre discursos.

    Carga las emociones del run activo, permite seleccionar discursos
    y muestra distintas visualizaciones comparativas dentro de sub-tabs.
    """
    st.markdown("### Comparación entre discursos")

    df_em = data_layer.get_emociones_enriched(db_path)
    if df_em.empty or "codigo" not in df_em.columns:
        st.info("No hay emociones cargadas para este run.")
        return

    corpus_posts = data_layer.has_posts(db_path)
    df_raw = df_em
    if corpus_posts:
        # En posts, los selectores y gráficos muestran el título del input;
        # `df_raw` conserva los códigos reales para las agrupaciones por
        # hilo/hashtag.
        labels = data_layer.codigo_labels(db_path)
        df_em = df_em.copy()
        df_em["codigo"] = df_em["codigo"].map(lambda c: labels.get(c, c))

    codigos = sorted(df_em["codigo"].unique().tolist())
    if len(codigos) < 2:
        st.info("Se necesitan al menos 2 discursos para comparar.")
        return

    seleccionados = st.multiselect(
        "Discursos a comparar",
        codigos,
        default=codigos[: min(4, len(codigos))],
        key="comp_sel",
    )
    if not seleccionados:
        st.info("Seleccioná al menos un discurso.")
        return

    df_sel = df_em[df_em["codigo"].isin(seleccionados)]

    subtab_perfil, subtab_radar, subtab_traj, subtab_timeline = st.tabs([
        "Perfil apilado", "Radar", "Trayectoria", "Timeline",
    ])

    with subtab_perfil:
        normalize = st.toggle("Normalizar (proporciones)", value=True, key="comp_norm")
        fig = charts.perfil_comparado(df_em, seleccionados, normalize=normalize)
        st.plotly_chart(fig, use_container_width=True)

    with subtab_radar:
        if len(seleccionados) > 5:
            st.markdown(
                "<p style='font-size:0.78rem;color:var(--accent);'>"
                "Con más de 5 discursos el radar pierde legibilidad. "
                "Considerá reducir la selección.</p>",
                unsafe_allow_html=True,
            )
        emociones_top = (
            df_em["tipo_emocion"].value_counts().head(12).index.tolist()
            if "tipo_emocion" in df_em.columns else []
        )
        emo_ref = None
        if emociones_top:
            emo_ref = st.multiselect(
                "Emociones de referencia",
                emociones_top,
                default=emociones_top[: min(8, len(emociones_top))],
                key="radar_emos",
            )
        fig = charts.radar_discurso(df_em, seleccionados, emociones_ref=emo_ref or None)
        st.plotly_chart(fig, use_container_width=True)

    with subtab_traj:
        if corpus_posts:
            # La trayectoria por post no tiene sentido en tuits (un post no
            # tiene segmentos): se recorre la conversación pública.
            _render_trayectoria_conversaciones(db_path, df_raw)
        else:
            n_bins = st.slider("Segmentos", 5, 20, 10, key="traj_bins")
            fig = charts.trayectoria_comparada(df_em, seleccionados, n_bins=n_bins)
            st.plotly_chart(fig, use_container_width=True)

    with subtab_timeline:
        if "discurso__fecha" not in df_em.columns:
            st.info(
                "Los discursos no tienen fecha en el input. La timeline "
                "requiere la columna `fecha` en el CSV original."
            )
        else:
            df_tl = df_raw
            if corpus_posts:
                df_tl = _filtrar_timeline(db_path, df_raw)
            emos = (
                df_tl["tipo_emocion"].value_counts().head(15).index.tolist()
                if "tipo_emocion" in df_tl.columns else []
            )
            opt = ["(emoción dominante por discurso)"] + emos
            sel = st.selectbox("Ver", opt, key="tl_emo")
            emocion = None if sel.startswith("(") else sel
            # La timeline usa todo el corpus del run (o el recorte por
            # hashtag/hilo elegido) y no solo los discursos seleccionados:
            # representa una vista temporal global.
            fig = charts.timeline_corpus(df_tl, emocion=emocion)
            st.plotly_chart(fig, use_container_width=True)


# ══════════════════════════════════════════════════════════════════════════════
#  Helpers para corpus de posts
# ══════════════════════════════════════════════════════════════════════════════

def _render_trayectoria_conversaciones(db_path: Path, df_raw) -> None:
    """Trayectoria de la emoción dominante recorriendo conversaciones públicas."""
    modos = []
    if not data_layer.get_post_hashtags(db_path).empty:
        modos.append("hashtag")
    ctx = data_layer.get_post_contexto(db_path)
    if not ctx.empty and ctx["conversacion_id"].notna().any():
        modos.append("hilo")
    if not modos:
        st.info("El corpus no tiene hashtags ni hilos para recorrer.")
        return
    modo = st.radio(
        "Recorrer", modos, horizontal=True, key="traj_modo",
        format_func={"hashtag": "Por #hashtag", "hilo": "Por hilo"}.get,
    )
    df_g = data_layer.agrupar_por_conversacion(db_path, df_raw, modo)
    if df_g.empty:
        st.info("Sin conversaciones para esa unidad.")
        return
    grupos = sorted(df_g["codigo"].unique().tolist())
    sel = st.multiselect(
        "Conversaciones", grupos, default=grupos[: min(4, len(grupos))],
        key=f"traj_grupos_{modo}",
    )
    if not sel:
        st.info("Seleccioná al menos una conversación.")
        return
    n_bins = st.slider("Segmentos", 5, 20, 10, key="traj_bins_conv")
    fig = charts.trayectoria_comparada(df_g, sel, n_bins=n_bins)
    st.plotly_chart(fig, use_container_width=True)


def _filtrar_timeline(db_path: Path, df_raw):
    """Recorta las emociones del corpus a un hashtag o un hilo elegido."""
    opciones = ["(todo el corpus)"]
    pares = data_layer.get_post_hashtags(db_path)
    tags = sorted(pares["hashtag"].unique().tolist()) if not pares.empty else []
    opciones += [f"#{t}" for t in tags]
    ctx = data_layer.get_post_contexto(db_path)
    hilos = (
        sorted(ctx[ctx["conversacion_id"].notna()]["conversacion_id"]
               .astype(str).unique().tolist())
        if not ctx.empty else []
    )
    opciones += [f"hilo: {h}" for h in hilos]
    sel = st.selectbox("Filtrar timeline por", opciones, key="tl_filtro")
    if sel.startswith("#"):
        codigos = pares[pares["hashtag"] == sel[1:]]["codigo"].astype(str)
        return df_raw[df_raw["codigo"].astype(str).isin(set(codigos))]
    if sel.startswith("hilo: "):
        conv = sel.removeprefix("hilo: ")
        codigos = ctx[ctx["conversacion_id"].astype(str) == conv]["codigo"].astype(str)
        return df_raw[df_raw["codigo"].astype(str).isin(set(codigos))]
    return df_raw
