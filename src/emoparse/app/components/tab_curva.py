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
from emoparse.app._knowledge import semas_list
from emoparse.app.components import _emofilter
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

    df_em = data_layer.get_emociones_enriched(db_path)
    if df_em.empty:
        st.info("No hay emociones cargadas para este run. Corré la stage `emotions` primero.")
        return
    if "codigo" not in df_em.columns:
        st.warning("Datos sin columna `codigo`.")
        return

    corpus_posts = data_layer.has_posts(db_path)
    modo = "post"
    if corpus_posts:
        # En posts, la curva por post no dice mucho: por defecto se ve la
        # evolución de la conversación pública (por hashtag) o del hilo.
        opciones_modo = _modos_disponibles(db_path)
        modo = st.radio(
            "Unidad de la curva",
            opciones_modo,
            horizontal=True,
            key="curva_modo",
            format_func=_MODO_LABELS.get,
        )
        df_em = _df_por_modo(db_path, df_em, modo)
        if df_em.empty:
            st.info("Sin datos para esa unidad de curva.")
            return

    codigos = sorted(df_em["codigo"].unique().tolist())
    if not codigos:
        st.info("Sin discursos.")
        return

    unidad_lbl = (
        _MODO_LABELS.get(modo, "Discurso").replace("Por ", "").capitalize()
        if corpus_posts else "Discurso"
    )
    col_sel, col_toggle, col_max = st.columns([3, 1.2, 1])
    with col_sel:
        codigo_sel = st.selectbox(unidad_lbl, codigos, key=f"curva_codigo_{modo}")
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

    codigo_b: str | None = None
    if comparar:
        otros = [c for c in codigos if c != codigo_sel]
        if otros:
            codigo_b = st.selectbox(
                f"{unidad_lbl} B", otros, key=f"curva_codigo_b_{modo}"
            )

    # ── Opciones de visualización ────────────────────────────────────────────
    opt_a, opt_b, opt_c = st.columns(3)
    with opt_a:
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
                    "(columna `tipo_emocion_canonico`). Las emociones sin canónico "
                    "asignado aparecen con su nombre original."
                ),
            )
    with opt_b:
        posicion_relativa = st.toggle(
            "Posición relativa (%)",
            value=False,
            key="curva_posrel",
            help="Normaliza el eje de posición a porcentaje del discurso (frase 40 de 40 → 100 %).",
        )
    with opt_c:
        usar_llm = st.toggle(
            "Usar resultados de la inferencia de los LLMs",
            value=False,
            key="curva_usar_llm",
            help=(
                "Muestra el experienciador y la fuente tal como los devolvió el LLM, "
                "en lugar de los canónicos (revisados en Referentes)."
            ),
        )

    # Columna efectiva de emoción para los charts.
    if usar_canonico:
        df_em = df_em.copy()
        df_em["tipo_emocion"] = df_em["tipo_emocion_canonico"].where(
            df_em["tipo_emocion_canonico"].notna(),
            df_em["tipo_emocion"],
        )

    actor_col = "experienciador" if usar_llm else "experienciador_efectivo"
    fuente_col = "fuente_inferencia" if usar_llm else "fuente_efectiva"
    semas_opts = semas_list()

    st.markdown("<hr class='ep-divider'>", unsafe_allow_html=True)

    if comparar and codigo_b:
        c_a, c_b = st.columns(2)
        with c_a:
            df_a = _emofilter.filter_panel(
                df_em[df_em["codigo"] == codigo_sel], key="curva_f_a",
                semas_options=semas_opts, title=f"Filtros · {codigo_sel}",
            )
        with c_b:
            df_bsel = _emofilter.filter_panel(
                df_em[df_em["codigo"] == codigo_b], key="curva_f_b",
                semas_options=semas_opts, title=f"Filtros · {codigo_b}",
            )
        df_plot = pd.concat([df_a, df_bsel], ignore_index=True)
        fig = charts.curva_emocional_comparada(
            df_plot, [codigo_sel, codigo_b], max_frases=int(max_fr),
            actor_col=actor_col, fuente_col=fuente_col,
            posicion_relativa=posicion_relativa,
        )
    else:
        df_a = _emofilter.filter_panel(
            df_em[df_em["codigo"] == codigo_sel], key="curva_f_a",
            semas_options=semas_opts, title="Filtros",
        )
        fig = charts.curva_emocional(
            df_a, codigo_sel, max_frases=int(max_fr),
            actor_col=actor_col, fuente_col=fuente_col,
            posicion_relativa=posicion_relativa,
        )
    st.plotly_chart(fig, use_container_width=True)

    st.markdown("<hr class='ep-divider'>", unsafe_allow_html=True)
    col_dist, col_chips = st.columns(2)
    with col_dist:
        st.markdown(f"#### Distribución · {codigo_sel}")
        fig_dist = charts.distribucion_emociones(df_a, codigo=codigo_sel)
        st.plotly_chart(fig_dist, use_container_width=True)
    with col_chips:
        st.markdown(f"#### Lista de emociones · {codigo_sel}")
        _render_chips(df_a.head(int(max_fr)), usar_llm=usar_llm)


def _render_chips(df_sel: pd.DataFrame, *, usar_llm: bool = False) -> None:
    """Renderiza la lista de emociones como chips visuales.

    Por defecto muestra experienciador y fuente canónicos (resueltos en Referentes);
    con `usar_llm`, la inferencia cruda del LLM.
    """
    if df_sel.empty:
        st.info("Sin emociones.")
        return

    df_sel = df_sel.sort_values(["frase_idx", "emocion_idx"])
    exp_col = "experienciador" if usar_llm else "experienciador_efectivo"
    fte_col = "fuente_inferencia" if usar_llm else "fuente_efectiva"

    chips_html = []
    for _, row in df_sel.iterrows():
        emo = str(row.get("tipo_emocion", "") or "")
        exp = str(row.get(exp_col, "") or row.get("experienciador", "") or "")
        fte = str(row.get(fte_col, "") or "")
        modo = str(row.get("modo_existencia", "") or "")
        foria = str(row.get("foria", "") or "")
        pos = row.get("frase_idx", "—")
        color = charts.emo_color(emo)
        ficon = _FORIA_ICONS.get(foria, "")

        fte_badge = (
            f"<span class='badge badge-dim' style='font-size:0.64rem;"
            f"color:#6ec89a;border-color:#6ec89a40;'>← {fte}</span>"
            if fte and fte != "—" else ""
        )

        r, g, b = int(color[1:3], 16), int(color[3:5], 16), int(color[5:7], 16)
        chips_html.append(
            f"<div style='display:flex;align-items:center;gap:0.6rem;"
            f"padding:0.3rem 0.6rem;border-bottom:1px solid #1a1c22;'>"
            f"<span style='font-family:DM Mono,monospace;font-size:0.68rem;"
            f"color:#3a3d4e;min-width:2.4rem;'>#{pos}</span>"
            f"<span class='emo-chip' style='background:rgba({r},{g},{b},0.15);"
            f"color:{color};border-color:{color}40;'>{emo}</span>"
            f"<span style='font-size:0.76rem;color:#8a8799;'>{exp}</span>"
            f"{fte_badge}"
            f"<span class='badge badge-dim' style='font-size:0.66rem;'>{modo}</span>"
            f"<span style='color:{color};margin-left:auto;font-size:0.82rem;'>{ficon}</span>"
            f"</div>"
        )

    st.markdown(
        "<div style='max-height:400px;overflow-y:auto;'>"
        + "".join(chips_html) + "</div>",
        unsafe_allow_html=True,
    )


# ══════════════════════════════════════════════════════════════════════════════
#  Unidad de la curva para corpus de posts
# ══════════════════════════════════════════════════════════════════════════════

#: Etiquetas visibles de cada unidad de curva.
_MODO_LABELS: dict[str, str] = {
    "hashtag": "Por #hashtag",
    "hilo": "Por hilo",
    "post": "Por post",
}


def _modos_disponibles(db_path: Path) -> list[str]:
    """Unidades de curva disponibles según el corpus (hashtag/hilo primero)."""
    modos: list[str] = []
    if not data_layer.get_post_hashtags(db_path).empty:
        modos.append("hashtag")
    df_ctx = data_layer.get_post_contexto(db_path)
    if not df_ctx.empty and df_ctx["conversacion_id"].notna().any():
        modos.append("hilo")
    modos.append("post")
    return modos


def _df_por_modo(db_path: Path, df_em: pd.DataFrame, modo: str) -> pd.DataFrame:
    """Transforma las emociones a la unidad de curva elegida.

    En `post` solo reemplaza los códigos por sus títulos de input. En
    `hashtag`/`hilo` agrupa los posts de cada conversación: el código pasa a
    ser el grupo y la posición, el orden temporal del post dentro del grupo,
    de modo que la curva representa la evolución de la conversación pública.
    """
    if modo == "post":
        labels = data_layer.codigo_labels(db_path)
        out = df_em.copy()
        out["codigo"] = out["codigo"].map(lambda c: labels.get(c, c))
        return out

    return data_layer.agrupar_por_conversacion(db_path, df_em, modo)
