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
#: Modalidad referencial: etiqueta corta + color.
_MOD_LABEL = {
    "designacion": "designación",
    "referencia_gramatical": "ref. gramatical",
    "identificacion_inferencial": "ident. inferencial",
}
_MOD_COLOR = {
    "designacion": "#6ec89a",
    "referencia_gramatical": "#7c9ec8",
    "identificacion_inferencial": "#c88a8a",
}
_MOD_OPCIONES = ["designacion", "referencia_gramatical", "identificacion_inferencial"]
_NAT_OPCIONES = ["persona", "colectivo", "institucion", "objeto_proceso", "otro"]
_MAX_MARCAS = 30
_MARCAS_PER_PAGE = 15           # marcas por página dentro de un referente
_MPAGE_KEY = "ref_marca_page"   # página de marcas (plain key, no widget)
_MPAGE_CID_KEY = "ref_marca_page_cid"  # referente al que pertenece la página

# Única fuente de verdad de posición: el cid activo guardado en el state del
# selectbox (`_SEL_KEY`). El selectbox usa cids estables como opciones y un
# format_func para el label, así el label puede cambiar (sube/baja n_accepted)
# sin romper la selección. prev/next/índice mutan `_SEL_KEY` y reran.
_SEL_KEY = "ref_active_cid"
_PENDING_KEY = "ref_pending_cid"  # navegación diferida (se aplica al próximo run)
_LAST_IDX_KEY = "ref_last_idx"    # índice previo (para caer al vecino, no al 1º)
_INITIAL_KEY = "ref_initial"     # filtro por inicial (índice alfabético)
_NONE_CID = "\x00sin_canonico"   # sentinel para el bucket "— sin canónico —"


def _enc(cid: str | None) -> str:
    return _NONE_CID if cid is None else str(cid)


def _dec(sel: str) -> str | None:
    return None if sel == _NONE_CID else sel


def _label_for(cid: str | None, n: int, n_accepted: int) -> str:
    if cid is None:
        return f"{_SIN_CANONICO} · {n}"
    return f"{cid} · {n} marca(s){' ✓' if n_accepted else ''}"


def _set_active(canonical_id: str | None) -> None:
    """Fija el referente activo. Diferido: se aplica al inicio del próximo run,
    para poder llamarlo también desde handlers que corren DESPUÉS del selectbox
    (merge/eliminar/renombrar) sin violar la regla de Streamlit de no modificar
    la key de un widget ya instanciado."""
    st.session_state[_PENDING_KEY] = _enc(canonical_id)


def _initial_of(cid: str) -> str:
    """Inicial para el índice alfabético: A–Z o '#' para lo demás."""
    for ch in str(cid):
        if ch.isalnum():
            return ch.upper() if ch.isalpha() else "#"
    return "#"


def render(db_path: Path) -> None:
    """Renderiza la tab de revisión de referentes, uno por vez."""
    # Aplicar navegación diferida ANTES de instanciar el selectbox.
    if _PENDING_KEY in st.session_state:
        st.session_state[_SEL_KEY] = st.session_state.pop(_PENDING_KEY)

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
    func_filter = st.multiselect(
        "Función", ["actor", "experienciador", "fuente"],
        key="ref_func_filter",
        placeholder="filtrar por función (todas)",
    )
    mod_filter = st.multiselect(
        "Modalidad", _MOD_OPCIONES,
        key="ref_mod_filter",
        format_func=lambda m: _MOD_LABEL.get(m, m),
        placeholder="filtrar por modalidad referencial (todas)",
    )
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
            # Sin st.rerun(): el rerun natural del botón preserva _SEL_KEY.

    resumen = data_layer.get_referentes_resumen(db_path, codigo)
    if resumen.empty:
        st.info(
            "No hay marcas discursivas para este run. Corré el pipeline "
            "(stage `explode_emotions`) para poblarlas."
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

    # Lista COMPLETA de canónicos (sin filtros): la usan los desplegables de
    # "elegir existente" / "destino merge", que deben mostrar todos los
    # referentes aunque el índice alfabético esté filtrando la navegación.
    all_cids = sorted({cid for cid, _ in items if cid is not None})

    _render_bulk_panel(db_path, codigo, all_cids)
    _render_merge_suggestions(db_path, codigo, all_cids)

    if func_filter:
        fset = set(func_filter)
        func_map = data_layer.get_referente_funciones(db_path, codigo)
        items = [it for it in items
                 if it[0] and (func_map.get(it[0], set()) & fset)]

    if mod_filter:
        mset = set(mod_filter)
        mod_map = data_layer.get_referente_modalidades(db_path, codigo)
        items = [it for it in items
                 if it[0] and (mod_map.get(it[0], set()) & mset)]

    if query:
        items = [it for it in items if it[0] and query in it[0].lower()]

    # ── Índice alfabético (para cientos de referentes) ────────────────────────
    inicial_sel = st.session_state.get(_INITIAL_KEY)
    iniciales = sorted({_initial_of(c) for c, _ in items if c is not None})
    if iniciales:
        st.markdown(
            "<p style='color:#5a5d6e;font-size:0.72rem;margin:0.3rem 0 0.1rem;'>"
            "Índice</p>", unsafe_allow_html=True,
        )
        fichas = ["Todos", *iniciales]
        per_row = 14
        for start in range(0, len(fichas), per_row):
            fila = fichas[start:start + per_row]
            cols = st.columns(len(fila))
            for col, letra in zip(cols, fila):
                es_todos = letra == "Todos"
                activa = (es_todos and not inicial_sel) or (letra == inicial_sel)
                if col.button(
                    letra, key=f"ref_ini_{letra}",
                    use_container_width=True,
                    type="primary" if activa else "secondary",
                ):
                    st.session_state[_INITIAL_KEY] = None if es_todos else letra
                    st.rerun()

    if inicial_sel and inicial_sel in iniciales:
        items = [it for it in items if it[0] and _initial_of(it[0]) == inicial_sel]

    if not items:
        st.info("Sin coincidencias.")
        return

    labels = [lab for _, lab in items]
    cids = [cid for cid, _ in items]
    sel_cids = [_enc(c) for c in cids]
    label_by_sel = dict(zip(sel_cids, labels))

    # ── Resolver / clampear el cid activo dentro de la lista actual ───────────
    # Si el referente activo desapareció (p. ej. al quitar su último vínculo),
    # caemos al vecino usando el índice previo, en vez de saltar al primero.
    active = st.session_state.get(_SEL_KEY)
    if active in sel_cids:
        cur = sel_cids.index(active)
    else:
        prev_idx = st.session_state.get(_LAST_IDX_KEY, 0)
        cur = min(max(prev_idx, 0), len(sel_cids) - 1)
        st.session_state[_SEL_KEY] = sel_cids[cur]
    st.session_state[_LAST_IDX_KEY] = cur

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
        if st.button("▶", key="ref_next", disabled=cur >= len(cids) - 1,
                     use_container_width=True):
            _set_active(cids[cur + 1])
            st.rerun()
    with nsel:
        # El selectbox ES la fuente de verdad: opciones = cids estables,
        # format_func para el label. Su key (_SEL_KEY) se mantiene sincronizada.
        st.selectbox(
            f"Referente {cur + 1} de {len(cids)}", sel_cids,
            format_func=lambda s: label_by_sel.get(s, s),
            key=_SEL_KEY,
            label_visibility="collapsed",
        )
    cur = sel_cids.index(st.session_state[_SEL_KEY])
    st.session_state[_LAST_IDX_KEY] = cur

    _render_referente(db_path, _dec(sel_cids[cur]), cur, items, all_cids)


# ── Render de un referente ────────────────────────────────────────────────────

_BULK_PAIRS_KEY = "ref_bulk_pairs"


def _render_bulk_panel(
    db_path: Path, codigo: str | None, all_cids: list[str]
) -> None:
    """Panel de aceptación/rechazo MASIVO de vínculos marca↔referente.

    Filtra por estado, modalidad, función (inclusiva y NEGATIVA) y referentes
    (incluir / excluir). El cálculo se dispara con un botón para no consultar la
    DB en cada rerun; los resultados quedan en session hasta recalcular/aplicar.
    """
    with st.expander("⚡ Acciones masivas", expanded=False):
        st.caption(
            "Acepta o rechaza en lote los vínculos que matcheen los filtros. "
            "Recalculá después de cambiar filtros."
        )
        c1, c2 = st.columns(2)
        with c1:
            status_src = st.selectbox(
                "Estado a afectar", ["proposed", "accepted", "rejected"],
                format_func=lambda s: {
                    "proposed": "pendientes", "accepted": "aceptados",
                    "rejected": "rechazados",
                }[s],
                key="bulk_status_src",
            )
            mods = st.multiselect(
                "Modalidad", _MOD_OPCIONES,
                format_func=lambda m: _MOD_LABEL.get(m, m),
                key="bulk_mod", placeholder="cualquiera",
            )
        with c2:
            inc_f = st.multiselect(
                "Función incluye", ["actor", "experienciador", "fuente"],
                key="bulk_incf", placeholder="cualquiera",
            )
            exc_f = st.multiselect(
                "Función NO incluye", ["actor", "experienciador", "fuente"],
                key="bulk_excf", placeholder="ninguna",
            )
        exc_ref = st.multiselect(
            "Excluir referentes (no tocar)", all_cids,
            key="bulk_excref",
            placeholder="p. ej. javier_milei, mercado",
        )
        inc_ref = st.multiselect(
            "Limitar a estos referentes (opcional)", all_cids,
            key="bulk_incref", placeholder="cualquiera",
        )

        if st.button("🔎 Calcular coincidencias", key="bulk_calc"):
            st.session_state[_BULK_PAIRS_KEY] = data_layer.bulk_links(
                db_path, codigo, status_src, mods or None,
                inc_f or None, exc_f or None, inc_ref or None, exc_ref or None,
            )
        pairs = st.session_state.get(_BULK_PAIRS_KEY, [])
        n = len(pairs)
        st.markdown(
            f"<span style='color:#c2bdb4;'>Coincidencias: <b>{n}</b> "
            f"vínculo(s).</span>", unsafe_allow_html=True,
        )
        if n:
            b1, b2, b3 = st.columns([1.2, 1.2, 1.6])
            with b1:
                if st.button(f"✓ Aceptar {n}", key="bulk_acc",
                             use_container_width=True):
                    actions_layer.bulk_set_link_status(db_path, pairs, "accepted")
                    st.session_state.pop(_BULK_PAIRS_KEY, None)
                    st.toast(f"{n} vínculos aceptados.", icon="✅")
                    st.rerun()
            with b3:
                confirm = st.checkbox("confirmar", key="bulk_confirm")
            with b2:
                if st.button(f"✗ Rechazar {n}", key="bulk_rej",
                             disabled=not confirm, use_container_width=True):
                    actions_layer.bulk_set_link_status(db_path, pairs, "rejected")
                    st.session_state.pop(_BULK_PAIRS_KEY, None)
                    st.toast(f"{n} vínculos rechazados.", icon="🗑")
                    st.rerun()


_MERGE_SUGG_KEY = "ref_merge_sugg"


def _render_merge_suggestions(
    db_path: Path, codigo: str | None, all_cids: list[str]
) -> None:
    """Panel de fusiones sugeridas de referentes casi-duplicados (escalable).

    Usa `data.suggest_referent_merges` (blocking + similitud, sin LLM). Cada
    grupo se puede fusionar (todos sus miembros → el elegido) o descartar.
    """
    with st.expander("🔗 Fusiones sugeridas", expanded=False):
        st.caption(
            "Detecta referentes casi-duplicados por similitud léxica "
            "(blocking + Jaccard/caracteres/contención). No fusiona solo: "
            "revisá cada grupo."
        )
        cc1, cc2 = st.columns([3, 1])
        with cc1:
            thr = st.slider("Umbral léxico", 0.50, 0.95, 0.62, 0.01,
                            key="merge_thr")
        with cc2:
            st.markdown("<div style='height:1.6rem;'></div>",
                        unsafe_allow_html=True)
            if st.button("🔎 Buscar", key="merge_scan",
                         use_container_width=True):
                st.session_state[_MERGE_SUGG_KEY] = \
                    data_layer.suggest_referent_merges(
                        db_path, codigo, threshold=thr,
                        use_embeddings=st.session_state.get("merge_emb", True),
                        embed_threshold=st.session_state.get("merge_embthr", 0.80),
                    )
        e1, e2 = st.columns([1, 2])
        with e1:
            st.checkbox("Semántico (embeddings)", value=True, key="merge_emb",
                        help="Suma candidatos por similitud semántica (vectores "
                             "spaCy md/lg). Capta sinónimos sin palabras en común; "
                             "revisá con cuidado (puede acercar entidades distintas).")
        with e2:
            st.slider("Umbral semántico", 0.70, 0.95, 0.80, 0.01,
                      key="merge_embthr",
                      disabled=not st.session_state.get("merge_emb", True))
        groups = st.session_state.get(_MERGE_SUGG_KEY)
        if groups is None:
            return
        if not groups:
            st.info("Sin grupos candidatos con ese umbral.")
            return
        st.markdown(f"**{len(groups)}** grupo(s) candidato(s):")
        for g in groups[:50]:
            members = g["members"]
            nm = g["n_marcas"]
            gid = "-".join(members)
            with st.container(border=True):
                st.markdown(
                    " · ".join(f"`{m}` ({nm.get(m, 0)})" for m in members)
                    + f"  ·  score {g['score']}"
                )
                # (a) tildar/destildar cada miembro sugerido.
                cols = st.columns(min(len(members), 4) or 1)
                incluidos: list[str] = []
                for k, m in enumerate(members):
                    with cols[k % len(cols)]:
                        if st.checkbox(f"{m} ({nm.get(m, 0)})", value=True,
                                       key=f"merge_chk_{gid}_{m}"):
                            incluidos.append(m)
                # (b) agregar otros referentes (fuera del grupo sugerido).
                extra = st.multiselect(
                    "agregar otros referentes a la fusión",
                    [c for c in all_cids if c not in members],
                    key=f"merge_add_{gid}", placeholder="opcional",
                )
                seleccion = incluidos + extra
                opciones = seleccion or members
                # target por defecto: el sugerido si sigue seleccionado.
                default_t = g["sugerido"] if g["sugerido"] in opciones else opciones[0]
                m1, m2, m3 = st.columns([2, 2, 1])
                with m1:
                    target = st.selectbox(
                        "fusionar en", opciones,
                        index=opciones.index(default_t),
                        key=f"merge_tgt_{gid}",
                    )
                with m2:
                    # (c) nombre canónico resultante (default = destino).
                    final_name = st.text_input(
                        "nombre resultante", value=target,
                        key=f"merge_name_{gid}",
                    ).strip()
                with m3:
                    st.markdown("<div style='height:1.7rem;'></div>",
                                unsafe_allow_html=True)
                    n_src = len([m for m in seleccion if m != target])
                    rename = bool(final_name) and final_name != target
                    if st.button("Fusionar", key=f"merge_do_{gid}",
                                 use_container_width=True,
                                 disabled=(n_src == 0 and not rename)):
                        for m in seleccion:
                            if m != target:
                                actions_layer.merge_canonicals(db_path, m, target)
                        if rename:
                            # repuntar el destino al nombre final (merge_canonicals
                            # slugifica; si el slug coincide, es no-op).
                            actions_layer.merge_canonicals(db_path, target, final_name)
                        st.session_state[_MERGE_SUGG_KEY] = [
                            x for x in (st.session_state.get(_MERGE_SUGG_KEY) or [])
                            if "-".join(x["members"]) != gid
                        ]
                        st.toast(f"Fusionado → «{final_name or target}».", icon="✅")
                        st.rerun()
                if st.button("descartar grupo", key=f"merge_skip_{gid}"):
                    st.session_state[_MERGE_SUGG_KEY] = [
                        x for x in (st.session_state.get(_MERGE_SUGG_KEY) or [])
                        if "-".join(x["members"]) != gid
                    ]
                    st.rerun()


def _render_referente(
    db_path: Path,
    canonical_id: str | None,
    cur_idx: int,
    items: list[tuple[str | None, str]],
    all_cids: list[str],
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
        _render_kb_panel(db_path, canonical_id, cur_idx, items, all_cids)
        _render_semas_panel(db_path, canonical_id)

    if marks.empty:
        st.info("Este referente ya no tiene marcas vinculadas.")
        return

    # Reset de la página al cambiar de referente (tracker por cid estable).
    cid_tok = _enc(canonical_id)
    if st.session_state.get(_MPAGE_CID_KEY) != cid_tok:
        st.session_state[_MPAGE_KEY] = 0
        st.session_state[_MPAGE_CID_KEY] = cid_tok

    only_pending = st.toggle(
        "Solo sin aceptar", value=False, key="ref_marca_only_pending",
        help="Muestra solo las marcas que todavía no aceptaste.",
    )
    if only_pending and "status" in marks.columns:
        marks = marks[marks["status"] != "accepted"]

    total = len(marks)
    if total == 0:
        st.success("No quedan marcas sin aceptar en este referente.")
        return

    per = _MARCAS_PER_PAGE
    n_pages = (total - 1) // per + 1
    # La página vive en _MPAGE_KEY (plain key); clamp por si total bajó tras
    # aceptar/quitar. No tocamos _SEL_KEY → el referente activo no se mueve.
    page = min(max(int(st.session_state.get(_MPAGE_KEY, 0)), 0), n_pages - 1)
    st.session_state[_MPAGE_KEY] = page

    if n_pages > 1:
        pp1, pp2, pp3 = st.columns([1, 3, 1])
        with pp1:
            if st.button("◀ anterior", key="ref_mprev", disabled=page == 0,
                         use_container_width=True):
                st.session_state[_MPAGE_KEY] = page - 1
                st.rerun()
        with pp3:
            if st.button("siguiente ▶", key="ref_mnext",
                         disabled=page >= n_pages - 1, use_container_width=True):
                st.session_state[_MPAGE_KEY] = page + 1
                st.rerun()
        with pp2:
            lo, hi = page * per + 1, min((page + 1) * per, total)
            st.markdown(
                f"<p style='text-align:center;color:#5a5d6e;font-size:0.8rem;'>"
                f"marcas {lo}–{hi} de {total} · página {page + 1}/{n_pages}</p>",
                unsafe_allow_html=True,
            )

    emo_brief = data_layer.get_frase_emociones_brief(db_path)
    for _, row in marks.iloc[page * per:(page + 1) * per].iterrows():
        _render_marca_card(db_path, canonical_id, row, items, all_cids, emo_brief)


def _render_kb_panel(
    db_path: Path,
    canonical_id: str,
    cur_idx: int,
    items: list[tuple[str | None, str]],
    all_cids: list[str],
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
        otros = [c for c in all_cids if c != canonical_id]
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
    """Panel de semas del referente, agrupados por su estructura jerárquica.

    Muestra las dimensiones aplicables según la `clase` actancial del referente
    (base → específicas de la clase → generales) con sus semas asignados, y
    permite quitarlos o sumar valores del vocabulario dentro de esa estructura.
    """
    with st.expander("🏷 Semas del referente", expanded=False):
        # Semas vigentes (no rechazados; `no_aplica` es relleno, se oculta).
        vig = [
            s for s in data_layer.list_canonico_semas(db_path, canonical_id)
            if s.get("status") != "rejected"
            and str(s.get("sema") or "").strip()
            and str(s.get("sema")) != "no_aplica"
        ]
        by_sema = {str(s["sema"]): s for s in vig}
        asignados = set(by_sema)

        # La clase actancial sale del propio sema de dimensión `clase`.
        clases = set(_knowledge.semas_by_dimension().get("clase") or [])
        clase = next((s for s in asignados if s in clases), None)

        estructura = _knowledge.semas_estructura(clase)
        claimed: set[str] = set()
        for dim, valores in estructura:
            # First-match en orden jerárquico: la clase resuelve los valores
            # que se repiten entre dimensiones (p. ej. `objeto`).
            recs = [by_sema[v] for v in valores if v in by_sema and v not in claimed]
            claimed.update(str(r["sema"]) for r in recs)
            _render_sema_dim(db_path, canonical_id, dim, recs)

        # Semas vigentes que no caen en ninguna dimensión aplicable.
        sobrantes = sorted(asignados - claimed)
        if sobrantes:
            _render_sema_dim(
                db_path, canonical_id, "otros",
                [by_sema[s] for s in sobrantes], muted=True,
            )

        # ── Agregar: valores aplicables no asignados, etiquetados por dimensión ─
        opciones: list[str] = []
        etiqueta: dict[str, str] = {}
        for dim, valores in estructura:
            for v in valores:
                if v not in asignados and v not in etiqueta:
                    opciones.append(v)
                    etiqueta[v] = f"{dim} · {v}"
        if opciones:
            st.divider()
            ac1, ac2 = st.columns([5, 1])
            nuevos = ac1.multiselect(
                "agregar semas", opciones,
                key=f"sema_add_{canonical_id}",
                label_visibility="collapsed",
                format_func=lambda v: etiqueta.get(v, v),
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


def _render_sema_dim(
    db_path: Path,
    canonical_id: str,
    dim: str,
    records: list[dict],
    muted: bool = False,
) -> None:
    """Fila de una dimensión: su nombre + los semas asignados (con quitar)."""
    dcol = "#5a5d6e" if muted else "#8a8799"
    st.markdown(
        f"<span style='font-size:0.72rem;color:{dcol};"
        f"font-family:DM Mono,monospace;'>{html.escape(dim)}</span>",
        unsafe_allow_html=True,
    )
    if not records:
        st.markdown(
            "<span style='font-size:0.78rem;color:#3f4250;'>— sin asignar —</span>",
            unsafe_allow_html=True,
        )
        return
    for s in records:
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
    all_cids: list[str],
    emo_brief: dict[tuple[str, int], list[dict[str, str]]] | None = None,
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
    modalidad = row.get("modalidad")
    naturaleza = row.get("naturaleza")
    mod_origin = row.get("modalidad_origin")
    if isinstance(modalidad, float) and pd.isna(modalidad):
        modalidad = None
    if isinstance(naturaleza, float) and pd.isna(naturaleza):
        naturaleza = None
    if isinstance(mod_origin, float) and pd.isna(mod_origin):
        mod_origin = None

    icon, color = _STATUS.get(status, ("", "#8a8799"))
    func_badges = "".join(
        f"<span style='font-size:0.68rem;color:{_FN_COLOR.get(f, '#8a8799')};"
        f"border:1px solid {_FN_COLOR.get(f, '#8a8799')}33;border-radius:4px;"
        f"padding:1px 6px;margin-right:4px;'>{html.escape(f)}</span>"
        for f in funciones
    )
    mod_badge = ""
    if modalidad:
        mcol = _MOD_COLOR.get(modalidad, "#8a8799")
        mlbl = _MOD_LABEL.get(modalidad, str(modalidad))
        nat_txt = f" · {html.escape(str(naturaleza))}" if naturaleza else ""
        orig_txt = {"human": " ✎", "llm": " ᴸᴸᴹ", "nlp": " ᴺᴸᴾ"}.get(
            str(mod_origin), ""
        )
        mod_badge = (
            f"<span style='font-size:0.68rem;color:{mcol};"
            f"border:1px solid {mcol}55;border-radius:4px;"
            f"padding:1px 6px;margin-right:4px;'>{html.escape(mlbl)}"
            f"{nat_txt}{orig_txt}</span>"
        )

    # Tooltip de contexto: si la marca es experienciador y/o fuente, al pasar el
    # cursor por la frase se ven las emociones de esa frase
    # (exp · emo · modo · fte).
    tip_attr = ""
    tip_hint = ""
    briefs = None
    if {"experienciador", "fuente"} & set(funciones):
        briefs = (emo_brief or {}).get((codigo, int(unit))) if unit is not None else None
        if briefs:
            lineas = [
                f"exp: {b['experienciador']}  ·  emo: {b['emocion']}"
                f"  ·  modo: {b.get('modo', '—')}  ·  fte: {b['fuente']}"
                for b in briefs
            ]
            texto = "Emociones de la frase:\n" + "\n".join(lineas)
            tip_attr = " title=\"" + html.escape(texto, quote=True).replace("\n", "&#10;") + "\""
            tip_hint = (
                "<span style='color:#5a5d6e;font-size:0.7rem;margin-left:6px;'>"
                "🛈 emociones</span>"
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
            f"<div style='display:flex;align-items:center;'>{mod_badge}{func_badges}"
            f"<span style='color:{color};font-size:0.72rem;'>{icon} {status}"
            f" · {html.escape(origin)}</span>{tip_hint}</div></div>"
            f"<div{tip_attr} style='margin-top:0.45rem;padding:0.5rem 0.7rem;"
            f"background:#15171c;border-radius:6px;font-size:0.86rem;"
            f"line-height:1.55;color:#c2bdb4;"
            f"{'cursor:help;' if tip_attr else ''}'>{_highlight(frase, marca)}</div>",
            unsafe_allow_html=True,
        )

        a1, a2, a3, a4 = st.columns([1.1, 1.1, 0.7, 3])
        # La posición vive en _SEL_KEY (que estas acciones no tocan), así que el
        # rerun refleja el cambio al instante sin perder el referente activo.
        if cid:
            if a1.button("✓ aceptar", key=f"acc_{mencion_id}_{cid}",
                         use_container_width=True):
                actions_layer.mencion_accept(db_path, mencion_id, cid)
                st.rerun()
            if a2.button("✗ rechazar", key=f"rej_{mencion_id}_{cid}",
                         use_container_width=True):
                actions_layer.mencion_reject(db_path, mencion_id, cid)
                st.rerun()
            if a3.button("🗑", key=f"del_{mencion_id}_{cid}",
                         help="Quitar vínculo", use_container_width=True):
                actions_layer.mencion_remove_link(db_path, mencion_id, cid)
                st.rerun()

        # ── Reasignar a otro canónico ─────────────────────────────────────────
        with a4:
            # Lista de canónicos existentes para elegir + campo libre
            cids_existentes = [c for c in all_cids if c != canonical_id]
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
                st.rerun()

        # ── Modalidad referencial (corrección manual) ─────────────────────────
        if cid:
            with st.expander("modalidad referencial ✎", expanded=False):
                mopts = ["(sin)"] + _MOD_OPCIONES
                nopts = ["(sin)"] + _NAT_OPCIONES
                m_idx = mopts.index(modalidad) if modalidad in mopts else 0
                n_idx = nopts.index(naturaleza) if naturaleza in nopts else 0
                mc1, mc2, mc3 = st.columns([2, 2, 1])
                with mc1:
                    new_mod = st.selectbox(
                        "modalidad", mopts, index=m_idx,
                        format_func=lambda m: _MOD_LABEL.get(m, m),
                        key=f"mod_{mencion_id}_{cid}",
                    )
                with mc2:
                    new_nat = st.selectbox(
                        "naturaleza", nopts, index=n_idx,
                        key=f"nat_{mencion_id}_{cid}",
                    )
                with mc3:
                    st.markdown("<div style='height:1.7rem;'></div>",
                                unsafe_allow_html=True)
                    if st.button("guardar", key=f"modsave_{mencion_id}_{cid}",
                                 use_container_width=True):
                        actions_layer.mencion_set_modalidad(
                            db_path, mencion_id, cid,
                            None if new_mod == "(sin)" else new_mod,
                            None if new_nat == "(sin)" else new_nat,
                        )
                        st.toast("Modalidad actualizada.", icon="✅")
                        st.rerun()

        # ── Atribución de experienciador por emoción (desarticular) ───────────
        # Cuando una frase tiene varias emociones que comparten la marca de
        # experienciador, permite atribuir el experienciador de CADA emoción por
        # separado, sin tocar el vínculo compartido de la mención.
        if "experienciador" in funciones and briefs and unit is not None:
            with st.expander("atribuir experienciador por emoción ✎", expanded=False):
                st.caption(
                    "Asigná el experienciador de cada emoción por separado. Útil "
                    "cuando la frase tiene varias emociones y solo algunas "
                    "corresponden a este referente."
                )
                cid_opts = ["— sin cambio —", "— limpiar (volver a marca) —"] + all_cids
                for b in briefs:
                    eidx = int(b["emocion_idx"])
                    fijado = bool(b.get("experienciador_fijado"))
                    ec1, ec2, ec3 = st.columns([3, 2, 1])
                    with ec1:
                        marca_txt = "✎ " if fijado else ""
                        st.markdown(
                            f"<span style='font-size:0.8rem;'>{marca_txt}#{eidx} · "
                            f"<b>{html.escape(str(b['emocion']))}</b> "
                            f"({html.escape(str(b['modo']))})</span><br>"
                            f"<span style='color:#8a8799;font-size:0.72rem;'>"
                            f"exp actual: {html.escape(str(b['experienciador']))}</span>",
                            unsafe_allow_html=True,
                        )
                    with ec2:
                        sel = st.selectbox(
                            "nuevo experienciador", cid_opts,
                            key=f"expat_sel_{mencion_id}_{eidx}",
                            label_visibility="collapsed",
                        )
                    with ec3:
                        st.markdown("<div style='height:0.15rem;'></div>",
                                    unsafe_allow_html=True)
                        if st.button("asignar", key=f"expat_btn_{mencion_id}_{eidx}",
                                     use_container_width=True):
                            if sel == "— sin cambio —":
                                st.toast("Elegí un experienciador o 'limpiar'.",
                                         icon="⚠️")
                            else:
                                destino = None if sel.startswith("— limpiar") else sel
                                actions_layer.emocion_set_experiencer_at(
                                    db_path, codigo, int(unit), eidx, destino
                                )
                                st.toast(
                                    f"Emoción #{eidx}: experienciador "
                                    + ("limpiado." if destino is None
                                       else f"→ «{destino}»."),
                                    icon="✅",
                                )
                                st.rerun()

        # ── Atribución de fuente por emoción (desarticular) ───────────────────
        if "fuente" in funciones and briefs and unit is not None:
            with st.expander("atribuir fuente por emoción ✎", expanded=False):
                st.caption(
                    "Asigná la fuente de cada emoción por separado. Útil cuando "
                    "la frase tiene varias emociones y solo algunas tienen a "
                    "este referente como fuente."
                )
                cid_opts = ["— sin cambio —", "— limpiar (volver a marca) —"] + all_cids
                for b in briefs:
                    eidx = int(b["emocion_idx"])
                    fijado = bool(b.get("fuente_fijado"))
                    fc1, fc2, fc3 = st.columns([3, 2, 1])
                    with fc1:
                        marca_txt = "✎ " if fijado else ""
                        st.markdown(
                            f"<span style='font-size:0.8rem;'>{marca_txt}#{eidx} · "
                            f"<b>{html.escape(str(b['emocion']))}</b> "
                            f"({html.escape(str(b['modo']))})</span><br>"
                            f"<span style='color:#8a8799;font-size:0.72rem;'>"
                            f"fuente actual: {html.escape(str(b['fuente']))}</span>",
                            unsafe_allow_html=True,
                        )
                    with fc2:
                        sel = st.selectbox(
                            "nueva fuente", cid_opts,
                            key=f"fteat_sel_{mencion_id}_{eidx}",
                            label_visibility="collapsed",
                        )
                    with fc3:
                        st.markdown("<div style='height:0.15rem;'></div>",
                                    unsafe_allow_html=True)
                        if st.button("asignar", key=f"fteat_btn_{mencion_id}_{eidx}",
                                     use_container_width=True):
                            if sel == "— sin cambio —":
                                st.toast("Elegí una fuente o 'limpiar'.", icon="⚠️")
                            else:
                                destino = None if sel.startswith("— limpiar") else sel
                                actions_layer.emocion_set_fuente_at(
                                    db_path, codigo, int(unit), eidx, destino
                                )
                                st.toast(
                                    f"Emoción #{eidx}: fuente "
                                    + ("limpiada." if destino is None
                                       else f"→ «{destino}»."),
                                    icon="✅",
                                )
                                st.rerun()


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
