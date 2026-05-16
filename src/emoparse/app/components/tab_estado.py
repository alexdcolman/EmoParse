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

import streamlit as st

from emoparse.app import actions as actions_layer
from emoparse.app import data as data_layer
from emoparse.storage.actors_kb_discoveries import ActorsKbDiscoveriesRepository
from emoparse.storage.db import Database


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
_DISCOVERIES_DISPLAY_CAP = 30


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
    shown = pending[:_DISCOVERIES_DISPLAY_CAP]

    with st.expander(
        f"Ver detalle (primeros {len(shown)} de {n_pending})",
        expanded=False,
    ):
        kb_canonical_ids = _try_load_kb_ids(db_path) if has_triage else []

        for d in shown:
            _render_discovery_row(
                db_path,
                d,
                repo,
                has_triage=has_triage,
                kb_canonical_ids=kb_canonical_ids,
            )

        if n_pending > _DISCOVERIES_DISPLAY_CAP:
            st.markdown(
                f"<p style='margin-top:0.6rem;font-size:0.75rem;color:#5a5d6e;'>"
                f"... y {n_pending - _DISCOVERIES_DISPLAY_CAP} más. "
                f"Listado completo: <code>emoparse discoveries list --db ...</code>."
                f"</p>",
                unsafe_allow_html=True,
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
        f"{_escape(contexto)[:180]}{'…' if len(contexto) > 180 else ''}</p>"
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

    if status == "pending":
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
) -> None:
    """Renderiza los formularios de triage (promote / merge / discard)."""
    discovery_id = discovery["id"]
    mencion = str(discovery.get("actor_mencionado", ""))

    tabs = st.tabs(["Promote", "Merge", "Discard"])

    # ── Promote ──
    with tabs[0]:
        suggested_id = _suggest_canonical_id(mencion)
        canonical_id = st.text_input(
            "canonical_id (slug)",
            value=suggested_id,
            key=f"prom_id_{discovery_id}",
            help="Slug ASCII: minúsculas, dígitos, guiones bajos.",
        )
        display_name = st.text_input(
            "display_name",
            value=mencion,
            key=f"prom_name_{discovery_id}",
        )
        col1, col2 = st.columns(2)
        with col1:
            tipo = st.selectbox(
                "tipo",
                options=("individuo", "institucion", "colectivo", "desconocido"),
                index=3,
                key=f"prom_tipo_{discovery_id}",
            )
        with col2:
            rol = st.text_input(
                "rol (opcional)",
                value="",
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
            into = st.selectbox(
                "Mergear como alias de",
                options=kb_canonical_ids,
                key=f"merge_into_{discovery_id}",
            )
        else:
            into = st.text_input(
                "canonical_id destino",
                value="",
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


def _try_load_kb_ids(db_path: Path) -> list[str]:
    """Intenta cargar los canonical_ids actuales de la KB para el selectbox."""
    import json
    # Subir hasta 4 niveles buscando 'knowledge/actors_kb.json'.
    cur = db_path.parent
    for _ in range(5):
        candidate = cur / "knowledge" / "actors_kb.json"
        if candidate.is_file():
            try:
                data = json.loads(candidate.read_text(encoding="utf-8"))
                actors = data.get("actors") or {}
                if isinstance(actors, dict):
                    return sorted(actors.keys())
            except (json.JSONDecodeError, OSError):
                return []
        if cur.parent == cur:
            break
        cur = cur.parent
    return []


def _escape(s: str) -> str:
    """Escape mínimo de HTML para evitar inyección al renderizar discoveries."""
    return (
        s.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )
