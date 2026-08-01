# ══════════════════════════════════════════════════════════════════════════════
#  emoparse.app.components.tab_estado
#
#  Tab de estado del run dentro del dashboard Streamlit.
#
#  Muestra el progreso de cada stage del pipeline y el estado general del
#  procesamiento (pendientes, errores y completados), y ofrece el commit de la
#  revisión de experienciadores (overlay → base) con recálculo downstream.
# ══════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

from pathlib import Path

import streamlit as st

from emoparse.app import actions as actions_layer
from emoparse.app import data as data_layer


def render(db_path: Path) -> None:
    """Renderiza la tab de estado del run.

    Muestra el estado general del pipeline y el detalle por stage,
    incluyendo pendientes, errores y completados.
    """
    st.markdown("### Estado del run")
    st.markdown(
        "<p style='color:var(--text-dim);font-size:0.88rem;'>"
        "Vista read-only. El porcentaje se calcula sobre las unidades que "
        "la stage alcanza: lo marcado <code>n/a</code> queda afuera "
        "(un post sin cita no tiene reframing). Para reintentar errores, "
        "ejecutá <code>emoparse retry --db [run] --stage [stage]</code>."
        "</p>",
        unsafe_allow_html=True,
    )

    statuses = data_layer.get_stage_statuses(db_path)
    if not statuses:
        st.info("Sin stages registradas.")
        return

    total_failed = sum(s.failed for s in statuses)
    total_pending = sum(s.pending for s in statuses if s.ejecutada)
    sin_correr = [s.stage for s in statuses if not s.ejecutada]
    if total_failed == 0 and total_pending == 0:
        st.markdown("""
        <div class='ep-card' style='border-left:3px solid var(--ok);'>
            <p style='margin:0;color:var(--ok);font-family:"DM Mono",monospace;font-size:0.85rem;'>
                ✓ Run completo. Todas las stages procesadas sin errores.
            </p>
        </div>
        """, unsafe_allow_html=True)
    else:
        st.markdown(f"""
        <div class='ep-card' style='border-left:3px solid {"var(--danger)" if total_failed else "var(--accent)"};'>
            <p style='margin:0;font-family:"DM Mono",monospace;font-size:0.85rem;'>
                <span style='color:var(--danger);'>{total_failed} errores</span>
                <span style='color:var(--dim);'> · </span>
                <span style='color:var(--accent);'>{total_pending} pendientes</span>
            </p>
        </div>
        """, unsafe_allow_html=True)

    st.markdown("<hr class='ep-divider'>", unsafe_allow_html=True)

    if sin_correr:
        st.markdown(
            "<p style='color:var(--dim);font-size:0.8rem;margin:0 0 0.6rem;'>"
            "Stages que no corrieron en este run: "
            f"{', '.join(sin_correr)}."
            "</p>",
            unsafe_allow_html=True,
        )

    for s in statuses:
        _render_stage_row(s)

    _render_experiencer_commit(db_path)


def _render_stage_row(s: data_layer.StageStatus) -> None:
    """Renderiza una fila de estado para una stage del pipeline.

    Incluye completados, pendientes, errores y las unidades fuera del
    alcance de la stage, más un expander con los códigos fallidos cuando
    corresponde. Una stage sin unidades a su alcance se muestra en gris:
    o no corrió en este run, o el corpus no le daba nada que procesar.
    """
    if not s.ejecutada or s.total == 0:
        # Sin ejecución no hay porcentaje que informar: lo que falta no es
        # trabajo pendiente sino una stage que este run no corrió.
        etiqueta = "no ejecutada" if not s.ejecutada else "sin unidades"
        detalle = (
            f" · {s.total} unidades a su alcance"
            if not s.ejecutada and s.total else ""
        )
        st.markdown(f"""
        <div style='display:flex;align-items:center;justify-content:space-between;
                    padding:0.5rem 0.8rem;border-bottom:1px solid var(--border-soft);font-size:0.85rem;'>
            <span style='color:var(--dim);font-family:DM Mono,monospace;'>{s.stage}{detalle}</span>
            <span class='badge badge-dim'>{etiqueta}</span>
        </div>
        """, unsafe_allow_html=True)
        return

    pct = s.pct or 0
    # Lo que quedó fuera del alcance de la stage se muestra aparte: no es
    # trabajo pendiente y no entra en el porcentaje.
    na_html = (
        f"<span style='color:var(--dim);font-family:DM Mono,monospace;font-size:0.78rem;'>"
        f"— {s.no_aplica} n/a</span>"
        if s.no_aplica else ""
    )
    summary_html = (
        f"<div style='display:flex;align-items:center;gap:0.8rem;font-size:0.85rem;'>"
        f"<span style='font-family:DM Mono,monospace;color:var(--text);min-width:9rem;'>{s.stage}</span>"
        f"<span class='badge {_pct_badge(pct)}'>{pct}%</span>"
        f"<span style='color:var(--ok);font-family:DM Mono,monospace;font-size:0.78rem;'>"
        f"✓ {s.completed}</span>"
        f"<span style='color:var(--accent);font-family:DM Mono,monospace;font-size:0.78rem;'>"
        f"⏳ {s.pending}</span>"
        f"<span style='color:var(--danger);font-family:DM Mono,monospace;font-size:0.78rem;'>"
        f"✗ {s.failed}</span>"
        f"{na_html}"
        f"<span style='color:var(--dim);font-size:0.74rem;'>{s.unidad}</span>"
        f"</div>"
    )

    if s.failed > 0 and s.failed_codigos:
        with st.expander("", expanded=False):
            st.markdown(summary_html, unsafe_allow_html=True)
            st.markdown(
                "<p style='margin:0.6rem 0 0.3rem;font-size:0.78rem;color:var(--text-dim);'>"
                f"Discursos con error (primeros {len(s.failed_codigos)}):"
                "</p>",
                unsafe_allow_html=True,
            )
            codigos_html = " ".join(
                f"<code style='font-size:0.72rem;color:var(--danger);margin-right:0.4rem;'>{c}</code>"
                for c in s.failed_codigos
            )
            st.markdown(f"<div>{codigos_html}</div>", unsafe_allow_html=True)
            st.markdown(
                "<p style='margin:0.6rem 0 0;font-size:0.75rem;color:var(--dim);'>"
                f"Reintentar: <code>emoparse retry --stage {s.stage}</code>"
                "</p>",
                unsafe_allow_html=True,
            )
    else:
        st.markdown(
            f"<div style='padding:0.5rem 0.8rem;border-bottom:1px solid var(--border-soft);'>"
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


def _render_experiencer_commit(db_path: Path) -> None:
    """Commit del overlay de experienciadores (revisión por emoción) → base.

    Materializa el experienciador revisado en `emociones.experienciador_canonico`
    e invalida characterizer/actants/judge de lo que cambió, para recálculo en la
    próxima corrida.
    """
    st.markdown("<hr class='ep-divider'>", unsafe_allow_html=True)
    st.markdown("#### Revisión de experienciadores")

    commit_flash = st.session_state.pop("_exp_commit_flash", None)
    if commit_flash is not None:
        st.success(
            f"Commit: {commit_flash['emociones']} emociones, "
            f"{commit_flash['changed']} cambiadas, "
            f"{commit_flash['invalidated']} marcadas para recálculo "
            f"(characterizer / actants), "
            f"{commit_flash.get('judge_invalidated', 0)} juicios invalidados."
        )

    if st.button(
        "Commit revisión → base (propagar a downstream)",
        key="commit_exp_btn",
        help=(
            "Materializa el experienciador revisado por emoción (overlay) en "
            "emociones.experienciador_canonico e invalida characterizer/actants/"
            "judge de las emociones que cambiaron, para que se recalculen en la "
            "próxima corrida. Corré characterizer/actants/judge DESPUÉS de esto."
        ),
    ):
        try:
            res = actions_layer.commit_experiencers_overlay(db_path)
            st.session_state["_exp_commit_flash"] = res
            st.rerun()
        except (FileNotFoundError, RuntimeError) as e:
            st.error(f"No pude commitear: {e}")
    st.caption(
        "El commit propaga la revisión humana a characterizer / actants / judge "
        "(que prefieren el canónico) e invalida sus salidas para las emociones "
        "que cambiaron, de modo que se recalculen en la próxima corrida. La "
        "agrupación de marcas y referentes se revisa en la tab Referentes."
    )
