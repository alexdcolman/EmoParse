# ══════════════════════════════════════════════════════════════════════════════
#  emoparse.app.components.tab_estado
#
#  Tab de estado del run dentro del dashboard Streamlit.
#
#  Muestra el progreso de cada stage del pipeline y el estado general
#  del procesamiento, incluyendo pendientes, errores y completados.
# ══════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

from pathlib import Path
from typing import Any

import streamlit as st

from emoparse.app import actions as actions_layer
from emoparse.app import data as data_layer
from emoparse.app.revision_overlay import (
    OverlayCorruptError,
    RevisionOverlay,
    default_overlay_path,
)
from emoparse.storage.actors_kb_discoveries import ActorsKbDiscoveriesRepository
from emoparse.storage.db import Database
from emoparse.storage.experiencer_equivalences import (
    ExperiencerEquivalencesRepository,
)
from emoparse.triage.discovery_grouping import (
    group_pending_discoveries,
    slugify,
)


def render(db_path: Path) -> None:
    """Renderiza la tab de estado del run.

    Muestra el estado general del pipeline y el detalle por stage,
    incluyendo pendientes, errores y completados.
    """
    st.markdown("### Estado del run")
    st.markdown(
        "<p style='color:#8a8799;font-size:0.88rem;'>"
        "Vista read-only. Para reintentar errores, ejecutá "
        "<code>emoparse retry --db [run] --stage [stage]</code> en CLI."
        "</p>",
        unsafe_allow_html=True,
    )

    statuses = data_layer.get_stage_statuses(db_path)
    if not statuses:
        st.info("Sin stages registradas.")
        return

    total_failed = sum(s.failed for s in statuses)
    total_pending = sum(s.pending for s in statuses)
    if total_failed == 0 and total_pending == 0:
        st.markdown("""
        <div class='ep-card' style='border-left:3px solid #6ec89a;'>
            <p style='margin:0;color:#6ec89a;font-family:"DM Mono",monospace;font-size:0.85rem;'>
                ✓ Run completo. Todas las stages procesadas sin errores.
            </p>
        </div>
        """, unsafe_allow_html=True)
    else:
        st.markdown(f"""
        <div class='ep-card' style='border-left:3px solid {"#c86e6e" if total_failed else "#c8a96e"};'>
            <p style='margin:0;font-family:"DM Mono",monospace;font-size:0.85rem;'>
                <span style='color:#c86e6e;'>{total_failed} errores</span>
                <span style='color:#5a5d6e;'> · </span>
                <span style='color:#c8a96e;'>{total_pending} pendientes</span>
            </p>
        </div>
        """, unsafe_allow_html=True)

    st.markdown("<hr class='ep-divider'>", unsafe_allow_html=True)

    for s in statuses:
        _render_stage_row(s)

    _render_actors_discoveries(db_path)
    _render_experiencer_equivalences(db_path)
    _render_kb_editor(db_path)


def _render_stage_row(s: data_layer.StageStatus) -> None:
    """Renderiza una fila de estado para una stage del pipeline.

    Incluye métricas de completado, pendientes y errores, y un
    expander con los códigos fallidos cuando corresponde.
    """
    total = s.pending + s.failed + s.completed
    if total == 0:
        st.markdown(f"""
        <div style='display:flex;align-items:center;justify-content:space-between;
                    padding:0.5rem 0.8rem;border-bottom:1px solid #1a1c22;font-size:0.85rem;'>
            <span style='color:#5a5d6e;font-family:DM Mono,monospace;'>{s.stage}</span>
            <span class='badge badge-dim'>—</span>
        </div>
        """, unsafe_allow_html=True)
        return

    pct = int((s.completed / total) * 100) if total else 0

    # Encabezado reutilizable para vista simple o expander con errores.
    summary_html = (
        f"<div style='display:flex;align-items:center;gap:0.8rem;font-size:0.85rem;'>"
        f"<span style='font-family:DM Mono,monospace;color:#e8e4dc;min-width:9rem;'>{s.stage}</span>"
        f"<span class='badge {_pct_badge(pct)}'>{pct}%</span>"
        f"<span style='color:#6ec89a;font-family:DM Mono,monospace;font-size:0.78rem;'>"
        f"✓ {s.completed}</span>"
        f"<span style='color:#c8a96e;font-family:DM Mono,monospace;font-size:0.78rem;'>"
        f"⏳ {s.pending}</span>"
        f"<span style='color:#c86e6e;font-family:DM Mono,monospace;font-size:0.78rem;'>"
        f"✗ {s.failed}</span>"
        f"</div>"
    )

    if s.failed > 0 and s.failed_codigos:
        with st.expander("", expanded=False):
            st.markdown(summary_html, unsafe_allow_html=True)
            st.markdown(
                "<p style='margin:0.6rem 0 0.3rem;font-size:0.78rem;color:#8a8799;'>"
                f"Discursos con error (primeros {len(s.failed_codigos)}):"
                "</p>",
                unsafe_allow_html=True,
            )
            codigos_html = " ".join(
                f"<code style='font-size:0.72rem;color:#c86e6e;margin-right:0.4rem;'>{c}</code>"
                for c in s.failed_codigos
            )
            st.markdown(f"<div>{codigos_html}</div>", unsafe_allow_html=True)
            st.markdown(
                "<p style='margin:0.6rem 0 0;font-size:0.75rem;color:#5a5d6e;'>"
                f"Reintentar: <code>emoparse retry --stage {s.stage}</code>"
                "</p>",
                unsafe_allow_html=True,
            )
    else:
        # Sin errores: render simple sin expander.
        st.markdown(
            f"<div style='padding:0.5rem 0.8rem;border-bottom:1px solid #1a1c22;'>"
            f"{summary_html}</div>",
            unsafe_allow_html=True,
        )


def _pct_badge(pct: int) -> str:
    """Devuelve la clase visual del badge según el porcentaje completado."""
    if pct >= 100:
        return "badge-ok"
    if pct >= 50:
        return "badge-warn"
    if pct == 0:
        return "badge-dim"
    return "badge-err"


# ══════════════════════════════════════════════════════════════════════════════
#  Discoveries de la KB de actores
# ══════════════════════════════════════════════════════════════════════════════

#: Cap de discoveries listados en la UI.
#: Cantidad de discoveries por página en la UI.
_DISCOVERIES_PAGE_SIZE = 25


#: Claves de session_state para los toggles de cada sección de revisión.
#: A diferencia de st.expander (cuyo estado se resetea en cada rerun), los
#: st.toggle conservan su estado de forma independiente y robusta: abrir uno
#: no fuerza la apertura de otro, y una acción no lo cierra.
_SHOW_GROUPS = "show_actors_groups"
_SHOW_BULK = "show_actors_bulk"
_SHOW_DETAIL = "show_actors_detail"
_SHOW_EXP = "show_exp_detail"


def _section_toggle(label: str, key: str) -> bool:
    """Toggle de sección con estado propio persistente (reemplaza expanders)."""
    fn = getattr(st, "toggle", st.checkbox)
    return bool(fn(label, key=key, value=st.session_state.get(key, False)))


def _pager(total: int, key: str, page_size: int) -> tuple[int, int]:
    """Controles de paginación (‹ Anterior / Siguiente ›) + indicador.

    Guarda la página en `st.session_state[key]`, la acota al rango válido y
    devuelve el slice ``(start, end)`` a renderizar.
    """
    n_pages = max(1, (total + page_size - 1) // page_size)
    page = max(0, min(int(st.session_state.get(key, 0)), n_pages - 1))
    st.session_state[key] = page

    if n_pages > 1:
        c1, c2, c3 = st.columns([1, 2, 1])
        with c1:
            if st.button(
                "‹ Anterior", key=f"{key}_prev",
                disabled=page <= 0, use_container_width=True,
            ):
                st.session_state[key] = page - 1
                st.rerun()
        with c2:
            st.markdown(
                f"<p style='text-align:center;margin:0.3rem 0;"
                f"font-family:\"DM Mono\",monospace;font-size:0.8rem;color:#8a8799;'>"
                f"Página {page + 1} de {n_pages}</p>",
                unsafe_allow_html=True,
            )
        with c3:
            if st.button(
                "Siguiente ›", key=f"{key}_next",
                disabled=page >= n_pages - 1, use_container_width=True,
            ):
                st.session_state[key] = page + 1
                st.rerun()

    start = page * page_size
    return start, min(start + page_size, total)


def _render_actors_discoveries(db_path: Path) -> None:
    """Renderiza la sección de discoveries con triage"""
    db = Database(db_path)
    if not db.table_exists("actors_kb_discoveries"):
        return

    has_triage = db.table_exists("actors_kb_decisions")
    repo = ActorsKbDiscoveriesRepository(db)
    n_pending = repo.count_pending_review()

    st.markdown("<hr class='ep-divider'>", unsafe_allow_html=True)
    st.markdown("#### Actores nuevos (KB discoveries)")
    st.markdown(
        "<p style='color:#8a8799;font-size:0.82rem;margin-top:-0.5rem;'>"
        "Menciones marcadas <code>es_nuevo=true</code> por el agente de "
        "<code>normalize_actors</code>. Las decisiones registradas acá "
        "quedan <em>pendientes</em> hasta aplicarlas con "
        "<code>emoparse discoveries apply</code>."
        "</p>",
        unsafe_allow_html=True,
    )

    if has_triage:
        n_dec_pending = repo.count_decisions(status="pending")
        n_dec_failed = repo.count_decisions(status="failed")
        if n_dec_pending or n_dec_failed:
            bar_parts = []
            if n_dec_pending:
                bar_parts.append(
                    f"<span style='color:#c8a96e;'>{n_dec_pending} decisiones pendientes</span>"
                )
            if n_dec_failed:
                bar_parts.append(
                    f"<span style='color:#c86e6e;'>{n_dec_failed} fallidas</span>"
                )
            st.markdown(
                f"<div class='ep-card' style='border-left:3px solid #c8a96e;margin-bottom:0.6rem;'>"
                f"<p style='margin:0;font-family:\"DM Mono\",monospace;font-size:0.82rem;'>"
                f"{' · '.join(bar_parts)}"
                f"</p></div>",
                unsafe_allow_html=True,
            )
        if n_dec_pending:
            _render_actors_apply_button(db_path, n_dec_pending)

    if n_pending == 0:
        st.markdown(
            "<div class='ep-card' style='border-left:3px solid #6ec89a;'>"
            "<p style='margin:0;color:#6ec89a;font-family:\"DM Mono\",monospace;font-size:0.85rem;'>"
            "✓ Sin discoveries pendientes."
            "</p></div>",
            unsafe_allow_html=True,
        )
        return

    st.markdown(
        f"<div class='ep-card' style='border-left:3px solid #c8a96e;'>"
        f"<p style='margin:0;font-family:\"DM Mono\",monospace;font-size:0.85rem;color:#c8a96e;'>"
        f"{n_pending} discoveries pendientes de revisión"
        f"</p></div>",
        unsafe_allow_html=True,
    )

    pending = repo.list_pending_review()

    if has_triage:
        _render_discovery_groups(db_path, repo)
        _render_bulk_merge(db_path, repo)

    if _section_toggle(f"Ver detalle ({n_pending} pendientes)", _SHOW_DETAIL):
        kb_canonical_ids = _try_load_kb_ids(db_path) if has_triage else []
        if has_triage:
            # Sumar los promotes pendientes como destinos posibles del merge:
            # así se puede encolar promote A + merge B→A y aplicar en un lote.
            pend = actions_layer.pending_promote_canonical_ids(db_path)
            kb_canonical_ids = sorted(set(kb_canonical_ids) | set(pend))

        start, end = _pager(
            n_pending, "actors_disc_page", _DISCOVERIES_PAGE_SIZE,
        )
        for d in pending[start:end]:
            _render_discovery_row(
                db_path,
                d,
                repo,
                has_triage=has_triage,
                kb_canonical_ids=kb_canonical_ids,
            )


_GROUPS_PAGE_SIZE = 15
_KB_TIPOS_UI = ("individuo", "institucion", "colectivo", "desconocido")


def _render_discovery_groups(
    db_path: Path,
    repo: ActorsKbDiscoveriesRepository,
) -> None:
    """Vista de sugerencias agrupadas: menciones que parecen el mismo actor nuevo."""
    try:
        decided = {
            int(x["discovery_id"])
            for s in ("pending", "applied")
            for x in repo.list_decisions(status=s)
        }
    except Exception:
        decided = set()
    groups = [
        g
        for g in group_pending_discoveries(db_path, exclude_ids=decided)
        if g.n_members >= 2
    ]
    if not groups:
        return

    if _section_toggle(
        f"Sugerencias agrupadas ({len(groups)} grupos de ≥2 menciones)",
        _SHOW_GROUPS,
    ):
        st.caption(
            "Menciones que el modelo propone como el mismo actor nuevo. "
            "Editá el canónico si hace falta y confirmá el grupo entero "
            "(un promote + los merges)."
        )
        start, end = _pager(
            len(groups), "actors_groups_page", _GROUPS_PAGE_SIZE,
        )
        for g in groups[start:end]:
            _render_group_card(db_path, g)


def _render_group_card(db_path: Path, g) -> None:
    key = g.canonical_id
    st.markdown(
        f"<div style='font-size:0.9rem;color:#e8e4dc;margin-top:0.4rem;'>"
        f"<strong>{_escape(g.display_name)}</strong> "
        f"<span style='color:#8a8799;font-family:DM Mono,monospace;font-size:0.78rem;'>"
        f"· {g.n_members} menciones</span></div>",
        unsafe_allow_html=True,
    )
    cid = st.text_input(
        "canonical_id (slug)", value=g.canonical_id, key=f"grp_id_{key}",
        help="Slug ASCII: minúsculas, dígitos, guiones bajos.",
    )
    dn = st.text_input("display_name", value=g.display_name, key=f"grp_name_{key}")
    tipo = st.selectbox(
        "tipo", options=_KB_TIPOS_UI,
        index=_KB_TIPOS_UI.index(g.tipo) if g.tipo in _KB_TIPOS_UI else 3,
        key=f"grp_tipo_{key}",
    )

    st.markdown(
        "<p style='margin:0.4rem 0 0.1rem 0;font-size:0.78rem;color:#8a8799;'>"
        "Menciones del grupo — destildá las que no correspondan (deícticos como "
        "'yo', 'mí', 'nosotros', roles ambiguos):</p>",
        unsafe_allow_html=True,
    )
    included_ids: list[int] = []
    for m in g.members:
        mid = int(m["id"])
        label = (
            f"'{m.get('actor_mencionado', '')}'  ·  "
            f"{m.get('codigo', '')}:{m.get('unit_idx', '?')}"
        )
        if st.checkbox(label, value=True, key=f"grp_mem_{key}_{mid}"):
            included_ids.append(mid)

    discard_excluded = st.checkbox(
        "Descartar las menciones destildadas (no reaparecen)",
        value=False, key=f"grp_disc_{key}",
    )
    n_inc = len(included_ids)
    if st.button(
        f"Confirmar grupo ({n_inc} incluidas)",
        key=f"grp_btn_{key}",
        type="primary",
        disabled=n_inc == 0,
    ):
        excluded = [int(m["id"]) for m in g.members if int(m["id"]) not in included_ids]
        try:
            actions_layer.register_group_decisions(
                db_path,
                canonical_id=cid.strip(),
                display_name=dn.strip(),
                tipo=tipo,
                member_ids=included_ids,
                discard_ids=excluded if discard_excluded else None,
            )
            st.rerun()
        except (ValueError, FileNotFoundError, RuntimeError) as e:
            st.error(str(e))
    st.markdown(
        "<div style='border-bottom:1px solid #1a1c22;margin:0.5rem 0;'></div>",
        unsafe_allow_html=True,
    )


_BULK_PAGE_SIZE = 40


def _render_bulk_merge(
    db_path: Path,
    repo: ActorsKbDiscoveriesRepository,
) -> None:
    """Revisión individual rápida: merge/descarte masivo por mención exacta.

    Complementa la vista agrupada. Como el agrupamiento por canónico sugerido
    a veces parte un mismo actor en dos grupos, acá las menciones se agregan
    por texto exacto (sin importar el grupo): se busca, se seleccionan varias
    y se mergean de una a un actor de la KB. Ordenado por frecuencia.
    """
    try:
        decided = {
            int(x["discovery_id"])
            for s in ("pending", "applied")
            for x in repo.list_decisions(status=s)
        }
    except Exception:
        decided = set()
    pending = [
        d for d in repo.list_pending_review() if int(d["id"]) not in decided
    ]
    if not pending:
        return

    agg: dict[str, list[int]] = {}
    for d in pending:
        mention = str(d.get("actor_mencionado", "")).strip()
        if mention:
            agg.setdefault(mention, []).append(int(d["id"]))
    if not agg:
        return

    items = sorted(agg.items(), key=lambda kv: (-len(kv[1]), kv[0].lower()))

    if _section_toggle(
        f"Revisión individual — merge masivo ({len(items)} menciones)",
        _SHOW_BULK,
    ):
        st.caption(
            "Agregado por mención exacta, sin importar el grupo sugerido. "
            "Buscá, tildá varias (la selección se mantiene entre páginas) y "
            "mergealas a un actor de la KB. Ordenado por frecuencia (×N)."
        )

        q = st.text_input(
            "Buscar mención",
            key="bulk_search",
            placeholder="ej.: víctimas del holocausto",
        ).strip().lower()
        shown = [it for it in items if q in it[0].lower()] if q else items

        kb_ids = _try_load_kb_ids(db_path)
        kb_ids = sorted(
            set(kb_ids)
            | set(actions_layer.pending_promote_canonical_ids(db_path))
        )

        start, end = _pager(len(shown), "bulk_page", _BULK_PAGE_SIZE)
        for mention, ids in shown[start:end]:
            st.checkbox(
                f"{mention}  ·  ×{len(ids)}",
                key=f"bulk_sel_{mention}",
            )

        # Selección efectiva: todas las menciones tildadas dentro del filtro
        # actual (persisten entre páginas vía session_state).
        selected_ids: list[int] = []
        n_mentions = 0
        for mention, ids in shown:
            if st.session_state.get(f"bulk_sel_{mention}", False):
                selected_ids.extend(ids)
                n_mentions += 1
        n_sel = len(selected_ids)

        st.markdown(
            f"<p style='font-family:\"DM Mono\",monospace;font-size:0.8rem;"
            f"color:#8a8799;margin:0.3rem 0;'>"
            f"{n_mentions} menciones · {n_sel} ocurrencias seleccionadas</p>",
            unsafe_allow_html=True,
        )

        # ── Mergear a un actor existente / descartar ──
        if kb_ids:
            target = st.selectbox(
                "Mergear seleccionadas a (actor existente)",
                options=kb_ids, key="bulk_target",
            )
        else:
            target = st.text_input(
                "canonical_id destino", key="bulk_target",
                help="No se pudo cargar la KB; escribir el canónico a mano.",
            )
        tgt = (target or "").strip()
        c1, c2 = st.columns(2)
        with c1:
            if st.button(
                f"Mergear {n_sel} → {tgt or '—'}",
                key="bulk_merge_btn", type="primary",
                use_container_width=True,
                disabled=(n_sel == 0 or not tgt),
            ):
                try:
                    actions_layer.register_merge_many(
                        db_path, selected_ids, into_canonical_id=tgt,
                    )
                    _clear_bulk_selection()
                    st.rerun()
                except (ValueError, FileNotFoundError, RuntimeError) as e:
                    st.error(str(e))
        with c2:
            if st.button(
                f"Descartar {n_sel}",
                key="bulk_disc_btn",
                use_container_width=True,
                disabled=(n_sel == 0),
            ):
                try:
                    actions_layer.register_discard_many(db_path, selected_ids)
                    _clear_bulk_selection()
                    st.rerun()
                except (ValueError, FileNotFoundError, RuntimeError) as e:
                    st.error(str(e))

        # ── …o crear un actor nuevo y mergear la selección ──
        st.markdown(
            "<div style='border-top:1px solid #1a1c22;margin:0.7rem 0 0.4rem;'></div>"
            "<p style='font-size:0.82rem;color:#8a8799;margin:0;'>"
            "…o crear un actor nuevo en la KB con la selección</p>",
            unsafe_allow_html=True,
        )
        cn1, cn2 = st.columns([2, 1])
        with cn1:
            new_name = st.text_input(
                "Nombre del actor nuevo",
                key="bulk_new_name",
                placeholder="ej.: Víctimas del Holocausto",
            )
        with cn2:
            new_tipo = st.selectbox(
                "Tipo", _KB_TIPOS_UI, key="bulk_new_tipo",
            )
        new_name_clean = (new_name or "").strip()
        new_slug = slugify(new_name_clean) if new_name_clean else ""
        exists = bool(new_slug) and new_slug in set(kb_ids)
        if new_name_clean:
            if exists:
                st.warning(
                    f"Ya existe un actor `{new_slug}`. Para sumar menciones a "
                    "un actor existente usá el merge de arriba."
                )
            else:
                st.caption(f"Se creará el canónico `{new_slug}`.")
        if st.button(
            f"Crear `{new_slug or '—'}` y mergear {n_sel}",
            key="bulk_new_btn", type="primary",
            use_container_width=True,
            disabled=(n_sel == 0 or not new_slug or exists),
        ):
            try:
                actions_layer.register_group_decisions(
                    db_path,
                    canonical_id=new_slug,
                    display_name=new_name_clean,
                    tipo=new_tipo,
                    member_ids=selected_ids,
                )
                _clear_bulk_selection()
                st.session_state.pop("bulk_new_name", None)
                st.rerun()
            except (ValueError, FileNotFoundError, RuntimeError) as e:
                st.error(str(e))


def _clear_bulk_selection() -> None:
    """Limpia los checkboxes del merge masivo tras una acción."""
    for k in [k for k in st.session_state if str(k).startswith("bulk_sel_")]:
        del st.session_state[k]


def _render_actors_apply_button(db_path: Path, n_pending: int) -> None:
    """Botón para aplicar el lote de decisiones de actores a la KB (con backup)."""
    flash = st.session_state.pop("_actors_apply_flash", None)
    if flash is not None:
        _render_apply_flash(flash, backup=flash.get("backup"))

    kb_path = _resolve_kb_path(db_path)
    if kb_path is None:
        st.markdown(
            "<p style='font-size:0.78rem;color:#c86e6e;margin:0 0 0.6rem 0;'>"
            "No encontré <code>knowledge/actors_kb.json</code> cerca de la DB; "
            "aplicá desde la terminal con "
            "<code>emoparse discoveries apply --kb ...</code>."
            "</p>",
            unsafe_allow_html=True,
        )
        return

    if st.button(
        f"Aplicar {n_pending} decisiones a la KB",
        key="apply_actors_btn",
        type="primary",
    ):
        try:
            res = actions_layer.apply_actor_decisions(db_path, kb_path)
            st.session_state["_actors_apply_flash"] = res
            st.rerun()
        except (FileNotFoundError, RuntimeError) as e:
            st.error(f"No pude aplicar: {e}")


def _render_apply_flash(res: dict, *, backup: str | None) -> None:
    """Muestra el resultado de un apply (compartido actores/experienciadores)."""
    applied = res.get("applied")
    failed = res.get("failed", 0)
    if applied is not None:
        msg = f"Aplicadas {applied} decisiones."
        if backup:
            msg += f" Backup: {backup}"
        (st.warning if failed else st.success)(
            msg + (f" Fallidas: {failed}." if failed else "")
        )
        for did, err in (res.get("errors") or [])[:5]:
            st.error(f"discovery {did}: {err}")
    else:
        st.success(
            f"Aplicadas {res.get('equivalences', 0)} equivalencias "
            f"({res.get('rows', 0)} emociones actualizadas)."
        )


def _render_discovery_row(
    db_path: Path,
    d: dict,
    repo: ActorsKbDiscoveriesRepository,
    *,
    has_triage: bool,
    kb_canonical_ids: list[str],
) -> None:
    """Renderiza una fila de discovery con sus botones de triage (si aplica)."""
    confianza = str(d.get("confianza", "?"))
    badge_color = {
        "alta": "#6ec89a",
        "media": "#c8a96e",
        "baja": "#c86e6e",
    }.get(confianza, "#5a5d6e")
    contexto = (d.get("contexto") or "").strip()

    ctx_html = (
        f"<p style='margin:0.2rem 0;font-size:0.78rem;color:#8a8799;font-style:italic;'>"
        f"{_escape(contexto)}</p>"
        if contexto else ""
    )
    just_html = (
        f"<p style='margin:0.2rem 0;font-size:0.76rem;color:#5a5d6e;'>"
        f"{_escape(str(d.get('justificacion') or ''))[:200]}</p>"
        if d.get("justificacion") else ""
    )
    st.markdown(
        f"<div style='padding:0.5rem 0;border-bottom:1px solid #1a1c22;'>"
        f"<div style='display:flex;align-items:center;gap:0.6rem;font-size:0.85rem;'>"
        f"<code style='color:#e8e4dc;'>{_escape(str(d.get('actor_mencionado', '')))}</code>"
        f"<span style='color:{badge_color};font-family:DM Mono,monospace;font-size:0.75rem;'>"
        f"[{confianza}]</span>"
        f"<span style='color:#5a5d6e;font-family:DM Mono,monospace;font-size:0.75rem;'>"
        f"· {_escape(str(d.get('codigo', '')))}:{d.get('unit_idx', '?')}</span>"
        f"<span style='color:#5a5d6e;font-family:DM Mono,monospace;font-size:0.72rem;'>"
        f"· id={d['id']}</span>"
        f"</div>"
        f"{ctx_html}{just_html}"
        f"</div>",
        unsafe_allow_html=True,
    )

    if not has_triage:
        return

    decision = repo.find_decision(d["id"])
    if decision is not None:
        _render_decision_status(db_path, d, decision)
        if decision["status"] == "failed":
            st.markdown(
                "<p style='margin:0.2rem 0 0 1rem;font-size:0.76rem;color:#c8a96e;'>"
                "Corregí los campos y volvé a registrar para reintentar:</p>",
                unsafe_allow_html=True,
            )
            _render_triage_forms(db_path, d, kb_canonical_ids, prefill=decision)
        return

    _render_triage_forms(db_path, d, kb_canonical_ids)


def _render_decision_status(
    db_path: Path,
    discovery: dict,
    decision: dict,
) -> None:
    """Muestra el estado de una decisión ya registrada y permite deshacer si pending."""
    status = decision["status"]
    kind = decision["decision"]
    color_map = {
        "pending": "#c8a96e",
        "applied": "#6ec89a",
        "failed":  "#c86e6e",
    }
    color = color_map.get(status, "#5a5d6e")
    detail = ""
    if kind in ("promote", "merge") and decision.get("canonical_id"):
        detail = f" → {decision['canonical_id']}"
    st.markdown(
        f"<p style='margin:0.3rem 0 0.3rem 1rem;font-size:0.78rem;"
        f"font-family:DM Mono,monospace;color:{color};'>"
        f"[{status}] {kind}{_escape(detail)}"
        f"</p>",
        unsafe_allow_html=True,
    )
    if status == "failed" and decision.get("error_message"):
        st.markdown(
            f"<p style='margin:0 0 0.3rem 1rem;font-size:0.74rem;color:#c86e6e;'>"
            f"  {_escape(decision['error_message'])[:300]}"
            f"</p>",
            unsafe_allow_html=True,
        )

    if status in ("pending", "failed"):
        if st.button(
            "Deshacer",
            key=f"undo_{discovery['id']}",
            use_container_width=False,
        ):
            try:
                actions_layer.undo_decision(db_path, discovery["id"])
                st.rerun()
            except (ValueError, FileNotFoundError, RuntimeError) as e:
                st.error(f"No pude deshacer: {e}")


def _render_triage_forms(
    db_path: Path,
    discovery: dict,
    kb_canonical_ids: list[str],
    *,
    prefill: dict | None = None,
) -> None:
    """Renderiza los formularios de triage (promote / merge / discard).

    Si `prefill` (una decisión previa, p. ej. fallida) trae valores, se usan
    como defaults para corregir y volver a registrar.
    """
    discovery_id = discovery["id"]
    mencion = str(discovery.get("actor_mencionado", ""))
    pf_promote = prefill if (prefill and prefill.get("decision") == "promote") else None
    pf_merge_into = (
        prefill["canonical_id"]
        if (prefill and prefill.get("decision") == "merge")
        else None
    )

    tabs = st.tabs(["Promote", "Merge", "Discard"])

    # ── Promote ──
    with tabs[0]:
        sug_id = (discovery.get("canonical_id_sugerido") or "").strip()
        sug_name = (discovery.get("display_name_sugerido") or "").strip()
        sug_tipo = (discovery.get("tipo_sugerido") or "").strip().lower()
        default_id = (
            (pf_promote or {}).get("canonical_id")
            or sug_id
            or _suggest_canonical_id(mencion)
        )
        canonical_id = st.text_input(
            "canonical_id (slug)",
            value=default_id,
            key=f"prom_id_{discovery_id}",
            help="Slug ASCII: minúsculas, dígitos, guiones bajos.",
        )
        display_name = st.text_input(
            "display_name",
            value=(pf_promote or {}).get("display_name") or sug_name or mencion,
            key=f"prom_name_{discovery_id}",
        )
        col1, col2 = st.columns(2)
        tipo_opts = ("individuo", "institucion", "colectivo", "desconocido")
        pf_tipo = (pf_promote or {}).get("tipo") or (
            sug_tipo if sug_tipo in tipo_opts else None
        )
        tipo_idx = tipo_opts.index(pf_tipo) if pf_tipo in tipo_opts else 3
        with col1:
            tipo = st.selectbox(
                "tipo",
                options=tipo_opts,
                index=tipo_idx,
                key=f"prom_tipo_{discovery_id}",
            )
        with col2:
            rol = st.text_input(
                "rol (opcional)",
                value=(pf_promote or {}).get("rol") or "",
                key=f"prom_rol_{discovery_id}",
            )
        if st.button(
            "Registrar promote",
            key=f"prom_btn_{discovery_id}",
            type="primary",
        ):
            try:
                actions_layer.register_promote(
                    db_path,
                    discovery_id,
                    canonical_id=canonical_id.strip(),
                    display_name=display_name.strip(),
                    tipo=tipo,
                    rol=rol.strip() or None,
                )
                st.rerun()
            except (ValueError, FileNotFoundError, RuntimeError) as e:
                st.error(str(e))

    # ── Merge ──
    with tabs[1]:
        if kb_canonical_ids:
            merge_idx = (
                kb_canonical_ids.index(pf_merge_into)
                if pf_merge_into in kb_canonical_ids
                else 0
            )
            into = st.selectbox(
                "Mergear como alias de",
                options=kb_canonical_ids,
                index=merge_idx,
                key=f"merge_into_{discovery_id}",
            )
        else:
            into = st.text_input(
                "canonical_id destino",
                value=pf_merge_into or "",
                key=f"merge_into_{discovery_id}",
                help="No se pudo cargar la KB para autocompletar; escribir manualmente.",
            )
        if st.button(
            "Registrar merge",
            key=f"merge_btn_{discovery_id}",
            type="primary",
        ):
            try:
                actions_layer.register_merge(
                    db_path,
                    discovery_id,
                    into_canonical_id=(into or "").strip(),
                )
                st.rerun()
            except (ValueError, FileNotFoundError, RuntimeError) as e:
                st.error(str(e))

    # ── Discard ──
    with tabs[2]:
        st.markdown(
            "<p style='font-size:0.8rem;color:#8a8799;'>"
            "Marcar la mención como ruido o irrelevante. No entra a la KB."
            "</p>",
            unsafe_allow_html=True,
        )
        if st.button(
            "Registrar discard",
            key=f"disc_btn_{discovery_id}",
            type="primary",
        ):
            try:
                actions_layer.register_discard(db_path, discovery_id)
                st.rerun()
            except (ValueError, FileNotFoundError, RuntimeError) as e:
                st.error(str(e))


# ══════════════════════════════════════════════════════════════════════════════
#  Equivalencias de experienciador
# ══════════════════════════════════════════════════════════════════════════════

#: Cap de equivalencias listadas en la UI.
_EQUIVALENCES_PAGE_SIZE = 40


def _render_experiencer_equivalences(db_path: Path) -> None:
    """Sección de triage de equivalencias de experienciador."""
    db = Database(db_path)
    if not db.table_exists("experiencer_equivalences"):
        return

    repo = ExperiencerEquivalencesRepository(db)
    n_pending = repo.count_by_status("pending")
    n_accepted = repo.count_by_status("accepted")
    n_applied = repo.count_by_status("applied")

    st.markdown("<hr class='ep-divider'>", unsafe_allow_html=True)
    st.markdown("#### Experienciadores (equivalencias)")
    st.markdown(
        "<p style='color:#8a8799;font-size:0.82rem;margin-top:-0.5rem;'>"
        "Propuestas de <code>normalize_experiencers</code> para resolver cada "
        "experienciador a un referente del discurso. Al aceptar, el canónico se "
        "escribe por emoción seleccionada en el overlay de revisión (se ve en la "
        "tab <b>Revisión</b>); podés destildar emociones del grupo y buscar un "
        "canónico existente en la KB. El botón <i>Aplicar</i> además materializa "
        "lo aceptado en <code>experienciador_canonico</code> de la base (todas "
        "las ocurrencias del crudo)."
        "</p>",
        unsafe_allow_html=True,
    )

    try:
        ov: RevisionOverlay | None = RevisionOverlay(default_overlay_path(db_path))
    except OverlayCorruptError as exc:
        ov = None
        st.warning(
            "El overlay de revisión está ilegible; la aceptación no se reflejará "
            f"en la tab Revisión hasta arreglarlo: {exc}"
        )
    kb_index = _try_load_kb_index(db_path)

    if n_accepted or n_applied:
        bar = []
        if n_accepted:
            bar.append(
                f"<span style='color:#c8a96e;'>{n_accepted} aceptadas sin aplicar</span>"
            )
        if n_applied:
            bar.append(
                f"<span style='color:#6ec89a;'>{n_applied} aplicadas</span>"
            )
        st.markdown(
            f"<div class='ep-card' style='border-left:3px solid #c8a96e;margin-bottom:0.6rem;'>"
            f"<p style='margin:0;font-family:\"DM Mono\",monospace;font-size:0.82rem;'>"
            f"{' · '.join(bar)}"
            f"</p></div>",
            unsafe_allow_html=True,
        )

    flash = st.session_state.pop("_exp_apply_flash", None)
    if flash is not None:
        _render_apply_flash(flash, backup=None)

    if n_accepted:
        if st.button(
            f"Aplicar {n_accepted} equivalencias aceptadas",
            key="apply_exp_btn",
            type="primary",
        ):
            try:
                res = actions_layer.apply_experiencer_decisions(db_path)
                st.session_state["_exp_apply_flash"] = res
                st.rerun()
            except (FileNotFoundError, RuntimeError) as e:
                st.error(f"No pude aplicar: {e}")

    if n_pending == 0:
        st.markdown(
            "<div class='ep-card' style='border-left:3px solid #6ec89a;'>"
            "<p style='margin:0;color:#6ec89a;font-family:\"DM Mono\",monospace;font-size:0.85rem;'>"
            "✓ Sin equivalencias pendientes."
            "</p></div>",
            unsafe_allow_html=True,
        )
        return

    st.markdown(
        f"<div class='ep-card' style='border-left:3px solid #c8a96e;'>"
        f"<p style='margin:0;font-family:\"DM Mono\",monospace;font-size:0.85rem;color:#c8a96e;'>"
        f"{n_pending} equivalencias pendientes de revisión"
        f"</p></div>",
        unsafe_allow_html=True,
    )

    pending = repo.list_pending_review()
    if _section_toggle(f"Ver detalle ({n_pending} pendientes)", _SHOW_EXP):
        start, end = _pager(
            n_pending, "exp_equiv_page", _EQUIVALENCES_PAGE_SIZE,
        )
        for e in pending[start:end]:
            _render_equivalence_row(db, db_path, ov, kb_index, e)


def _experiencer_occurrences(
    db: Database, codigo: str, raw_experienciador: str,
) -> list[tuple[Any, str, list[tuple[Any, str]]]]:
    """Apariciones de un experienciador crudo, agrupadas por frase.

    Devuelve una lista ``(frase_idx, frase_texto, [(emocion_idx, tipo_emocion)])``
    para poder ver, en la revisión, la frase COMPLETA y a qué emoción
    corresponde cada experienciador. Lee de ``emociones`` ⋈ ``frases`` por el
    crudo (columna ``experienciador``), igual que escribe ``apply``.
    """
    try:
        rows = db.execute(
            "SELECT e.frase_idx AS fi, e.emocion_idx AS ei, "
            "e.tipo_emocion AS te, f.frase AS frase "
            "FROM emociones e "
            "LEFT JOIN frases f "
            "  ON f.codigo = e.codigo AND f.unit_idx = e.frase_idx "
            "WHERE e.codigo = ? AND e.experienciador = ? "
            "ORDER BY e.frase_idx, e.emocion_idx",
            (codigo, raw_experienciador),
        ).fetchall()
    except Exception:
        return []
    grouped: dict[Any, dict] = {}
    for r in rows:
        g = grouped.setdefault(
            r["fi"], {"frase": r["frase"] or "", "emos": []}
        )
        g["emos"].append((r["ei"], r["te"] or "—"))
    return [(fi, g["frase"], g["emos"]) for fi, g in grouped.items()]


def _occurrence_default_checked(
    ov: RevisionOverlay | None, codigo: str, fi: Any, ei: Any, any_override: bool,
) -> bool:
    """Valor inicial del checkbox de una emoción.

    Si el grupo ya tiene alguna asignación en el overlay, refleja el estado
    real (tildada solo donde hay canónico); si es la primera vez, todo tildado.
    """
    if ov is None or not any_override:
        return True
    cur = (
        ov.get_emocion(codigo, int(fi), int(ei))
        .get("overrides", {})
        .get("experienciador_canonico")
    )
    return cur is not None and str(cur) != ""


def _render_occurrence_selector(
    ov: RevisionOverlay | None,
    db: Database,
    codigo: str,
    raw: str,
    eq_id: int,
) -> list[tuple[Any, str, list[tuple[Any, str]]]]:
    """Expander con la frase COMPLETA + checkbox por emoción.

    Devuelve las ocurrencias para que ``Aceptar`` itere y lea los checkboxes.
    """
    occ = _experiencer_occurrences(db, codigo, raw)
    n_frases = len(occ)
    n_emos = sum(len(emos) for _, _, emos in occ)

    any_override = False
    if ov is not None:
        for fi, _frase, emos in occ:
            for ei, _te in emos:
                cur = (
                    ov.get_emocion(codigo, int(fi), int(ei))
                    .get("overrides", {})
                    .get("experienciador_canonico")
                )
                if cur is not None and str(cur) != "":
                    any_override = True
                    break
            if any_override:
                break

    with st.expander(
        f"Frases y emociones · {n_frases} frase(s), {n_emos} emoción(es)",
        expanded=False,
    ):
        if not occ:
            st.caption("No se encontraron emociones para este experienciador.")
            return occ

        st.markdown(
            "<p style='font-size:0.74rem;color:#5a5d6e;margin:0.2rem 0 0.1rem;'>"
            "Destildá las emociones que NO deban tomar estos canónicos:</p>",
            unsafe_allow_html=True,
        )
        for fi, frase, emos in occ:
            st.markdown(
                f"<p style='margin:0.35rem 0 0.1rem;font-size:0.7rem;color:#5a5d6e;"
                f"font-family:DM Mono,monospace;'>frase {_escape(str(fi))}</p>"
                f"<p style='margin:0 0 0.2rem;font-size:0.84rem;color:#e8e4dc;"
                f"line-height:1.4;'>"
                f"{_escape(str(frase)) or '<em>(frase no encontrada)</em>'}</p>",
                unsafe_allow_html=True,
            )
            for ei, te in emos:
                st.checkbox(
                    f"#{ei} · {te}",
                    value=_occurrence_default_checked(
                        ov, codigo, fi, ei, any_override
                    ),
                    key=f"exp_occ_{eq_id}_{fi}_{ei}",
                )
    return occ


def _resolve_canonical_list(
    kb_sel: list[str], canonical_text: str,
) -> list[str]:
    """Combina canónicos de la KB (multiselect) + libres (texto separado por ';').

    Dedupe preservando orden: primero los de la KB, luego los libres.
    """
    extras = [t.strip() for t in (canonical_text or "").split(";") if t.strip()]
    out: list[str] = []
    for x in [*kb_sel, *extras]:
        if x and x not in out:
            out.append(x)
    return out


def _canon_store_value(lst: list[str]) -> Any:
    """Valor a guardar en el overlay: '' si vacío, str si uno, lista si varios."""
    if not lst:
        return ""
    return lst[0] if len(lst) == 1 else list(lst)


def _apply_overlay_canonical(
    ov: RevisionOverlay,
    codigo: str,
    occ: list[tuple[Any, str, list[tuple[Any, str]]]],
    eq_id: int,
    value: Any,
) -> int:
    """Escribe `experienciador_canonico` (str o lista) por emoción tildada.

    Las emociones destildadas quedan sin override (se limpia por si había uno
    de una decisión anterior). Devuelve cuántas emociones recibieron canónico.
    """
    n = 0
    for fi, _frase, emos in occ:
        for ei, _te in emos:
            checked = st.session_state.get(f"exp_occ_{eq_id}_{fi}_{ei}", True)
            if checked and value:
                ov.set_emocion_override(
                    codigo, int(fi), int(ei),
                    "experienciador_canonico", value,
                )
                n += 1
            else:
                ov.clear_emocion_override(
                    codigo, int(fi), int(ei), "experienciador_canonico"
                )
    return n


def _render_equivalence_row(
    db: Database,
    db_path: Path,
    ov: RevisionOverlay | None,
    kb_index: list[dict[str, Any]],
    e: dict,
) -> None:
    """Una equivalencia pendiente: selección por emoción + KB + aceptar/rechazar."""
    eq_id = int(e["id"])
    codigo = str(e.get("codigo", ""))
    raw = str(e.get("raw_experienciador", ""))
    confianza = str(e.get("confianza", "?"))
    badge_color = {
        "alta": "#6ec89a",
        "media": "#c8a96e",
        "baja": "#c86e6e",
    }.get(confianza, "#5a5d6e")
    sugerido = e.get("canonical_sugerido") or (
        raw if e.get("clase") == "literal" else ""
    )
    just = str(e.get("justificacion") or "")
    just_html = (
        f"<p style='margin:0.2rem 0;font-size:0.76rem;color:#5a5d6e;'>"
        f"{_escape(just)[:200]}</p>" if just else ""
    )
    st.markdown(
        f"<div style='padding:0.5rem 0 0.2rem 0;border-bottom:1px solid #1a1c22;'>"
        f"<div style='display:flex;align-items:center;gap:0.6rem;font-size:0.85rem;'>"
        f"<code style='color:#e8e4dc;'>{_escape(raw)}</code>"
        f"<span style='color:#5a5d6e;'>→</span>"
        f"<span style='color:#8a8799;font-family:DM Mono,monospace;font-size:0.78rem;'>"
        f"[{_escape(str(e.get('clase', '?')))}]</span>"
        f"<span style='color:{badge_color};font-family:DM Mono,monospace;font-size:0.75rem;'>"
        f"[{confianza}]</span>"
        f"<span style='color:#5a5d6e;font-family:DM Mono,monospace;font-size:0.72rem;'>"
        f"· {_escape(codigo)} · x{e.get('ocurrencias', 0)} · id={eq_id}</span>"
        f"</div>{just_html}</div>",
        unsafe_allow_html=True,
    )

    occ = _render_occurrence_selector(ov, db, codigo, raw, eq_id)

    kb_ids = [m["id"] for m in kb_index]
    by_id = {m["id"]: m for m in kb_index}
    # Pre-carga: si la sugerencia es un id de la KB, va al multiselect; si no,
    # al campo de texto libre.
    sugerido_en_kb = sugerido in set(kb_ids)
    default_kb = [sugerido] if sugerido_en_kb else []
    default_text = "" if (sugerido_en_kb or not sugerido) else sugerido

    kb_sel: list[str] = []
    if kb_ids:
        kb_sel = st.multiselect(
            "Canónicos de la KB (podés elegir varios)",
            kb_ids,
            default=default_kb,
            key=f"exp_kbms_{eq_id}",
            format_func=lambda x: _kb_option_label(by_id[x]),
        )

    col_in, col_ok, col_no = st.columns([3, 1, 1])
    with col_in:
        canonical_text = st.text_input(
            "Otros canónicos libres (separá con ;)",
            value=default_text,
            key=f"exp_canon_{eq_id}",
            label_visibility="collapsed",
            placeholder="otros canónicos libres, separá con ;",
        )

    # Lista final resuelta AHORA (KB + libres), usada por el botón y el
    # indicador, para que coincidan siempre. Si quedó vacía pero hay sugerido,
    # se usa el sugerido (acepta de un click).
    canon_list = _resolve_canonical_list(kb_sel, canonical_text)
    if not canon_list and sugerido:
        canon_list = [sugerido]
    store_val = _canon_store_value(canon_list)
    db_canon = "; ".join(canon_list) or None

    with col_ok:
        if st.button("Aceptar", key=f"exp_acc_{eq_id}", use_container_width=True):
            try:
                actions_layer.register_experiencer_accept(
                    db_path, eq_id, canonical=db_canon
                )
                if ov is not None:
                    _apply_overlay_canonical(ov, codigo, occ, eq_id, store_val)
                st.rerun()
            except (ValueError, FileNotFoundError, RuntimeError) as exc:
                st.error(f"No pude aceptar: {exc}")
    with col_no:
        if st.button("Rechazar", key=f"exp_rej_{eq_id}", use_container_width=True):
            try:
                if ov is not None:
                    _apply_overlay_canonical(ov, codigo, occ, eq_id, "")
                actions_layer.register_experiencer_reject(db_path, eq_id)
                st.rerun()
            except (ValueError, FileNotFoundError, RuntimeError) as exc:
                st.error(f"No pude rechazar: {exc}")

    _render_destino_indicator(eq_id, occ, canon_list)


def _render_destino_indicator(
    eq_id: int,
    occ: list[tuple[Any, str, list[tuple[Any, str]]]],
    canon_list: list[str],
) -> None:
    """Muestra, antes de aceptar, qué canónicos se aplicarán y a cuántas emociones."""
    total = sum(len(emos) for _, _, emos in occ)
    seleccionadas = sum(
        1
        for fi, _frase, emos in occ
        for ei, _te in emos
        if st.session_state.get(f"exp_occ_{eq_id}_{fi}_{ei}", True)
    )
    if not canon_list:
        st.markdown(
            "<p style='margin:0.1rem 0 0.4rem;font-size:0.78rem;color:#c86e6e;'>"
            "Al aceptar: <b>sin canónico</b> — elegí de la KB o escribilo.</p>",
            unsafe_allow_html=True,
        )
        return
    chips = " ".join(
        f"<code style='color:#6ec89a;'>{_escape(c)}</code>" for c in canon_list
    )
    plural = "es" if len(canon_list) > 1 else ""
    st.markdown(
        f"<p style='margin:0.1rem 0 0.4rem;font-size:0.78rem;color:#8a8799;'>"
        f"Al aceptar: experienciador{plural} {chips} → "
        f"<b>{seleccionadas}/{total}</b> emoción(es) tildada(s).</p>",
        unsafe_allow_html=True,
    )


# ── Helpers privados ─────────────────────────────────────────────────────────

def _suggest_canonical_id(mencion: str) -> str:
    """Sugiere un canonical_id slug a partir de la mención."""
    import re
    import unicodedata
    s = unicodedata.normalize("NFD", mencion)
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    s = s.lower()
    s = re.sub(r"[^a-z0-9]+", "_", s).strip("_")
    if not s:
        return ""
    if not s[0].isalpha():
        s = "x_" + s
    return s[:64]


def _resolve_kb_path(db_path: Path) -> Path | None:
    """Ubica 'knowledge/actors_kb.json' subiendo hasta 5 niveles desde la DB."""
    cur = db_path.parent
    for _ in range(5):
        candidate = cur / "knowledge" / "actors_kb.json"
        if candidate.is_file():
            return candidate
        if cur.parent == cur:
            break
        cur = cur.parent
    return None


def _try_load_kb_ids(db_path: Path) -> list[str]:
    """Intenta cargar los canonical_ids actuales de la KB para el selectbox."""
    import json
    candidate = _resolve_kb_path(db_path)
    if candidate is None:
        return []
    try:
        data = json.loads(candidate.read_text(encoding="utf-8"))
        actors = data.get("actors") or {}
        if isinstance(actors, dict):
            return sorted(actors.keys())
    except (json.JSONDecodeError, OSError):
        return []
    return []


def _try_load_kb_index(db_path: Path) -> list[dict[str, Any]]:
    """Carga la KB como lista de {id, display_name, aliases} para buscar.

    Reusa `_resolve_kb_path`. Vacío si no se ubica o no es legible.
    """
    import json
    candidate = _resolve_kb_path(db_path)
    if candidate is None:
        return []
    try:
        data = json.loads(candidate.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []
    actors = data.get("actors") or {}
    if not isinstance(actors, dict):
        return []
    out: list[dict[str, Any]] = []
    for cid, entry in actors.items():
        entry = entry or {}
        out.append({
            "id": cid,
            "display_name": str(entry.get("display_name") or cid),
            "aliases": [str(a) for a in (entry.get("aliases") or [])],
        })
    return out


def _kb_option_label(m: dict[str, Any]) -> str:
    """Etiqueta del multiselect: id — display_name · aliases (para tipear-filtrar)."""
    base = f"{m['id']} — {m['display_name']}"
    aliases = m.get("aliases") or []
    if aliases:
        base += " · " + ", ".join(aliases[:6])
    return base


def _try_load_kb_full(db_path: Path) -> tuple[Path | None, dict[str, Any]]:
    """Devuelve (kb_path, actors_dict) crudos para el editor. ({}/None si falla)."""
    import json
    candidate = _resolve_kb_path(db_path)
    if candidate is None:
        return None, {}
    try:
        data = json.loads(candidate.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return candidate, {}
    actors = data.get("actors") or {}
    return candidate, (actors if isinstance(actors, dict) else {})


def _kb_actor_matches(actors: dict[str, Any], query: str) -> list[str]:
    """canonical_ids que matchean el query (id/display/aliases/tipo/rol)."""
    qn = _kb_norm_q(query)
    ids = sorted(actors.keys())
    if not qn:
        return ids
    toks = qn.split()
    out: list[str] = []
    for cid in ids:
        e = actors[cid] or {}
        hay = " ".join(
            _kb_norm_q(str(x))
            for x in [
                cid, e.get("display_name", ""), e.get("tipo", ""),
                e.get("rol", ""), e.get("notas", ""),
                *(e.get("aliases") or []),
            ]
        )
        if all(t in hay for t in toks):
            out.append(cid)
    return out


def _kb_norm_q(s: str) -> str:
    """Normaliza para búsqueda en el editor: minúsculas, sin tildes."""
    import unicodedata
    s = unicodedata.normalize("NFD", str(s or ""))
    return "".join(c for c in s if unicodedata.category(c) != "Mn").lower().strip()


def _render_kb_editor(db_path: Path) -> None:
    """Navegador + editor de la KB de actores y sus equivalencias (aliases).

    Edición segura: nunca cambia el `canonical_id` (no rompe referencias). Cada
    guardado hace backup + escritura atómica vía el editor de la KB.
    """
    st.markdown("<hr class='ep-divider'>", unsafe_allow_html=True)
    st.markdown("#### KB de actores (revisión y equivalencias)")

    kb_path, actors = _try_load_kb_full(db_path)
    if kb_path is None:
        st.info("No encontré `knowledge/actors_kb.json` cerca de este run.")
        return
    st.markdown(
        "<p style='color:#8a8799;font-size:0.82rem;margin-top:-0.5rem;'>"
        f"<code>{_escape(str(kb_path))}</code> · {len(actors)} actores. "
        "Podés corregir <b>display_name</b>, <b>tipo</b>, <b>rol</b>, "
        "<b>notas</b> y los <b>aliases</b> (equivalencias). El <code>canonical_id</code> "
        "no se cambia desde acá (rompería referencias). Cada guardado hace "
        "backup automático. Los cambios de nombre se reflejan en la tab Revisión."
        "</p>",
        unsafe_allow_html=True,
    )

    _render_kb_create_form(kb_path)

    query = st.text_input(
        "Buscar actor (id / nombre / alias / tipo / rol)", key="kb_search_q"
    )
    matches = _kb_actor_matches(actors, query)
    cap = 200
    shown = matches if query.strip() else matches[:cap]
    if not query.strip() and len(matches) > cap:
        st.caption(
            f"Mostrando {cap} de {len(matches)}. Usá el buscador para filtrar."
        )
    elif not matches:
        st.caption("Sin coincidencias.")

    for cid in shown:
        _render_kb_actor_row(kb_path, cid, actors[cid] or {})


def _render_kb_create_form(kb_path: Path) -> None:
    """Formulario de alta de un actor nuevo."""
    with st.expander("➕ Agregar actor nuevo", expanded=False):
        c1, c2 = st.columns(2)
        with c1:
            display_name = st.text_input("display_name", key="kb_new_dn")
        with c2:
            cid_default = _suggest_canonical_id(display_name) if display_name else ""
            canonical_id = st.text_input(
                "canonical_id (slug)", value=cid_default, key="kb_new_cid"
            )
        c3, c4 = st.columns(2)
        with c3:
            tipo = st.text_input("tipo", value="desconocido", key="kb_new_tipo")
        with c4:
            rol = st.text_input("rol (opcional)", key="kb_new_rol")
        aliases_raw = st.text_area(
            "aliases / equivalencias (uno por línea)", key="kb_new_aliases", height=80
        )
        if st.button("Crear actor", key="kb_new_btn"):
            try:
                actions_layer.kb_create_actor(
                    kb_path,
                    canonical_id=canonical_id.strip(),
                    display_name=display_name.strip(),
                    tipo=tipo.strip() or "desconocido",
                    rol=rol.strip() or None,
                    aliases=[a.strip() for a in aliases_raw.splitlines() if a.strip()],
                )
                st.success(f"Actor '{canonical_id.strip()}' creado.")
                st.rerun()
            except (ValueError, FileNotFoundError, RuntimeError) as exc:
                st.error(f"No pude crear el actor: {exc}")


def _render_kb_actor_row(kb_path: Path, cid: str, entry: dict[str, Any]) -> None:
    """Fila editable de un actor de la KB."""
    if not isinstance(entry, dict):
        entry = {}
    dn = str(entry.get("display_name") or cid)
    tipo = str(entry.get("tipo") or "")
    n_alias = len(entry.get("aliases") or [])
    with st.expander(f"{dn}  ·  {cid}  ·  {tipo or '—'}  ·  {n_alias} alias"):
        c1, c2 = st.columns(2)
        with c1:
            new_dn = st.text_input(
                "display_name", value=dn, key=f"kb_dn_{cid}"
            )
            new_tipo = st.text_input(
                "tipo", value=tipo, key=f"kb_tipo_{cid}"
            )
        with c2:
            new_rol = st.text_input(
                "rol", value=str(entry.get("rol") or ""), key=f"kb_rol_{cid}"
            )
            new_notas = st.text_input(
                "notas", value=str(entry.get("notas") or ""), key=f"kb_notas_{cid}"
            )
        new_aliases = st.text_area(
            "aliases / equivalencias (uno por línea)",
            value="\n".join(str(a) for a in (entry.get("aliases") or [])),
            key=f"kb_aliases_{cid}",
            height=110,
        )
        if st.button("Guardar", key=f"kb_save_{cid}", use_container_width=True):
            try:
                actions_layer.kb_save_actor(
                    kb_path,
                    cid,
                    display_name=new_dn,
                    tipo=new_tipo,
                    rol=new_rol,
                    notas=new_notas,
                    aliases=[a.strip() for a in new_aliases.splitlines() if a.strip()],
                )
                st.success(f"'{cid}' actualizado.")
                st.rerun()
            except (ValueError, FileNotFoundError, RuntimeError) as exc:
                st.error(f"No pude guardar: {exc}")


def _escape(s: str) -> str:
    """Escape mínimo de HTML para evitar inyección al renderizar discoveries."""
    return (
        s.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )
