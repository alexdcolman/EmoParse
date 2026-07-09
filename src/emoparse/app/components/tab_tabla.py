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

#: Columnas del nivel emociones, en orden de lectura. Se muestran las que existan.
_EMO_COLS = (
    "codigo", "frase_idx", "emocion_idx",
    "tipo_emocion", "tipo_emocion_canonico", "modo_existencia", "tipo_configuracion",
    "experienciador", "experienciador_canonico", "experienciador_marca",
    "fuente", "fuente_canonico", "fuente_marca",
    "foria", "dominancia", "intensidad", "duracion",
    "temporalidad", "aspecto", "tipo_atribucion",
    "mediador",
    "verificador_normativo", "verificador_normativo_evaluacion",
    "verificador_observacional", "verificador_observacional_evaluacion",
    "operador_modificacion", "polaridad",
    "enunciador", "frase",
)


def render(db_path: Path) -> None:
    """Renderiza la tab de exploración tabular.

    Permite seleccionar el nivel de datos, aplicar filtros y exportar
    el resultado filtrado como CSV.
    """
    st.markdown("### Tabla de datos")

    col_lvl, col_llm = st.columns([1, 2])
    with col_lvl:
        level = st.selectbox("Nivel", _LEVELS, key="tabla_level")
    with col_llm:
        usar_llm = st.toggle(
            "Usar resultados de la inferencia de los LLMs",
            value=False, key="tabla_usar_llm",
            help=(
                "Solo aplica al nivel emociones: muestra el experienciador y la "
                "fuente crudos del LLM en lugar de los canónicos (revisados en Referentes)."
            ),
        )

    df = _load(db_path, level, usar_llm=usar_llm)
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


def _load(db_path: Path, level: str, *, usar_llm: bool = False) -> pd.DataFrame:
    """Carga el DataFrame correspondiente al nivel seleccionado."""
    if level == "discursos":
        return data_layer.get_discursos(db_path)
    if level == "frases":
        return data_layer.get_frases(db_path)
    if level == "emociones":
        return _load_emociones(db_path, usar_llm=usar_llm)
    return pd.DataFrame()


def _load_emociones(db_path: Path, *, usar_llm: bool) -> pd.DataFrame:
    """Nivel emociones con canónicos por defecto (o LLM) y columnas de actants."""
    df = data_layer.get_emociones_enriched(db_path)
    if df.empty:
        return df
    df = df.copy()
    df["experienciador"] = (
        df["experienciador"].fillna("") if usar_llm else df["experienciador_efectivo"]
    )
    fte_raw = df.get("fuente_inferencia", pd.Series([""] * len(df))).fillna("")
    df["fuente"] = fte_raw if usar_llm else df["fuente_efectiva"]
    cols = [c for c in _EMO_COLS if c in df.columns]
    return df[cols]


def _apply_filters(df: pd.DataFrame, level: str) -> pd.DataFrame:
    """Aplica filtros dinámicos según el nivel seleccionado.

    Solo se muestran filtros para columnas existentes y con una
    cardinalidad razonable (< 200 valores únicos), para evitar
    selectores poco útiles o difíciles de navegar.
    """
    cols = st.columns(3)
    out = df

    candidatos = {
        "discursos": [
            "codigo", "metadata__tipo_discurso", "enunciation__enunciador",
            "summarizer__status",
        ],
        "frases":    ["codigo"],
        "emociones": [
            "codigo", "tipo_emocion", "experienciador", "fuente",
            "modo_existencia", "foria", "polaridad",
        ],
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
