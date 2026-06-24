# ══════════════════════════════════════════════════════════════════════════════
#  emoparse.app.components.tab_busqueda
#
#  Búsqueda de frases por texto (palabra suelta, frase exacta entre comillas, o
#  frase con término opcional entre paréntesis) y por selección de emoción,
#  actor, experienciador o fuente. Muestra las frases completas con contexto
#  (±1) y un resumen de apariciones.
# ══════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

import html
import re
from pathlib import Path

import streamlit as st

from emoparse.app import data as data_layer
from emoparse.app._textmatch import matches, normalize, parse_query

_KIND_LABEL = {
    "emocion": "Emoción",
    "actor": "Actor",
    "experienciador": "Experienciador",
    "fuente": "Fuente",
}
_MAX_RESULTS = 200


def render(db_path: Path) -> None:
    """Renderiza la tab de búsqueda."""
    st.markdown("### Búsqueda")

    frases = data_layer.iter_all_frases(db_path)
    if not frases:
        st.info("No hay frases procesadas en este run.")
        return
    by_key = {(c, u): f for c, u, f in frases}
    items_map = data_layer.get_items_by_frase(db_path)

    tab_texto, tab_sel = st.tabs(["🔤 Por texto", "🎯 Por selección"])
    with tab_texto:
        _render_text_search(db_path, frases, by_key, items_map)
    with tab_sel:
        _render_selection_search(db_path, by_key, items_map)


# ── Búsqueda por texto ───────────────────────────────────────────────────────

def _render_text_search(db_path, frases, by_key, items_map) -> None:
    st.caption(
        "Palabra suelta: `javier milei` · Frase exacta: `\"los socialistas\"` · "
        "Término opcional: `\"abandono del modelo de (la) libertad\"`."
    )
    query = st.text_input("Buscar", key="busq_texto", placeholder="javier milei")
    if not query.strip():
        return

    matchers = parse_query(query)
    hits = [(c, u, f) for c, u, f in frases if matches(normalize(f), matchers)]

    term = _simplify_term(query)
    counts = data_layer.search_counts(db_path, term) if term else {}
    n_frases = len(hits)
    resumen = (
        f"<b>{n_frases}</b> frases"
        + (f" · {counts.get('emociones', 0)} emociones" if counts else "")
        + (f" · {counts.get('experienciadores', 0)} experienciadores" if counts else "")
        + (f" · {counts.get('fuentes', 0)} fuentes" if counts else "")
    )
    st.markdown(
        f"<p style='color:#8a8799;font-size:0.9rem;'>{resumen}</p>",
        unsafe_allow_html=True,
    )
    if not hits:
        st.info("Sin coincidencias.")
        return
    if n_frases > _MAX_RESULTS:
        st.caption(f"Mostrando las primeras {_MAX_RESULTS}.")
    for c, u, f in hits[:_MAX_RESULTS]:
        _render_hit(c, u, f, by_key, items_map)


# ── Búsqueda por selección ───────────────────────────────────────────────────

def _render_selection_search(db_path, by_key, items_map) -> None:
    opts = data_layer.list_search_options(db_path)
    kind = st.selectbox(
        "Buscar por", list(_KIND_LABEL),
        format_func=lambda k: _KIND_LABEL[k], key="busq_kind",
    )
    pool = {
        "emocion": opts["emociones"],
        "actor": opts["actores"],
        "experienciador": opts["experienciadores"],
        "fuente": opts["fuentes"],
    }[kind]
    if not pool:
        st.info(f"No hay {_KIND_LABEL[kind].lower()}es para este run.")
        return
    value = st.selectbox(_KIND_LABEL[kind], pool, key=f"busq_val_{kind}")
    if not value:
        return
    keys = data_layer.frases_for_selection(db_path, kind, value)
    st.markdown(
        f"<p style='color:#8a8799;font-size:0.9rem;'><b>{len(keys)}</b> frases.</p>",
        unsafe_allow_html=True,
    )
    for c, u in keys[:_MAX_RESULTS]:
        _render_hit(c, u, by_key.get((c, u), ""), by_key, items_map)


# ── Render de una frase con contexto ─────────────────────────────────────────

def _compress_codigo(codigo: str, keep: int = 22) -> str:
    """Comprime un código largo dejando inicio y fin."""
    codigo = str(codigo)
    if len(codigo) <= keep:
        return codigo
    head = keep // 2 - 1
    return f"{codigo[:head]}…{codigo[-head:]}"


def _render_hit(codigo, unit_idx, frase, by_key, items_map=None) -> None:
    prev = by_key.get((codigo, unit_idx - 1))
    nxt = by_key.get((codigo, unit_idx + 1))
    with st.container(border=True):
        st.markdown(
            f"<span style='font-family:DM Mono,monospace;font-size:0.72rem;"
            f"color:#5a5d6e;'>{html.escape(_compress_codigo(codigo))} · u{unit_idx}"
            f"</span>",
            unsafe_allow_html=True,
        )
        ctx = ""
        if prev:
            ctx += (f"<div style='color:#5a5d6e;font-size:0.8rem;line-height:1.5;'>"
                    f"… {html.escape(prev)}</div>")
        ctx += (f"<div style='color:#e8e4dc;font-size:0.9rem;line-height:1.6;"
                f"margin:0.15rem 0;'>{html.escape(str(frase))}</div>")
        if nxt:
            ctx += (f"<div style='color:#5a5d6e;font-size:0.8rem;line-height:1.5;'>"
                    f"{html.escape(nxt)} …</div>")
        st.markdown(ctx, unsafe_allow_html=True)
        _render_items((items_map or {}).get((codigo, unit_idx)))


_ITEM_STYLE = [
    ("emociones", "Emociones", "#b08ad0"),
    ("experienciadores", "Experienciadores", "#7c9ec8"),
    ("fuentes", "Fuentes", "#6ec89a"),
]


def _render_items(items) -> None:
    if not items:
        return
    rows = ""
    for key, label, color in _ITEM_STYLE:
        valores = items.get(key, [])
        if not valores:
            continue
        vals = " · ".join(html.escape(str(v)) for v in valores)
        rows += (
            f"<div style='font-size:0.78rem;line-height:1.6;margin-top:0.15rem;'>"
            f"<span style='color:{color};font-weight:600;'>{label}:</span> "
            f"<span style='color:#c2bdb4;'>{vals}</span></div>"
        )
    if rows:
        st.markdown(
            f"<div style='margin-top:0.45rem;padding-top:0.4rem;"
            f"border-top:1px solid #ffffff14;'>{rows}</div>",
            unsafe_allow_html=True,
        )


def _simplify_term(query: str) -> str:
    """Reduce la query a un término plano para los conteos auxiliares."""
    cleaned = re.sub(r"[\"'()\[\]]", " ", query)
    return normalize(cleaned)
