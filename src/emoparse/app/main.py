# ══════════════════════════════════════════════════════════════════════════════
#  emoparse.app.main
#
#  Punto de entrada del dashboard Streamlit.
#
#  Renderiza el selector de run en sidebar y las tabs principales de
#  exploración sobre resultados previamente generados por el pipeline.
# ══════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

import os
from pathlib import Path

import streamlit as st

from emoparse.app.components import (
    run_selector,
    tab_actores,
    tab_comparacion,
    tab_curva,
    tab_estado,
    tab_revision,
    tab_tabla,
)
from emoparse.app.styles import CSS


#: Directorio donde se almacenan los runs (.sqlite).
#: Puede configurarse vía variable de entorno; el valor por defecto
#: mantiene la convención estándar del proyecto.
_RUNS_DIR_ENV = "EMOPARSE_RUNS_DIR"
_DEFAULT_RUNS_DIR = "runs"


def main() -> None:
    """Punto de entrada principal del dashboard Streamlit."""
    st.set_page_config(
        page_title="EmoParse",
        page_icon="🧭",
        layout="wide",
        initial_sidebar_state="expanded",
    )
    st.markdown(CSS, unsafe_allow_html=True)

    # Fuerza el sidebar siempre visible: oculta el botón de colapso nativo
    # de Streamlit (el chevron) y el backdrop que lo tapa en mobile.
    st.markdown(
        """
        <style>
        /* Oculta el botón colapsar/expandir del sidebar */
        button[data-testid="collapsedControl"],
        button[kind="header"][aria-label="Close sidebar"],
        section[data-testid="stSidebarCollapsedControl"] {
            display: none !important;
        }
        /* Garantiza que el sidebar permanezca visible */
        section[data-testid="stSidebar"] {
            transform: none !important;
            visibility: visible !important;
            width: var(--sidebar-width, 21rem) !important;
            min-width: 16rem !important;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )

    runs_dir = Path(os.environ.get(_RUNS_DIR_ENV, _DEFAULT_RUNS_DIR))

    db_path = run_selector.render(runs_dir)
    if db_path is None:
        st.markdown("# EmoParse")
        st.markdown(
            "<p style='color:#8a8799;'>Sin runs disponibles. "
            f"Ejecutá <code>emoparse run</code> para crear uno en "
            f"<code>{runs_dir}/</code>.</p>",
            unsafe_allow_html=True,
        )
        return

    st.markdown("# Resultados")
    st.markdown(
        "<p style='color:#8a8799;margin-top:-0.5rem;'>"
        "Explorá los outputs del run seleccionado.</p>",
        unsafe_allow_html=True,
    )
    st.markdown("<hr class='ep-divider'>", unsafe_allow_html=True)

    tab_curva_, tab_act, tab_tab, tab_comp, tab_rev, tab_est = st.tabs([
        "📈 Curva emocional",
        "👥 Por actor",
        "📋 Tabla",
        "↔ Comparar discursos",
        "📝 Revisión",
        "🔁 Estado del run",
    ])

    with tab_curva_:
        tab_curva.render(db_path)
    with tab_act:
        tab_actores.render(db_path)
    with tab_tab:
        tab_tabla.render(db_path)
    with tab_comp:
        tab_comparacion.render(db_path)
    with tab_rev:
        tab_revision.render(db_path)
    with tab_est:
        tab_estado.render(db_path)


if __name__ == "__main__":
    main()
