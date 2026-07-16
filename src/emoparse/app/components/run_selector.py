# ══════════════════════════════════════════════════════════════════════════════
#  emoparse.app.components.run_selector
#
#  Selector de run activo y resumen de métricas del run.
# ══════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

from pathlib import Path

import streamlit as st

from emoparse.app import data as data_layer


def render(runs_dir: Path) -> Path | None:
    """Renderiza el sidebar y devuelve el `db_path` del run seleccionado.

    Devuelve `None` si no hay runs disponibles.
    """
    st.sidebar.markdown("""
    <div style='padding: 1.2rem 0.5rem 1rem;'>
        <div style='font-family:"DM Serif Display",serif; font-size:1.5rem; color:#c8a96e; letter-spacing:-0.02em;'>
            🧭 EmoParse
        </div>
        <div style='font-family:"DM Mono",monospace; font-size:0.7rem; color:#5a5d6e; margin-top:0.1rem;'>
            v0.6.1 · análisis discursivo
        </div>
    </div>
    <hr style='border-color:#252730; margin: 0 0 1rem;'>
    """, unsafe_allow_html=True)

    runs = data_layer.list_runs(runs_dir)
    if not runs:
        st.sidebar.markdown(f"""
        <div class='ep-card' style='border-left:3px solid #c86e6e;'>
            <p style='margin:0;font-size:0.85rem;color:#c86e6e;'>Sin runs.</p>
            <p style='margin:0.4rem 0 0;font-size:0.78rem;color:#8a8799;'>
                Ejecutá <code>emoparse run</code> para crear un run en
                <code>{runs_dir}/</code>.
            </p>
        </div>
        """, unsafe_allow_html=True)
        return None

    # El selectbox muestra una etiqueta formateada, pero devuelve
    # el objeto `RunInfo` completo mediante `format_func`.
    selected = st.sidebar.selectbox(
        "Run",
        options=runs,
        format_func=_format_run_option,
        key="emoparse_run_selector",
    )

    st.sidebar.markdown("<hr style='border-color:#252730; margin: 1rem 0;'>", unsafe_allow_html=True)

    _render_run_stats(selected.path)
    return selected.path


def _format_run_option(run: data_layer.RunInfo) -> str:
    badge = ""
    if run.status == "completed":
        badge = " ✓"
    elif run.status == "failed":
        badge = " ✗"
    elif run.status == "running":
        badge = " ◐"
    return f"{run.name}{badge}"


def _render_run_stats(db_path: Path) -> None:
    """Renderiza métricas y metadata del run activo en el sidebar."""
    try:
        stats = data_layer.get_run_stats(db_path)
    except Exception as e:  # pragma: no cover — defensa contra DB corrupta
        st.sidebar.error(f"No se pudo leer el run: {e}")
        return

    status = stats.get("status") or "—"
    badge_class = {
        "completed": "badge-ok",
        "failed":    "badge-err",
        "running":   "badge-warn",
    }.get(status, "badge-dim")

    st.sidebar.markdown(f"""
    <div class='ep-card ep-card-accent' style='padding:0.9rem 1rem;'>
        <div style='font-family:"DM Mono",monospace;font-size:0.7rem;color:#5a5d6e;'>RUN</div>
        <div style='font-family:"DM Mono",monospace;font-size:0.85rem;color:#e8e4dc;
                    word-break:break-all;line-height:1.3;margin-top:0.2rem;'>
            {stats.get("run_id") or "—"}
        </div>
        <div style='margin-top:0.5rem;'>
            <span class='badge {badge_class}'>{status}</span>
        </div>
    </div>
    """, unsafe_allow_html=True)

    n_d = stats.get("n_discursos", 0)
    n_f = stats.get("n_frases", 0)
    n_e = stats.get("n_emociones", 0)
    st.sidebar.markdown(f"""
    <div class='stat-grid' style='margin-bottom:1rem;'>
        <div class='stat-box' style='padding:0.7rem 0.9rem;'>
            <div class='stat-val' style='font-size:1.2rem;'>{n_d}</div>
            <div class='stat-lbl'>Discursos</div>
        </div>
        <div class='stat-box' style='padding:0.7rem 0.9rem;'>
            <div class='stat-val' style='font-size:1.2rem;'>{n_f}</div>
            <div class='stat-lbl'>Frases</div>
        </div>
        <div class='stat-box' style='padding:0.7rem 0.9rem;'>
            <div class='stat-val' style='font-size:1.2rem;'>{n_e}</div>
            <div class='stat-lbl'>Emociones</div>
        </div>
    </div>
    """, unsafe_allow_html=True)

    versions = [
        ("knowledge", stats.get("knowledge_version")),
        ("prompt",    stats.get("prompt_version")),
        ("ontology",  stats.get("ontology_version")),
        ("schema",    stats.get("schema_version")),
    ]
    rows = "".join(
        f"<div style='display:flex;justify-content:space-between;"
        f"font-size:0.75rem;padding:0.15rem 0;'>"
        f"<span style='color:#5a5d6e;'>{name}</span>"
        f"<span style='font-family:DM Mono,monospace;color:#8a8799;'>{val or '—'}</span>"
        f"</div>"
        for name, val in versions
    )
    st.sidebar.markdown(f"""
    <div style='margin-top:0.4rem;'>
        <div style='font-size:0.7rem;color:#5a5d6e;font-family:DM Mono,monospace;
                    text-transform:uppercase;letter-spacing:0.06em;margin-bottom:0.3rem;'>
            VERSIONS
        </div>
        {rows}
    </div>
    """, unsafe_allow_html=True)

    if stats.get("notes"):
        st.sidebar.markdown(f"""
        <details style='margin-top:0.8rem;'>
            <summary style='font-size:0.75rem;color:#8a8799;cursor:pointer;'>Notas</summary>
            <pre style='font-size:0.75rem;color:#8a8799;white-space:pre-wrap;
                        margin-top:0.4rem;'>{stats["notes"]}</pre>
        </details>
        """, unsafe_allow_html=True)
