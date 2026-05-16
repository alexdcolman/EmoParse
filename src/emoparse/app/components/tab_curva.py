# ══════════════════════════════════════════════════════════════════════════════
#  emoparse.app.components.tab_curva
#
#  Tab de curva emocional del dashboard Streamlit.
#
#  Permite explorar un discurso frase a frase y, opcionalmente,
#  compararlo con un segundo discurso. Incluye visualización principal,
#  distribución emocional y listado detallado de emociones detectadas.
# ══════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

from pathlib import Path

import pandas as pd
import streamlit as st

from emoparse.app import data as data_layer
from emoparse.viz import charts


#: Iconos de foria usados en la visualización de chips.
_FORIA_ICONS: dict[str, str] = {
    "eufórico":      "↑",
    "disfórico":     "↓",
    "afórico":       "–",
    "ambifórico":    "↕",
    "indeterminado": "?",
}


def render(db_path: Path) -> None:
    """Renderiza la tab de curva emocional.

    Permite seleccionar uno o dos discursos del run activo y muestra
    la curva emocional frase a frase, junto con la distribución
    emocional y el listado de emociones del discurso principal.
    """
    st.markdown("### Curva emocional frase a frase")

    df_em = data_layer.get_emociones(db_path)
    if df_em.empty:
        st.info("No hay emociones cargadas para este run. Corré la stage `emotions` primero.")
        return
    if "codigo" not in df_em.columns:
        st.warning("Datos sin columna `codigo`.")
        return

    codigos = sorted(df_em["codigo"].unique().tolist())
    if not codigos:
        st.info("Sin discursos.")
        return

    col_sel, col_toggle, col_max = st.columns([3, 1.2, 1])
    with col_sel:
        codigo_sel = st.selectbox("Discurso", codigos, key="curva_codigo")
    with col_toggle:
        comparar = st.toggle(
            "Comparar con otro",
            value=False,
            key="curva_comparar",
            disabled=len(codigos) < 2,
        )
    with col_max:
        max_fr = st.number_input(
            "Máx. frases",
            min_value=20, max_value=500, value=200, step=20,
            key="curva_maxfr",
        )

    # Toggle canónico: visible solo si la columna existe y tiene datos.
    _has_canonico = (
        "tipo_emocion_canonico" in df_em.columns
        and df_em["tipo_emocion_canonico"].notna().any()
    )
    usar_canonico = False
    if _has_canonico:
        usar_canonico = st.toggle(
            "Usar tipo canónico (ontología)",
            value=False,
            key="curva_canonico",
            help=(
                "Agrupa emociones por su nombre canónico según la ontología "
                "(columna `tipo_emocion_canonico`). "
                "Las emociones sin canónico asignado aparecen con su nombre original."
            ),
        )

    # Columna efectiva de emoción para los charts.
    if usar_canonico:
        df_em = df_em.copy()
        # Fallback al tipo original si el canónico es nulo.
        df_em["tipo_emocion"] = df_em["tipo_emocion_canonico"].where(
            df_em["tipo_emocion_canonico"].notna(),
            df_em["tipo_emocion"],
        )

    codigo_b: str | None = None
    if comparar:
        otros = [c for c in codigos if c != codigo_sel]
        if otros:
            codigo_b = st.selectbox("Discurso B", otros, key="curva_codigo_b")

    st.markdown("<hr class='ep-divider'>", unsafe_allow_html=True)
    if comparar and codigo_b:
        fig = charts.curva_emocional_comparada(
            df_em, [codigo_sel, codigo_b], max_frases=int(max_fr),
        )
    else:
        fig = charts.curva_emocional(df_em, codigo_sel, max_frases=int(max_fr))
    st.plotly_chart(fig, use_container_width=True)

    df_sel_a = df_em[df_em["codigo"] == codigo_sel].copy()
    st.markdown("<hr class='ep-divider'>", unsafe_allow_html=True)

    col_dist, col_chips = st.columns(2)
    with col_dist:
        st.markdown(f"#### Distribución · {codigo_sel}")
        fig_dist = charts.distribucion_emociones(df_em, codigo=codigo_sel)
        st.plotly_chart(fig_dist, use_container_width=True)
    with col_chips:
        st.markdown(f"#### Lista de emociones · {codigo_sel}")
        _render_chips(df_sel_a.head(int(max_fr)))


def _render_chips(df_sel: pd.DataFrame) -> None:
    """Renderiza la lista de emociones como chips visuales."""
    if df_sel.empty:
        st.info("Sin emociones.")
        return

    df_sel = df_sel.sort_values(["frase_idx", "emocion_idx"])

    chips_html = []
    for _, row in df_sel.iterrows():
        emo = str(row.get("tipo_emocion", "") or "")
        exp = str(row.get("experienciador", "") or "")
        modo = str(row.get("modo_existencia", "") or "")
        foria = str(row.get("foria", "") or "")
        pos = row.get("frase_idx", "—")
        color = charts.emo_color(emo)
        ficon = _FORIA_ICONS.get(foria, "")

        canonico_raw = row.get("tipo_emocion_canonico")
        canonico = str(canonico_raw) if canonico_raw and canonico_raw != emo else ""
        canonico_badge = (
            f"<span class='badge badge-dim' style='font-size:0.64rem;"
            f"color:#7c9ec8;border-color:#7c9ec840;'>≡ {canonico}</span>"
            if canonico else ""
        )

        r, g, b = int(color[1:3], 16), int(color[3:5], 16), int(color[5:7], 16)
        chips_html.append(
            f"<div style='display:flex;align-items:center;gap:0.6rem;"
            f"padding:0.3rem 0.6rem;border-bottom:1px solid #1a1c22;'>"
            f"<span style='font-family:DM Mono,monospace;font-size:0.68rem;"
            f"color:#3a3d4e;min-width:2.4rem;'>#{pos}</span>"
            f"<span class='emo-chip' style='background:rgba({r},{g},{b},0.15);"
            f"color:{color};border-color:{color}40;'>{emo}</span>"
            f"{canonico_badge}"
            f"<span style='font-size:0.76rem;color:#8a8799;'>{exp}</span>"
            f"<span class='badge badge-dim' style='font-size:0.66rem;'>{modo}</span>"
            f"<span style='color:{color};margin-left:auto;font-size:0.82rem;'>{ficon}</span>"
            f"</div>"
        )

    st.markdown(
        "<div style='max-height:400px;overflow-y:auto;'>"
        + "".join(chips_html) + "</div>",
        unsafe_allow_html=True,
    )
