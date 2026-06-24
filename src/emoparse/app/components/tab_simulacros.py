# ══════════════════════════════════════════════════════════════════════════════
#  emoparse.app.components.tab_simulacros
#
#  Reconstrucción de "simulacros de emoción": descripción analítica de cada
#  emoción discursiva con sus funciones actanciales. Permite filtrar por tipo de
#  actante (mediador, verificadores, operador de modificación), por semas de
#  experienciador y de fuente, y por la emoción reconocida.
# ══════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

import html
from pathlib import Path
from typing import Any

import pandas as pd
import streamlit as st

from emoparse.app import data as data_layer
from emoparse.app import _knowledge
from emoparse.app._textmatch import matches, normalize, parse_query

#: Opciones tipadas de actantes, tomadas del esquema como fuente de verdad.
try:
    from typing import get_args

    from emoparse.core import schemas as _sc

    _ACTANTE_OPTS: dict[str, list[str]] = {
        "mediador": list(get_args(_sc.TipoMediador)),
        "verificador_normativo": list(get_args(_sc.TipoVerificadorNormativo)),
        "verificador_observacional": list(get_args(_sc.TipoVerificadorObservacional)),
        "operador_modificacion": list(get_args(_sc.FuncionOpMod)),
    }
except Exception:  # pragma: no cover — fallback defensivo
    _ACTANTE_OPTS = {
        "mediador": [], "verificador_normativo": [],
        "verificador_observacional": [], "operador_modificacion": [],
    }

_ACTANTE_LABEL = {
    "mediador": "Mediador",
    "verificador_normativo": "Verificador normativo",
    "verificador_observacional": "Verificador observacional",
    "operador_modificacion": "Operador de modificación",
}

#: Color por rol del simulacro, usado en selectores y resultados para que cada
#: función se distinga de un vistazo.
_ROLE_COLOR = {
    "experienciador": "#7c9ec8",
    "emocion": "#b08ad0",
    "fuente": "#6ec89a",
    "mediador": "#c8a96e",
    "verificador_normativo": "#d28aa8",
    "verificador_observacional": "#8ac6d0",
    "operador_modificacion": "#cf8f6e",
}


def _lbl(text: str, role: str) -> str:
    """Etiqueta coloreada por rol para los selectores."""
    return (
        f"<span style='font-size:0.78rem;font-weight:600;"
        f"color:{_ROLE_COLOR.get(role, '#8a8799')};'>{text}</span>"
    )


_PAGE = 20
_CUALQUIERA = "(cualquiera)"


def render(db_path: Path) -> None:
    """Renderiza la tab de simulacros de emoción."""
    st.markdown("### Simulacros de emoción")
    st.caption(
        "Cada simulacro es la descripción analítica de una emoción con sus "
        "funciones actanciales. Filtrá por tipo de actante, por semas del "
        "experienciador y de la fuente, y por emoción."
    )

    df = data_layer.get_simulacros(db_path)
    if df.empty:
        st.info(
            "No hay emociones materializadas. Corré `explode_emociones` "
            "(y opcionalmente `actants`/`semas`)."
        )
        return

    # ── Filtros ───────────────────────────────────────────────────────────────
    emociones = sorted(
        e for e in df["tipo_emocion_canonico"].dropna().unique() if str(e).strip()
    )
    semas_vocab = _knowledge.semas_list()

    query = st.text_input(
        "Buscar por texto",
        key="sim_query",
        placeholder='ítem léxico o "sintagma exacto" o "modelo de (la) libertad"',
    )

    c1, c2 = st.columns(2)
    with c1:
        st.markdown(_lbl("Emoción", "emocion"), unsafe_allow_html=True)
        emo_sel = st.multiselect(
            "Emoción", emociones, key="sim_emo", label_visibility="collapsed"
        )
    with c2:
        st.markdown(
            "<span style='font-size:0.78rem;color:#8a8799;'>Semas</span>",
            unsafe_allow_html=True,
        )
        sc1, sc2 = st.columns(2)
        with sc1:
            st.markdown(_lbl("Experienciador", "experienciador"),
                        unsafe_allow_html=True)
            exp_semas = st.multiselect(
                "Experienciador", semas_vocab, key="sim_exp_semas",
                label_visibility="collapsed",
            )
        with sc2:
            st.markdown(_lbl("Fuente", "fuente"), unsafe_allow_html=True)
            fte_semas = st.multiselect(
                "Fuente", semas_vocab, key="sim_fte_semas",
                label_visibility="collapsed",
            )

    st.markdown(
        "<span style='font-size:0.78rem;color:#8a8799;'>Actantes</span>",
        unsafe_allow_html=True,
    )
    acol = st.columns(4)
    actante_sel: dict[str, str] = {}
    for i, key in enumerate(_ACTANTE_OPTS):
        with acol[i]:
            st.markdown(_lbl(_ACTANTE_LABEL[key], key), unsafe_allow_html=True)
            opts = [_CUALQUIERA, *(_ACTANTE_OPTS[key] or [])]
            actante_sel[key] = st.selectbox(
                _ACTANTE_LABEL[key], opts, key=f"sim_act_{key}",
                label_visibility="collapsed",
            )

    # ── Aplicar filtros ───────────────────────────────────────────────────────
    mask = pd.Series(True, index=df.index)
    if emo_sel:
        mask &= df["tipo_emocion_canonico"].isin(emo_sel)
    for key, val in actante_sel.items():
        if val != _CUALQUIERA:
            mask &= df[key] == val
    if exp_semas:
        mask &= df["experienciador_semas"].apply(
            lambda xs: set(exp_semas).issubset(set(xs))
        )
    if fte_semas:
        mask &= df["fuente_semas"].apply(
            lambda xs: set(fte_semas).issubset(set(xs))
        )
    if query.strip():
        matchers = parse_query(query)
        blob = (
            df["frase"].fillna("") + " "
            + df["experienciador"].fillna("") + " "
            + df["experienciador_canonico"].fillna("") + " "
            + df["fuente_inferencia"].fillna("") + " "
            + df["fuente_canonico"].fillna("") + " "
            + df["tipo_emocion_canonico"].fillna("")
        ).map(normalize)
        mask &= blob.map(lambda t: matches(t, matchers))

    res = df[mask].reset_index(drop=True)
    st.markdown(
        f"<p style='color:#8a8799;font-size:0.85rem;'>{len(res)} simulacro(s) "
        f"de {len(df)} emociones.</p>",
        unsafe_allow_html=True,
    )
    if res.empty:
        st.info("Sin simulacros para esa combinación de filtros.")
        return

    # ── Paginación ────────────────────────────────────────────────────────────
    n_pages = (len(res) - 1) // _PAGE + 1
    page = st.session_state.get("sim_page", 0)
    page = max(0, min(page, n_pages - 1))
    p1, p2, p3 = st.columns([1, 6, 1])
    with p1:
        if st.button("◀", key="sim_prev", disabled=page == 0,
                     use_container_width=True):
            st.session_state["sim_page"] = page - 1
            st.rerun()
    with p3:
        if st.button("▶", key="sim_next", disabled=page >= n_pages - 1,
                     use_container_width=True):
            st.session_state["sim_page"] = page + 1
            st.rerun()
    with p2:
        st.markdown(
            f"<p style='text-align:center;color:#5a5d6e;font-size:0.8rem;'>"
            f"página {page + 1} de {n_pages}</p>",
            unsafe_allow_html=True,
        )

    for _, row in res.iloc[page * _PAGE:(page + 1) * _PAGE].iterrows():
        _render_simulacro(row)


def _chip(label: str, value: str, color: str) -> str:
    if not value or value == "ausente":
        return ""
    return (
        f"<span style='font-size:0.7rem;color:{color};border:1px solid {color}44;"
        f"border-radius:5px;padding:1px 7px;margin:2px 4px 2px 0;display:inline-block;'>"
        f"{html.escape(label)}: {html.escape(str(value))}</span>"
    )


def _render_simulacro(row: pd.Series) -> None:
    exp = row["experienciador_canonico"] or row["experienciador"] or "—"
    fte = row["fuente_canonico"] or row["fuente_inferencia"] or "—"
    emo = row["tipo_emocion_canonico"] or "—"

    with st.container(border=True):
        st.markdown(
            f"<div style='font-size:0.95rem;'>"
            f"<b style='color:{_ROLE_COLOR['experienciador']};'>{html.escape(str(exp))}</b> "
            f"<span style='color:{_ROLE_COLOR['emocion']};font-weight:600;'>"
            f"{html.escape(str(emo))}</span> "
            f"<span style='color:#5a5d6e;'>←</span> "
            f"<b style='color:{_ROLE_COLOR['fuente']};'>{html.escape(str(fte))}</b></div>"
            f"<div style='font-size:0.72rem;color:#5a5d6e;"
            f"font-family:DM Mono,monospace;margin-top:0.15rem;'>"
            f"{html.escape(str(row['codigo']))}·u{row['frase_idx']}·e{row['emocion_idx']}"
            f"</div>",
            unsafe_allow_html=True,
        )
        chips = (
            _chip("mediador", row["mediador"], _ROLE_COLOR["mediador"])
            + _chip("v.normativo", row["verificador_normativo"],
                    _ROLE_COLOR["verificador_normativo"])
            + _chip("v.observacional", row["verificador_observacional"],
                    _ROLE_COLOR["verificador_observacional"])
            + _chip("op.modificación", row["operador_modificacion"],
                    _ROLE_COLOR["operador_modificacion"])
        )
        exp_s = ", ".join(row["experienciador_semas"])
        fte_s = ", ".join(row["fuente_semas"])
        if exp_s:
            chips += _chip("exp.semas", exp_s, _ROLE_COLOR["experienciador"])
        if fte_s:
            chips += _chip("fte.semas", fte_s, _ROLE_COLOR["fuente"])
        if chips:
            st.markdown(f"<div style='margin-top:0.35rem;'>{chips}</div>",
                        unsafe_allow_html=True)
        if str(row["frase"]).strip():
            st.markdown(
                f"<div style='margin-top:0.4rem;padding:0.45rem 0.7rem;"
                f"background:#15171c;border-radius:6px;font-size:0.84rem;"
                f"line-height:1.5;color:#c2bdb4;'>{html.escape(str(row['frase']))}</div>",
                unsafe_allow_html=True,
            )
