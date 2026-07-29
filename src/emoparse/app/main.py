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
    tab_busqueda,
    tab_comparacion,
    tab_correlacion,
    tab_curva,
    tab_deixis,
    tab_enunciacion,
    tab_estado,
    tab_referentes,
    tab_revision,
    tab_simulacros,
    tab_tabla,
)
from emoparse.app import data
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

    # Secciones de primer nivel, hermanas entre sí. "Ejecutar" es el
    # constructor de comandos; vive al nivel de "Resultados", no como una tab
    # dentro de ellos.
    with st.sidebar:
        st.markdown("<hr class='ep-divider'>", unsafe_allow_html=True)
        seccion = st.radio(
            "Sección",
            ["Resultados", "Ejecutar"],
            key="ep_seccion",
            label_visibility="collapsed",
        )

    if seccion == "Ejecutar":
        from emoparse.app.components import tab_ejecutar
        tab_ejecutar.render(db_path)
        return

    st.markdown("# Resultados")
    st.markdown(
        "<p style='color:#8a8799;margin-top:-0.5rem;'>"
        "Explorá los outputs del run seleccionado.</p>",
        unsafe_allow_html=True,
    )
    st.markdown("<hr class='ep-divider'>", unsafe_allow_html=True)

    labels = [
        "📈 Curva emocional",
        "👥 Por actor",
        "📋 Tabla",
        "↔ Comparar discursos",
        "🔎 Búsqueda",
        "🔗 Co-ocurrencia",
        "🎭 Simulacros",
        "🗣 Enunciación",
        "🧭 Deixis",
        "🏷 Referentes",
        "📝 Revisión",
        "🔁 Estado del run",
    ]
    # La tab Red aparece con corpus de posts (grafos de interacción) o cuando
    # hay grafos de similitud persistidos (semántico / simulacros), que valen
    # para cualquier género. Las de tecnodiscurso siguen siendo solo de posts.
    corpus_posts = data.has_posts(db_path)
    hay_red = corpus_posts or bool(data.list_red_grafos(db_path))
    n_fijas = len(labels)  # 12 tabs fijas de la página Resultados
    if hay_red:
        labels.append("🕸 Red")
    idx_red = n_fijas if hay_red else None
    if corpus_posts:
        labels += ["🧵 Hilos", "#️⃣ Hashtags", "✳ Tecno"]

    tabs = st.tabs(labels)
    (tab_curva_, tab_act, tab_tab, tab_comp, tab_busq, tab_corr, tab_sim,
     tab_enun, tab_dx, tab_ref, tab_rev, tab_est) = tabs[:12]

    with tab_curva_:
        tab_curva.render(db_path)
    with tab_act:
        tab_actores.render(db_path)
    with tab_tab:
        tab_tabla.render(db_path)
    with tab_comp:
        tab_comparacion.render(db_path)
    with tab_busq:
        tab_busqueda.render(db_path)
    with tab_corr:
        tab_correlacion.render(db_path)
    with tab_sim:
        tab_simulacros.render(db_path)
    with tab_enun:
        tab_enunciacion.render(db_path)
    with tab_dx:
        tab_deixis.render(db_path)
    with tab_ref:
        tab_referentes.render(db_path)
    with tab_rev:
        tab_revision.render(db_path)
    with tab_est:
        tab_estado.render(db_path)

    if idx_red is not None:
        from emoparse.app.components import tab_red
        with tabs[idx_red]:
            tab_red.render(db_path)

    if corpus_posts:
        from emoparse.app.components import (
            tab_hashtags,
            tab_hilos,
            tab_tecno,
        )
        # Las tres tabs de posts van después de Red (que ya está en labels).
        tab_hil, tab_hash, tab_tec = tabs[idx_red + 1:idx_red + 4]
        with tab_hil:
            tab_hilos.render(db_path)
        with tab_hash:
            tab_hashtags.render(db_path)
        with tab_tec:
            tab_tecno.render(db_path)


if __name__ == "__main__":
    main()
