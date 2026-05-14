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

from emoparse.app import data as data_layer


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


def _render_stage_row(s: data_layer.StageStatus) -> None:
    """Renderiza una fila de estado para una stage del pipeline.

    Incluye métricas de completado, pendientes y errores, y un
    expander con los códigos fallidos cuando corresponde.
    """
    total = s.pending + s.failed + s.completed
    if total == 0:
        # Stage no aplicable para este run o aún no ejecutada.
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
