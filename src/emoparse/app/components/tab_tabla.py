# ══════════════════════════════════════════════════════════════════════════════
#  emoparse.app.components.tab_tabla
#
#  Tab de exploración tabular dentro del dashboard Streamlit.
#
#  Permite visualizar datos del run en distintos niveles de
#  granularidad, aplicar filtros por columna y exportar resultados
#  en formato CSV.
# ══════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

from pathlib import Path

import pandas as pd
import streamlit as st

from emoparse.app import data as data_layer


#: Niveles de granularidad disponibles para la vista tabular.
_LEVELS = ("discursos", "frases", "emociones")


def render(db_path: Path) -> None:
    """Renderiza la tab de exploración tabular.

    Permite seleccionar el nivel de datos, aplicar filtros y exportar
    el resultado filtrado como CSV.
    """
    st.markdown("### Tabla de datos")

    col_lvl, _ = st.columns([1, 3])
    with col_lvl:
        level = st.selectbox("Nivel", _LEVELS, key="tabla_level")

    df = _load(db_path, level)
    if df.empty:
        st.info(f"Sin datos en el nivel `{level}`.")
        return

    df_filtered = _apply_filters(df, level)

    st.markdown(
        f"<p style='font-size:0.8rem;color:#5a5d6e;'>{len(df_filtered)} filas</p>",
        unsafe_allow_html=True,
    )
    st.dataframe(df_filtered, use_container_width=True, height=480)

    st.download_button(
        f"⬇ Exportar {level}.csv",
        data=_df_to_csv_bytes(df_filtered),
        file_name=f"emoparse_{level}.csv",
        mime="text/csv",
        key=f"dl_tabla_{level}",
    )


def _load(db_path: Path, level: str) -> pd.DataFrame:
    """Carga el DataFrame correspondiente al nivel seleccionado."""
    if level == "discursos":
        return data_layer.get_discursos(db_path)
    if level == "frases":
        return data_layer.get_frases(db_path)
    if level == "emociones":
        return data_layer.get_emociones(db_path)
    return pd.DataFrame()


def _apply_filters(df: pd.DataFrame, level: str) -> pd.DataFrame:
    """Aplica filtros dinámicos según el nivel seleccionado.

    Solo se muestran filtros para columnas existentes y con una
    cardinalidad razonable (< 200 valores únicos), para evitar
    selectores poco útiles o difíciles de navegar.
    """
    cols = st.columns(3)
    out = df

    candidatos = {
        "discursos": ["codigo", "metadata__tipo_discurso", "summarizer__status"],
        "frases":    ["codigo"],
        "emociones": ["codigo", "tipo_emocion", "experienciador", "foria", "modo_existencia"],
    }.get(level, [])

    for i, col_name in enumerate(candidatos):
        if col_name not in df.columns:
            continue
        unique_vals = df[col_name].dropna().unique().tolist()
        if not unique_vals or len(unique_vals) > 200:
            continue
        with cols[i % 3]:
            opts = ["(todos)"] + sorted(map(str, unique_vals))
            sel = st.selectbox(col_name, opts, key=f"filter_{level}_{col_name}")
            if sel != "(todos)":
                out = out[out[col_name].astype(str) == sel]
    return out


def _df_to_csv_bytes(df: pd.DataFrame) -> bytes:
    """Exporta CSV en UTF-8 con BOM para compatibilidad con Excel."""
    return df.to_csv(index=False).encode("utf-8-sig")
