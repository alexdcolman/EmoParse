# ══════════════════════════════════════════════════════════════════════════════
#  emoparse.app.components.tab_deixis
#
#  Revisión de sugerencias deícticas: por cada marca deíctica ("nosotros",
#  "tenemos", "veamos"…) el stage `deixis` propone uno o varios referentes
#  concretos (enunciador, auditorio, colectivo de identificación). Aceptar
#  inscribe la marca en ese referente y sobreescribe el canónico automático que
#  el LLM había inventado; rechazar la descarta. Se revisa de a 10.
# ══════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

import html
from pathlib import Path

import streamlit as st

from emoparse.app import actions as actions_layer
from emoparse.app import data as data_layer

_PAGE = 10
_TIPO_LABEL = {
    "enunciador": "enunciador",
    "auditorio": "auditorio",
    "colectivo_identificacion": "colectivo de identificación",
}
_STATUS_BADGE = {
    "accepted": ("aceptado", "#6ec89a"),
    "rejected": ("rechazado", "#c86e6e"),
    "proposed": ("pendiente", "#c8a96e"),
}


def _pretty(canonical_id: str) -> str:
    return str(canonical_id or "").replace("_", " ").strip().capitalize()


def render(db_path: Path) -> None:
    """Renderiza la tab de revisión de deixis."""
    st.markdown("### Deixis")

    fcol1, fcol2 = st.columns([1, 2])
    with fcol1:
        only_pending = st.toggle(
            "Solo pendientes", value=True, key="deixis_only_pending"
        )
        include_unlinked = st.toggle(
            "Incluir marcas sin sugerencia", value=False,
            key="deixis_include_unlinked",
            help="Muestra también marcas deícticas (yo/nosotros/ustedes…) que el "
                 "LLM no asignó, para asignarles un referente a mano.",
        )
    with fcol2:
        func_inc = st.multiselect(
            "Función incluye",
            ["actor", "experienciador", "fuente"],
            key="deixis_func_inc",
            placeholder="cualquiera",
        )
        func_exc = st.multiselect(
            "Función NO incluye (excluir)",
            ["actor", "experienciador", "fuente"],
            key="deixis_func_exc",
            placeholder="ninguna",
        )
    sugerencias = data_layer.get_deixis_suggestions(
        db_path, only_pending=only_pending, include_unlinked=include_unlinked
    )
    if func_inc:
        inc = set(func_inc)
        sugerencias = [s for s in sugerencias if inc & set(s["funciones"])]
    if func_exc:
        exc = set(func_exc)
        sugerencias = [s for s in sugerencias if not (exc & set(s["funciones"]))]

    if not sugerencias:
        st.info(
            "No hay sugerencias deícticas pendientes. Corré el stage `deixis` "
            "(necesita `enunciation` con auditorio/colectivos)."
        )
        return

    st.markdown(
        f"<p style='color:#8a8799;font-size:0.9rem;'>Se encontraron "
        f"<b>{len(sugerencias)}</b> marcas deícticas "
        f"<span style='color:#5a5d6e;'>(aceptar sobreescribe el referente "
        f"automático de la marca).</span></p>",
        unsafe_allow_html=True,
    )

    n_pages = (len(sugerencias) - 1) // _PAGE + 1
    page = st.session_state.get("deixis_page", 0)
    page = max(0, min(page, n_pages - 1))
    p1, p2, p3 = st.columns([1, 6, 1])
    with p1:
        if st.button("◀", key="deixis_prev", disabled=page == 0,
                     use_container_width=True):
            st.session_state["deixis_page"] = page - 1
            st.rerun()
    with p3:
        if st.button("▶", key="deixis_next", disabled=page >= n_pages - 1,
                     use_container_width=True):
            st.session_state["deixis_page"] = page + 1
            st.rerun()
    with p2:
        st.markdown(
            f"<p style='text-align:center;color:#5a5d6e;font-size:0.8rem;'>"
            f"página {page + 1} de {n_pages}</p>",
            unsafe_allow_html=True,
        )

    pagina = sugerencias[page * _PAGE:(page + 1) * _PAGE]
    ref_map = data_layer.get_deixis_referentes_map(
        db_path, codigos=sorted({s["codigo"] for s in pagina})
    )
    canonicos = data_layer.list_canonicos(db_path)
    emo_brief = data_layer.get_frase_emociones_brief(db_path)
    for sug in pagina:
        _render_sugerencia(
            db_path, sug, ref_map.get(sug["codigo"], []), canonicos, emo_brief
        )


def _render_sugerencia(
    db_path: Path, sug: dict, referentes_discurso: list[dict],
    canonicos: list[str],
    emo_brief: dict[tuple[str, int], list[dict[str, str]]] | None = None,
) -> None:
    funcs = "/".join(sug["funciones"]) or "—"
    with st.container(border=True):
        st.markdown(
            f"<span style='font-size:1rem;color:#e8e4dc;'><b>"
            f"{html.escape(str(sug['marca']))}</b></span> "
            f"<span style='font-size:0.72rem;color:#b08ad0;'>{html.escape(funcs)}</span> "
            f"<span style='font-family:DM Mono,monospace;font-size:0.7rem;"
            f"color:#5a5d6e;'> · {html.escape(str(sug['codigo']))}·u{sug['unit_idx']}"
            f"</span>",
            unsafe_allow_html=True,
        )
        if str(sug["frase"]).strip():
            # Tooltip: emociones de la frase (experienciador · emoción · fuente),
            # para decidir el referente sin salir de la tab.
            tip_attr = ""
            hint = ""
            briefs = (emo_brief or {}).get(
                (str(sug["codigo"]), int(sug["unit_idx"]))
            )
            if briefs:
                lineas = [
                    f"exp: {b['experienciador']}  ·  emo: {b['emocion']}  ·  "
                    f"fte: {b['fuente']}"
                    for b in briefs
                ]
                texto = "Emociones de la frase:\n" + "\n".join(lineas)
                tip_attr = (" title=\""
                            + html.escape(texto, quote=True).replace("\n", "&#10;")
                            + "\"")
                hint = ("<span style='color:#5a5d6e;font-size:0.7rem;"
                        "margin-left:6px;'>🛈 emociones</span>")
            st.markdown(
                f"<div{tip_attr} style='margin:0.3rem 0 0.5rem;"
                f"padding:0.45rem 0.7rem;background:#15171c;border-radius:6px;"
                f"font-size:0.84rem;line-height:1.55;color:#c2bdb4;"
                f"{'cursor:help;' if tip_attr else ''}'>"
                f"{html.escape(str(sug['frase']))}</div>{hint}",
                unsafe_allow_html=True,
            )

        for ref in sug["referentes"]:
            _render_referente(db_path, sug["mencion_id"], ref)

        _render_agregar(db_path, sug, referentes_discurso)
        _render_agregar_canonico(db_path, sug, canonicos)


def _render_agregar(db_path: Path, sug: dict, referentes_discurso: list[dict]) -> None:
    """Permite sumar a la marca otro referente deíctico del discurso."""
    ya = {r["canonical_id"] for r in sug["referentes"]}
    opciones = [r for r in referentes_discurso if r["canonical_id"] not in ya]
    if not opciones:
        return
    mid = sug["mencion_id"]
    labels = {
        f"{r['nombre']} ({_TIPO_LABEL.get(r['tipo'], r['tipo'])})": r
        for r in opciones
    }
    ac1, ac2 = st.columns([5, 1])
    sel = ac1.selectbox(
        "agregar otro referente",
        ["— agregar otro —", *labels.keys()],
        key=f"dxadd_sel_{mid}",
        label_visibility="collapsed",
    )
    with ac2:
        st.markdown("<div style='height:0.35rem;'></div>", unsafe_allow_html=True)
        if st.button("＋ agregar", key=f"dxadd_btn_{mid}",
                     use_container_width=True,
                     disabled=sel == "— agregar otro —"):
            r = labels[sel]
            actions_layer.deixis_add(db_path, mid, r["canonical_id"], r["tipo"])
            st.toast(f"«{r['nombre']}» agregado.", icon="✅")
            st.rerun()


def _render_agregar_canonico(db_path: Path, sug: dict, canonicos: list[str]) -> None:
    """Asigna a la marca un referente canónico existente (de tab Referentes) o nuevo."""
    mid = sug["mencion_id"]
    ya = {r["canonical_id"] for r in sug["referentes"]}
    opciones = [c for c in canonicos if c not in ya]
    tipos = list(_TIPO_LABEL)
    with st.expander("Asignar canónico existente o nuevo", expanded=False):
        existente = st.selectbox(
            "Canónico existente",
            ["— ninguno —", *opciones],
            key=f"dxc_sel_{mid}",
        )
        nuevo = st.text_input(
            "… o nuevo referente",
            key=f"dxc_new_{mid}",
            placeholder="nombre del referente nuevo",
        )
        tcol, bcol = st.columns([3, 1])
        tipo = tcol.selectbox(
            "Tipo",
            tipos,
            format_func=lambda t: _TIPO_LABEL.get(t, t),
            key=f"dxc_tipo_{mid}",
        )
        with bcol:
            st.markdown("<div style='height:1.8rem;'></div>", unsafe_allow_html=True)
            if st.button("＋ agregar", key=f"dxc_btn_{mid}",
                         use_container_width=True):
                canonical = nuevo.strip() or (
                    existente if existente != "— ninguno —" else ""
                )
                if not canonical:
                    st.warning("Elegí un canónico existente o escribí uno nuevo.")
                else:
                    actions_layer.deixis_add(db_path, mid, canonical, tipo)
                    st.toast(f"«{canonical}» agregado.", icon="✅")
                    st.rerun()


def _render_referente(db_path: Path, mencion_id: int, ref: dict) -> None:
    cid = ref["canonical_id"]
    tipo = _TIPO_LABEL.get(ref["deixis_tipo"], ref["deixis_tipo"] or "—")
    status = ref["status"]
    badge_txt, badge_col = _STATUS_BADGE.get(status, (status, "#8a8799"))

    c_lbl, c_ok, c_no = st.columns([5, 1, 1])
    with c_lbl:
        st.markdown(
            f"<div style='padding-top:0.35rem;'>"
            f"<b style='color:#e8e4dc;'>{html.escape(_pretty(cid))}</b> "
            f"<span style='color:#7c9ec8;font-size:0.78rem;'>({html.escape(tipo)})</span>"
            f"<span style='color:{badge_col};font-size:0.7rem;'> · {badge_txt}</span>"
            f"<br><span style='font-family:DM Mono,monospace;font-size:0.68rem;"
            f"color:#5a5d6e;'>{html.escape(cid)}</span></div>",
            unsafe_allow_html=True,
        )
    with c_ok:
        if st.button("✓ aceptar", key=f"dxok_{mencion_id}_{cid}",
                     disabled=status == "accepted", use_container_width=True):
            actions_layer.deixis_accept(db_path, mencion_id, cid)
            st.toast(f"«{_pretty(cid)}» aceptado.", icon="✅")
            st.rerun()
    with c_no:
        if st.button("✗ rechazar", key=f"dxno_{mencion_id}_{cid}",
                     disabled=status == "rejected", use_container_width=True):
            actions_layer.deixis_reject(db_path, mencion_id, cid)
            st.toast(f"«{_pretty(cid)}» rechazado.", icon="🗑")
            st.rerun()
