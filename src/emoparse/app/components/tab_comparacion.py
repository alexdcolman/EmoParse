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
                "<p style='font-size:0.78rem;color:#c8a96e;'>"
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
            emos = (
                df_em["tipo_emocion"].value_counts().head(15).index.tolist()
                if "tipo_emocion" in df_em.columns else []
            )
            opt = ["(emoción dominante por discurso)"] + emos
            sel = st.selectbox("Ver", opt, key="tl_emo")
            emocion = None if sel.startswith("(") else sel
            # La timeline usa todo el corpus del run y no solo los discursos
            # seleccionados, ya que representa una vista temporal global.
            fig = charts.timeline_corpus(df_em, emocion=emocion)
            st.plotly_chart(fig, use_container_width=True)
