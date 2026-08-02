# ══════════════════════════════════════════════════════════════════════════════
#  emoparse.app.components.tab_ejecutar
#
#  Constructor de comandos de CLI.
#
#  Arma la línea de `emoparse ...` a partir de controles y la muestra para
#  copiar y pegar en la terminal. No ejecuta nada: el pipeline es un proceso
#  largo con GPU, y lanzarlo desde Streamlit obligaría a gestionar
#  subprocesos, streaming de logs y cancelación, rompiendo además la garantía
#  de que el dashboard solo lee la DB. El valor está en no tener que recordar
#  los flags ni el orden de las stages, con la robustez de seguir corriendo
#  todo desde la CLI.
# ══════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

import shlex
from pathlib import Path

import streamlit as st


def render(db_path: Path) -> None:
    """Renderiza el constructor de comandos."""
    st.markdown("# Ejecutar")
    st.markdown(
        "<p style='color:var(--text-dim);margin-top:-0.5rem;'>"
        "Armá el comando y copialo a tu terminal. Esta sección no ejecuta "
        "nada: el pipeline corre en CLI, que es lo robusto para un proceso "
        "largo con GPU.</p>",
        unsafe_allow_html=True,
    )
    st.markdown("<hr class='ep-divider'>", unsafe_allow_html=True)

    comando = st.radio(
        "Comando",
        ["run", "network", "follows", "status", "retry"],
        horizontal=True,
        format_func=_titulo_comando,
    )
    st.markdown("<hr class='ep-divider'>", unsafe_allow_html=True)

    if comando == "run":
        cmd = _form_run(db_path)
    elif comando == "network":
        cmd = _form_network(db_path)
    elif comando == "follows":
        cmd = _form_follows(db_path)
    elif comando == "status":
        cmd = _form_status(db_path)
    else:
        cmd = _form_retry(db_path)

    _mostrar_comando(cmd)


# ══════════════════════════════════════════════════════════════════════════════
#  Formularios por comando
# ══════════════════════════════════════════════════════════════════════════════


def _form_run(db_path: Path) -> list[str]:
    """Comando `emoparse run`: config, input, género, stages."""
    generos = _generos_disponibles()
    col1, col2 = st.columns(2)
    with col1:
        config = st.text_input("Config (YAML)", value="config.yaml")
        run_id = st.text_input("Run id", value=db_path.stem)
    with col2:
        input_path = st.text_input("Input (CSV / JSON / JSONL)", value="")
        genero = st.selectbox("Género", generos, index=_indice_tuit(generos))

    default_stages, todas = _stages_del_genero(genero)
    modo = st.radio(
        "Stages",
        ["Recomendadas del género", "Elegir manualmente"],
        horizontal=True,
    )
    stages: list[str] = []
    if modo == "Elegir manualmente":
        stages = st.multiselect(
            "Stages a correr",
            todas,
            default=default_stages,
            help="El orden lo resuelve el pipeline; elegí cuáles correr. "
            "Las dependencias duras se validan al ejecutar.",
        )

    resume = st.checkbox(
        "Reanudar si la DB ya existe (--resume)",
        help="Sin esto, si la DB existe el comando pregunta o falla.",
    )

    cmd = ["emoparse", "run", "--config", config, "--run-id", run_id]
    if input_path:
        cmd += ["--input", input_path]
    cmd += ["--db", str(db_path)]
    if genero:
        cmd += ["--genre", genero]
    if stages:
        cmd += ["--stages", ",".join(stages)]
    if resume:
        cmd.append("--resume")
    if not input_path:
        st.warning("Falta el input: completá el CSV/JSON/JSONL de entrada.")
    return cmd


def _form_network(db_path: Path) -> list[str]:
    """Comando `emoparse network`: grafos y análisis.

    Los defaults se adaptan al corpus: con posts, los grafos de interacción
    vienen marcados (son lo propio de ese corpus); sin posts (discursos), los
    grafos de interacción no aplican y se preseleccionan los dos análisis de
    similitud, que sí valen para cualquier género.
    """
    from emoparse.app import data

    tiene_posts = data.has_posts(db_path)
    st.caption(
        "Grafos de interacción (requieren corpus de posts) y análisis de "
        "similitud (valen para cualquier género)."
    )
    col1, col2 = st.columns(2)
    with col1:
        grafos = st.multiselect(
            "Grafos de interacción",
            ["reply", "mention", "rt", "qt", "hashtag_co", "follow"],
            default=["reply", "mention", "rt", "qt", "hashtag_co"] if tiene_posts else [],
            help="Requieren corpus de posts. Para un corpus de discursos, "
            "dejá esto vacío y usá los análisis de similitud.",
            disabled=not tiene_posts,
        )
        cliques = st.checkbox("Cliques (vínculos recíprocos)", disabled=not tiene_posts)
        flujo = st.checkbox("Flujo emocional entre comunidades", disabled=not tiene_posts)
    with col2:
        # Sin posts, la similitud es lo único que aplica: viene marcada.
        similitud = st.checkbox("Agrupamiento narrativo (simulacros)", value=not tiene_posts)
        semantico = st.checkbox("Agrupamiento semántico (embeddings)", value=not tiene_posts)
        export = st.checkbox("Exportar a Gephi + CSV")

    cmd = ["emoparse", "network", "--db", str(db_path)]
    # --graphs '' es explícito: permite pedir solo similitud sin grafos.
    cmd += ["--graphs", ",".join(grafos)]
    if cliques:
        cmd.append("--cliques")
    if flujo:
        cmd.append("--flujo")
    if similitud:
        cmd.append("--similitud")
    if semantico:
        cmd.append("--semantico")
    if export:
        cmd += ["--export-dir", f"{db_path.stem}_export"]
    if not grafos and not (similitud or semantico):
        st.warning("Sin grafos ni análisis: marcá al menos un grafo o un agrupamiento.")
    return cmd


def _form_follows(db_path: Path) -> list[str]:
    """Comando `emoparse follows`: adquisición del grafo de seguimiento."""
    st.caption(
        "Adquiere a quién sigue cada cuenta del corpus. Es una foto del "
        "momento de la consulta; se corre una vez, no por run."
    )
    fuente = st.selectbox("Fuente", ["bluesky", "mastodon"])
    seudo = st.checkbox("Corpus seudonimizado")
    cmd = ["emoparse", "follows", "--db", str(db_path), "--source", fuente]
    if seudo:
        cmd += ["--pseudonymize", "--salt", f"{db_path}.salt", "--handles", "handles.txt"]
        st.caption(
            "Con seudonimización hacen falta los handles reales en un archivo "
            "(uno por línea): el alias es un hash y no se puede consultar."
        )
    return cmd


def _form_status(db_path: Path) -> list[str]:
    """Comando `emoparse status`."""
    st.caption("Estado de cada stage del run (también en la tab Estado).")
    return ["emoparse", "status", "--db", str(db_path)]


def _form_retry(db_path: Path) -> list[str]:
    """Comando `emoparse retry`: reintenta una stage con errores."""
    st.caption("Reintenta las unidades con error de una stage.")
    _, todas = _stages_del_genero(None)
    stage = st.selectbox("Stage a reintentar", todas)
    cmd = ["emoparse", "retry", "--db", str(db_path)]
    if stage:
        cmd += ["--stage", stage]
    return cmd


# ══════════════════════════════════════════════════════════════════════════════
#  Salida
# ══════════════════════════════════════════════════════════════════════════════


def _mostrar_comando(cmd: list[str]) -> None:
    """Muestra la línea final, lista para copiar."""
    st.markdown("<hr class='ep-divider'>", unsafe_allow_html=True)
    st.markdown("##### Comando")
    linea = " ".join(shlex.quote(p) for p in cmd)
    # st.code trae botón de copiado nativo.
    st.code(linea, language="bash")
    st.caption("Copialo y pegalo en la terminal, desde la raíz del proyecto.")


# ══════════════════════════════════════════════════════════════════════════════
#  Helpers de introspección (degradan sin romper la UI)
# ══════════════════════════════════════════════════════════════════════════════


def _titulo_comando(c: str) -> str:
    """Etiqueta legible de cada comando."""
    return {
        "run": "run — correr el pipeline",
        "network": "network — análisis de redes",
        "follows": "follows — grafo de seguimiento",
        "status": "status — estado del run",
        "retry": "retry — reintentar errores",
    }.get(c, c)


def _generos_disponibles() -> list[str]:
    """Géneros registrados, con fallback a los built-in.

    El registry puede exponer la lista con distintos nombres según versión;
    se prueban los candidatos y, si ninguno responde, se usan los built-in.
    La UI nunca se rompe por esto: es solo para poblar el selector.
    """
    import emoparse.genres as genres_mod

    for nombre in ("available_genres", "list_genres", "registered_genres"):
        fn = getattr(genres_mod, nombre, None)
        if callable(fn):
            try:
                generos = list(fn())
                if generos:
                    return sorted(str(g) for g in generos)
            except Exception:
                pass
    return ["discurso_presidencial", "tuit"]


def _indice_tuit(generos: list[str]) -> int:
    """Índice de 'tuit' si está, para preseleccionarlo; 0 si no."""
    return generos.index("tuit") if "tuit" in generos else 0


def _stages_del_genero(genero: str | None) -> tuple[list[str], list[str]]:
    """(stages por defecto, todas las stages) para poblar los controles.

    Lee el orden canónico del pipeline. Si el género se resuelve, ajusta los
    defaults con sus reglas (technoparse/emoji para tuit, sin summarizer);
    si algo falla, cae a los defaults globales sin romper la UI.
    """
    try:
        from emoparse.pipeline.runner import (
            DEFAULT_ENABLED_STAGES,
            STAGE_ORDER,
        )

        todas = list(STAGE_ORDER)
        defaults = list(DEFAULT_ENABLED_STAGES)
    except Exception:
        return [], []

    if genero:
        try:
            from emoparse.genres import get_genre

            g = get_genre(genero)
            if not g.summarizer:
                defaults = [s for s in defaults if s != "summarizer"]
            if getattr(g, "technoparse", False):
                for s in ("technoparse", "emoji_affect"):
                    if s not in defaults:
                        defaults.insert(0, s)
            invalidas = set(getattr(g, "stages_invalidas", ()))
            todas = [s for s in todas if s not in invalidas]
            defaults = [s for s in defaults if s not in invalidas]
        except Exception:
            pass
    return defaults, todas
