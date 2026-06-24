# ══════════════════════════════════════════════════════════════════════════════
#  emoparse.app.components.tab_referentes
# ══════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

import html
from pathlib import Path

import pandas as pd
import streamlit as st

from emoparse.app import actions as actions_layer
from emoparse.app import data as data_layer
from emoparse.app import _knowledge

_SIN_CANONICO = "— sin canónico —"
_STATUS = {
    "accepted": ("✓", "#6ec89a"),
    "rejected": ("✗", "#c86e6e"),
    "proposed": ("◷", "#c8a96e"),
}
_FN_COLOR = {
    "actor": "#7c9ec8",
    "experienciador": "#b08ad0",
    "fuente": "#c8a96e",
    "circunstante": "#8a8799",
}
_MAX_MARCAS = 30

# La fuente de verdad de posición es el canonical_id, NO el label.
# El label se recalcula en cada ciclo y puede cambiar (n_accepted sube/baja);
# el cid es estable mientras el referente exista.
_CID_KEY  = "ref_active_cid"   # canonical_id activo (str | None | sentinel)
_SEL_KEY  = "ref_sel"          # label en el selectbox (solo para UI)
_SENTINEL = object()            # valor inicial que indica "no hay selección"


def _label_for(cid: str | None, n: int, n_accepted: int) -> str:
    if cid is None:
        return f"{_SIN_CANONICO} · {n}"
    return f"{cid} · {n} marca(s){' ✓' if n_accepted else ''}"


def _set_active(canonical_id: str | None) -> None:
    """Fija el referente activo por su cid (persiste entre reruns)."""
    st.session_state[_CID_KEY] = canonical_id


def render(db_path: Path) -> None:
    """Renderiza la tab de revisión de referentes, uno por vez."""
    st.markdown("### Referentes canónicos")
    st.caption(
        "Revisión referente por referente. Para cada marca ves su frase en "
        "contexto y podés aceptar, rechazar, quitar o reasignar el vínculo."
    )

    # ── Filtros ───────────────────────────────────────────────────────────────
    codigos = ["(todos)"]
    try:
        dd = data_layer.get_discursos(db_path)
        if not dd.empty and "codigo" in dd.columns:
            codigos += sorted(dd["codigo"].dropna().astype(str).tolist())
    except Exception:
        pass

    f1, f2, f3 = st.columns([2, 2, 1])
    with f1:
        codigo_sel = st.selectbox("Discurso", codigos, key="ref_codigo")
    codigo = None if codigo_sel == "(todos)" else codigo_sel
    with f2:
        query = st.text_input(
            "Buscar referente", key="ref_query",
            placeholder="filtrar por canónico…",
        ).strip().lower()
    with f3:
        st.markdown("<div style='height:1.6rem;'></div>", unsafe_allow_html=True)
        if st.button("⤴ Promover → KB", key="ref_promote",
                     help="Sincroniza referentes aceptados en referentes_kb.json "
                          "(agrega nuevos, elimina los que ya no tienen vínculos "
                          "aceptados; no pisa tipo/notas editados a mano)."):
            res = actions_layer.promote_referentes(db_path)
            removed = res.get("removed", 0)
            removed_txt = f", {removed} eliminados" if removed else ""
            st.toast(
                f"KB: {res.get('referentes_total', 0)} referentes "
                f"({res.get('added', 0)} nuevos, {res.get('updated', 0)} "
                f"completados{removed_txt}).",
                icon="✅",
            )
            # Sin st.rerun(): el rerun natural del botón preserva _CID_KEY.

    resumen = data_layer.get_referentes_resumen(db_path, codigo)
    if resumen.empty:
        st.info(
            "No hay marcas discursivas para este run. Corré el pipeline "
            "(stage `explode_emociones`) para poblarlas."
        )
        return

    # ── Lista navegable ────────────────────────────────────────────────────────
    items: list[tuple[str | None, str]] = []
    for _, r in resumen.iterrows():
        cid = r["canonical_id"]
        n = int(r["n_marcas"] or 0)
        acc = int(r["n_accepted"] or 0)
        cid_str = None if (cid is None or str(cid) == "") else str(cid)
        items.append((cid_str, _label_for(cid_str, n, acc)))

    if query:
        items = [it for it in items if it[0] and query in it[0].lower()]
    if not items:
        st.info("Sin coincidencias.")
        return

    labels = [lab for _, lab in items]
    cids   = [cid for cid, _ in items]

    # ── Resolver el cid activo → índice en la lista actual ────────────────────
    active_cid = st.session_state.get(_CID_KEY, _SENTINEL)
    if active_cid is _SENTINEL or active_cid not in cids:
        # Primera vez o el cid activo desapareció de la lista: ir al primero
        cur = 0
    else:
        cur = cids.index(active_cid)
    # Sincronizar _CID_KEY con el cid real del ítem actual
    st.session_state[_CID_KEY] = cids[cur]

    # ── Navegador prev / select / next ────────────────────────────────────────
    st.markdown(
        f"<p style='color:#5a5d6e;font-size:0.78rem;margin:0.5rem 0 0.2rem;'>"
        f"{len(items)} referentes</p>",
        unsafe_allow_html=True,
    )
    nprev, nsel, nnext = st.columns([1, 8, 1])
    with nprev:
        if st.button("◀", key="ref_prev", disabled=cur == 0,
                     use_container_width=True):
            _set_active(cids[cur - 1])
            st.rerun()
    with nnext:
        if st.button("▶", key="ref_next", disabled=cur >= len(labels) - 1,
                     use_container_width=True):
            _set_active(cids[cur + 1])
            st.rerun()
    with nsel:
        # El selectbox muestra el label pero al cambiar guardamos el cid
        sel_label = st.selectbox(
            f"Referente {cur + 1} de {len(labels)}", labels,
            index=cur,
            key=_SEL_KEY,
            label_visibility="collapsed",
        )
        # Si el usuario eligió un label distinto en el selectbox, actualizar cid
        sel_idx = labels.index(sel_label)
        if sel_idx != cur:
            _set_active(cids[sel_idx])
            st.rerun()

    _render_referente(db_path, items[cur][0], cur, items)


# ── Render de un referente ────────────────────────────────────────────────────

def _render_referente(
    db_path: Path,
    canonical_id: str | None,
    cur_idx: int,
    items: list[tuple[str | None, str]],
) -> None:
    """Renderiza las marcas del referente activo + panel de edición KB."""
    marks = data_layer.get_menciones_de_canonico(db_path, canonical_id)

    titulo = canonical_id if canonical_id else _SIN_CANONICO
    n_marks = len(marks)

    st.markdown(
        f"<div style='margin:0.6rem 0 0.4rem;padding:0.4rem 0;"
        f"border-bottom:1px solid #2a2c34;'>"
        f"<span style='font-family:DM Mono,monospace;font-size:1.0rem;"
        f"color:#e8e4dc;font-weight:600;'>{html.escape(str(titulo))}</span>"
        f"<span style='color:#5a5d6e;font-size:0.78rem;'> · "
        f"{n_marks} marca(s)</span></div>",
        unsafe_allow_html=True,
    )

    if canonical_id is not None:
        _render_kb_panel(db_path, canonical_id, cur_idx, items)
        _render_semas_panel(db_path, canonical_id)

    if marks.empty:
        st.info("Este referente ya no tiene marcas vinculadas.")
        return

    extra = 0
    if n_marks > _MAX_MARCAS:
        extra = n_marks - _MAX_MARCAS
        marks = marks.head(_MAX_MARCAS)

    for _, row in marks.iterrows():
        _render_marca_card(db_path, canonical_id, row, items)

    if extra:
        st.caption(
            f"… y {extra} marca(s) más en este referente. Filtrá por discurso "
            f"para acotar la revisión."
        )


def _render_kb_panel(
    db_path: Path,
    canonical_id: str,
    cur_idx: int,
    items: list[tuple[str | None, str]],
) -> None:
    """Panel colapsable: editar KB (display_name, tipo, notas) + renombrar + eliminar."""

    kb_entry = actions_layer.get_kb_entry(canonical_id)

    with st.expander("⚙ Editar en KB / Renombrar / Eliminar", expanded=False):

        # ── Edición de campos KB (un solo Guardar) ────────────────────────────
        st.markdown(
            "<span style='font-size:0.78rem;color:#8a8799;'>display_name</span>",
            unsafe_allow_html=True,
        )
        new_display = st.text_input(
            "display_name",
            value=kb_entry.get("display_name", "") if kb_entry else "",
            key=f"kb_dn_{canonical_id}",
            label_visibility="collapsed",
            placeholder="nombre visible…",
        ).strip()

        st.markdown(
            "<span style='font-size:0.78rem;color:#8a8799;'>tipo</span>",
            unsafe_allow_html=True,
        )
        new_tipo = st.text_input(
            "tipo",
            value=kb_entry.get("tipo", "") if kb_entry else "",
            key=f"kb_tipo_{canonical_id}",
            label_visibility="collapsed",
            placeholder="institución, persona, concepto…",
        ).strip()

        st.markdown(
            "<span style='font-size:0.78rem;color:#8a8799;'>notas</span>",
            unsafe_allow_html=True,
        )
        new_notas = st.text_area(
            "notas",
            value=kb_entry.get("notas", "") if kb_entry else "",
            key=f"kb_notas_{canonical_id}",
            label_visibility="collapsed",
            placeholder="observaciones libres…",
            height=68,
        ).strip()

        if st.button("💾 Guardar cambios en KB", key=f"kb_save_{canonical_id}"):
            actions_layer.update_kb_entry(
                canonical_id,
                display_name=new_display or None,
                tipo=new_tipo,
                notas=new_notas,
            )
            st.toast("KB actualizada.", icon="✅")

        st.divider()

        # ── Renombrar canonical_id ────────────────────────────────────────────
        st.markdown(
            "<span style='font-size:0.78rem;color:#8a8799;'>"
            "Renombrar canonical_id (actualiza DB + KB)</span>",
            unsafe_allow_html=True,
        )
        rn_col, rn_btn = st.columns([5, 1])
        nuevo_id = rn_col.text_input(
            "nuevo id",
            value=canonical_id,
            key=f"rename_input_{canonical_id}",
            label_visibility="collapsed",
            placeholder="nuevo_canonical_id…",
        ).strip()
        with rn_btn:
            st.markdown("<div style='height:0.35rem;'></div>", unsafe_allow_html=True)
            if st.button("Renombrar", key=f"rename_btn_{canonical_id}",
                         use_container_width=True):
                if nuevo_id and nuevo_id != canonical_id:
                    res = actions_layer.rename_canonical(db_path, canonical_id, nuevo_id)
                    st.toast(
                        f"Renombrado a «{nuevo_id}» "
                        f"({res.get('rows_updated', 0)} vínculos actualizados).",
                        icon="✏",
                    )
                    _set_active(nuevo_id)
                    st.rerun()
                else:
                    st.warning("El nombre nuevo es igual al actual o está vacío.")

        st.divider()

        # ── Mergear con otro canónico ─────────────────────────────────────────
        st.markdown(
            "<span style='font-size:0.78rem;color:#8a8799;'>"
            "Mergear dentro de otro canónico (quedás en el destino)</span>",
            unsafe_allow_html=True,
        )
        otros = [c for c, _ in items if c is not None and c != canonical_id]
        if otros:
            mg_col, mg_btn = st.columns([5, 1])
            destino_merge = mg_col.selectbox(
                "destino merge",
                ["— elegir destino —"] + otros,
                key=f"merge_sel_{canonical_id}",
                label_visibility="collapsed",
            )
            with mg_btn:
                st.markdown("<div style='height:0.35rem;'></div>",
                            unsafe_allow_html=True)
                if st.button("Mergear", key=f"merge_btn_{canonical_id}",
                             use_container_width=True):
                    if destino_merge != "— elegir destino —":
                        res = actions_layer.merge_canonicals(
                            db_path, canonical_id, destino_merge
                        )
                        st.toast(
                            f"«{canonical_id}» → «{destino_merge}» "
                            f"({res.get('links_merged', 0)} vínculos).",
                            icon="🔗",
                        )
                        _set_active(destino_merge)
                        st.rerun()
                    else:
                        st.warning("Elegí un canónico destino.")
        else:
            st.caption("No hay otros canónicos para mergear.")

        st.divider()

        # ── Eliminar canónico ─────────────────────────────────────────────────
        st.markdown(
            "<span style='font-size:0.78rem;color:#c86e6e;'>"
            "Eliminar canónico (quita todos sus vínculos de la DB y lo borra de la KB)</span>",
            unsafe_allow_html=True,
        )
        if st.button("🗑 Eliminar canónico", key=f"del_canon_{canonical_id}",
                     type="primary"):
            actions_layer.delete_canonical(db_path, canonical_id)
            next_cid = _next_canonical(cur_idx, items)
            _set_active(next_cid)
            st.rerun()


_SEMA_COLOR = {"accepted": "#6ec89a", "proposed": "#c8a96e", "rejected": "#c86e6e"}


def _render_semas_panel(db_path: Path, canonical_id: str) -> None:
    """Panel de semas del referente: ver/quitar actuales y agregar del vocabulario."""
    with st.expander("🏷 Semas del referente", expanded=False):
        actuales = data_layer.list_canonico_semas(db_path, canonical_id)
        actuales_set = {s["sema"] for s in actuales if s.get("status") != "rejected"}

        if actuales:
            for s in actuales:
                sema = str(s["sema"])
                status = str(s.get("status") or "")
                origin = str(s.get("origin") or "")
                color = _SEMA_COLOR.get(status, "#8a8799")
                c1, c2 = st.columns([5, 1])
                c1.markdown(
                    f"<span style='font-size:0.82rem;color:{color};'>"
                    f"{html.escape(sema)}</span>"
                    f"<span style='color:#5a5d6e;font-size:0.7rem;'> · {status}"
                    f" · {html.escape(origin)}</span>",
                    unsafe_allow_html=True,
                )
                if c2.button("✗", key=f"sema_rm_{canonical_id}_{sema}",
                             help="Quitar sema", use_container_width=True):
                    actions_layer.referente_remove_sema(db_path, canonical_id, sema)
                    st.toast(f"Sema «{sema}» quitado.", icon="🗑")
                    st.rerun()
        else:
            st.caption("Sin semas asignados.")

        vocab = [s for s in _knowledge.semas_list() if s not in actuales_set]
        if vocab:
            ac1, ac2 = st.columns([5, 1])
            nuevos = ac1.multiselect(
                "agregar semas", vocab,
                key=f"sema_add_{canonical_id}",
                label_visibility="collapsed",
                placeholder="agregar semas del vocabulario…",
            )
            with ac2:
                st.markdown("<div style='height:0.35rem;'></div>",
                            unsafe_allow_html=True)
                if st.button("＋", key=f"sema_addbtn_{canonical_id}",
                             use_container_width=True, disabled=not nuevos):
                    for sema in nuevos:
                        actions_layer.referente_set_sema(
                            db_path, canonical_id, sema, "accepted"
                        )
                    st.toast(f"{len(nuevos)} sema(s) agregado(s).", icon="✅")
                    st.rerun()


def _next_canonical(
    cur_idx: int, items: list[tuple[str | None, str]]
) -> str | None:
    """Devuelve el canonical_id al que ir tras eliminar el actual."""
    # Preferir el siguiente; si era el último, ir al anterior
    if cur_idx + 1 < len(items):
        return items[cur_idx + 1][0]
    if cur_idx - 1 >= 0:
        return items[cur_idx - 1][0]
    return None


# ── Tarjeta de una marca ──────────────────────────────────────────────────────

def _render_marca_card(
    db_path: Path,
    canonical_id: str | None,
    row: pd.Series,
    items: list[tuple[str | None, str]],
) -> None:
    """Tarjeta de una marca: span + frase resaltada + estado + acciones."""
    mencion_id = int(row["mencion_id"])
    cid = row.get("canonical_id")
    marca = str(row.get("marca") or "")
    frase = str(row.get("frase") or "")
    funciones = [f for f in str(row.get("funciones") or "").split(",") if f]
    codigo = str(row.get("codigo") or "")
    unit = row.get("unit_idx")
    origin = str(row.get("origin") or "")
    status = str(row.get("status") or "")

    icon, color = _STATUS.get(status, ("", "#8a8799"))
    func_badges = "".join(
        f"<span style='font-size:0.68rem;color:{_FN_COLOR.get(f, '#8a8799')};"
        f"border:1px solid {_FN_COLOR.get(f, '#8a8799')}33;border-radius:4px;"
        f"padding:1px 6px;margin-right:4px;'>{html.escape(f)}</span>"
        for f in funciones
    )

    with st.container(border=True):
        st.markdown(
            f"<div style='display:flex;justify-content:space-between;"
            f"align-items:baseline;gap:0.6rem;flex-wrap:wrap;'>"
            f"<div><span style='font-weight:700;font-size:0.95rem;"
            f"color:#e8e4dc;'>{html.escape(marca)}</span> "
            f"<span style='color:#5a5d6e;font-size:0.72rem;"
            f"font-family:DM Mono,monospace;'>{html.escape(codigo)}·u{unit}</span>"
            f"</div>"
            f"<div style='display:flex;align-items:center;'>{func_badges}"
            f"<span style='color:{color};font-size:0.72rem;'>{icon} {status}"
            f" · {html.escape(origin)}</span></div></div>"
            f"<div style='margin-top:0.45rem;padding:0.5rem 0.7rem;"
            f"background:#15171c;border-radius:6px;font-size:0.86rem;"
            f"line-height:1.55;color:#c2bdb4;'>{_highlight(frase, marca)}</div>",
            unsafe_allow_html=True,
        )

        a1, a2, a3, a4 = st.columns([1.1, 1.1, 0.7, 3])
        # Acciones de vínculo: NO llaman st.rerun() → el rerun natural del botón
        # re-ejecuta el script con ref_sel intacto → posición preservada siempre.
        if cid:
            if a1.button("✓ aceptar", key=f"acc_{mencion_id}_{cid}",
                         use_container_width=True):
                actions_layer.mencion_accept(db_path, mencion_id, cid)
            if a2.button("✗ rechazar", key=f"rej_{mencion_id}_{cid}",
                         use_container_width=True):
                actions_layer.mencion_reject(db_path, mencion_id, cid)
            if a3.button("🗑", key=f"del_{mencion_id}_{cid}",
                         help="Quitar vínculo", use_container_width=True):
                actions_layer.mencion_remove_link(db_path, mencion_id, cid)

        # ── Reasignar a otro canónico ─────────────────────────────────────────
        with a4:
            # Lista de canónicos existentes para elegir + campo libre
            cids_existentes = [c for c, _ in items if c is not None and c != canonical_id]
            sel_existing = st.selectbox(
                "reasignar existente",
                ["— elegir existente —"] + cids_existentes,
                key=f"re_sel_{mencion_id}_{canonical_id}",
                label_visibility="collapsed",
            )
            nuevo_libre = st.text_input(
                "reasignar libre",
                key=f"re_{mencion_id}_{canonical_id}",
                label_visibility="collapsed",
                placeholder="… o escribir nuevo canónico",
            ).strip()
            # Determinar el destino: campo libre tiene prioridad si está lleno
            destino = nuevo_libre or (
                sel_existing if sel_existing != "— elegir existente —" else ""
            )
            if destino and st.button("＋ asignar",
                                     key=f"add_{mencion_id}_{canonical_id}"):
                actions_layer.mencion_add_link(db_path, mencion_id, destino)
                st.toast(f"Marca «{marca}» asignada a «{destino}».", icon="✅")


def _highlight(frase: str, marca: str) -> str:
    if not frase:
        return "<span style='color:#5a5d6e;'>(frase no disponible)</span>"
    f = html.escape(frase)
    m = html.escape(marca)
    if not m:
        return f
    idx = f.lower().find(m.lower())
    if idx == -1:
        return f
    return (
        f[:idx]
        + "<mark style='background:#3a3320;color:#f0d890;padding:0 2px;"
        f"border-radius:3px;'>{f[idx:idx + len(m)]}</mark>"
        + f[idx + len(m):]
    )
