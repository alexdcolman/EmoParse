# ══════════════════════════════════════════════════════════════════════════════
#  emoparse.app.components.tab_red
#
#  Tab Red: grafos persistidos por `emoparse network` y `emoparse follows`.
#
#  Conviven tres clases de grafo, con nodos distintos: los de interacción y
#  seguimiento (nodos = cuentas), el de parecido narrativo (nodos =
#  simulacros emocionales) y el semántico (nodos = posts). El selector los
#  distingue para que no se lean como si fueran lo mismo.
# ══════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

from pathlib import Path

import pandas as pd
import streamlit as st

from emoparse.app import data
from emoparse.network import GRAFOS_AUTOR, community_emotion_profile
from emoparse.network import simulacro_similarity as sim
from emoparse.viz.network_charts import fig_perfil_forico, fig_red

#: Qué representa cada grafo, para no leer parecidos como interacciones.
_DESCRIPCIONES: dict[str, str] = {
    "reply": "cuentas que se responden",
    "mention": "cuentas que mencionan a otras",
    "rt": "cuentas que repostean a otras",
    "qt": "cuentas que citan a otras",
    "hashtag_co": "hashtags que coocurren en un post",
    "follow": "cuentas que siguen a otras (foto del momento de la captura)",
    "simulacro": "emociones con simulacros parecidos",
    "semantico": "posts con contenido parecido",
}


#: Grafos de similitud (nodos = unidades de análisis), válidos en cualquier
#: género. El resto son de interacción y presuponen corpus de posts.
_GRAFOS_SIMILITUD: frozenset[str] = frozenset({"semantico", "simulacro"})


def render(db_path: Path) -> None:
    """Renderiza la tab de red.

    Muestra tres familias de grafo, según lo que el run tenga persistido: la
    interacción entre cuentas (solo con corpus de posts), la similitud
    semántica entre unidades y el parecido entre simulacros emocionales.
    Estas dos últimas valen para cualquier género, así que la tab también
    sirve para discursos, no solo para tuits.
    """
    grafos = data.list_red_grafos(db_path)
    solo_similitud = bool(grafos) and all(g in _GRAFOS_SIMILITUD for g in grafos)
    titulo = "#### 🧬 Similitud entre unidades" if solo_similitud else "#### 🕸 Red"
    st.markdown(titulo)
    if not grafos:
        st.info(
            "Sin grafos persistidos. Corré `emoparse network --db <run>` "
            "para construirlos (requiere el extra [network]). Para "
            "similitud entre discursos: `emoparse network --db <run> "
            "--graphs '' --semantico --similitud`. El grafo de seguimiento "
            "se adquiere aparte, con `emoparse follows`."
        )
        return

    col1, col2 = st.columns([1, 3])
    with col1:
        grafo = st.selectbox(
            "Grafo",
            grafos,
            format_func=lambda g: f"{g} — {_DESCRIPCIONES[g]}" if g in _DESCRIPCIONES else g,
        )
        df_metricas = data.get_red_metricas(db_path, grafo)
        if not df_metricas.empty and df_metricas["comunidad"].notna().any():
            n_com = int(df_metricas["comunidad"].nunique())
            st.metric("Comunidades", n_com)
        st.metric("Nodos", len(df_metricas))

    df_aristas = data.get_red_aristas(db_path, grafo)
    with col2:
        try:
            st.plotly_chart(
                fig_red(
                    df_aristas,
                    df_metricas,
                    etiquetas=_etiquetas_de_nodo(db_path, grafo, df_metricas),
                ),
                use_container_width=True,
            )
        except ImportError:
            st.warning("Instalá el extra [network] para el grafo interactivo.")

    st.markdown("##### Nodos por PageRank")
    if not df_metricas.empty:
        st.dataframe(
            df_metricas[
                [
                    "nodo",
                    "grado_in",
                    "grado_out",
                    "grado_total",
                    "pagerank",
                    "intermediacion",
                    "comunidad",
                ]
            ].head(100),
            use_container_width=True,
            hide_index=True,
        )

    if grafo in GRAFOS_AUTOR:
        _perfil_comunidades(db_path, df_metricas)
    elif grafo == "simulacro":
        _grupos_narrativos(db_path, df_metricas)


#: Caracteres de texto de post que entran en el tooltip antes de cortar.
_TOOLTIP_CHARS = 220


def _etiquetas_de_nodo(
    db_path: Path, grafo: str, df_metricas: pd.DataFrame
) -> dict[str, str] | None:
    """Texto a mostrar al pasar el cursor por cada nodo del grafo.

    En los grafos de cuentas el nodo es el handle y no hace falta nada; en el
    semántico el nodo es un post_id y en el de parecido es un id de emoción,
    ambos ilegibles sin esto.
    """
    if grafo == "semantico":
        return {
            str(r["post_id"]): _envolver(str(r.get("texto") or ""))
            for r in data.get_posts(db_path).to_dict(orient="records")
        }
    if grafo == "simulacro":
        df = data.get_emociones_enriched(db_path)
        if df.empty:
            return None
        return {
            sim.clave_simulacro(r): sim.describir_simulacro(r) for r in df.to_dict(orient="records")
        }
    return None


def _envolver(texto: str) -> str:
    """Corta y parte en líneas un texto para que el tooltip sea legible."""
    limpio = " ".join(texto.split())
    if len(limpio) > _TOOLTIP_CHARS:
        limpio = limpio[:_TOOLTIP_CHARS].rsplit(" ", 1)[0] + "…"
    palabras, linea, lineas = limpio.split(" "), "", []
    for palabra in palabras:
        if len(linea) + len(palabra) + 1 > 48:
            lineas.append(linea)
            linea = palabra
        else:
            linea = f"{linea} {palabra}".strip()
    if linea:
        lineas.append(linea)
    return "<br>".join(lineas)


def _grupos_narrativos(db_path: Path, df_metricas: pd.DataFrame) -> None:
    """Qué narra cada grupo de simulacros parecidos, y qué cuentas lo enuncian.

    Los nodos del grafo son emociones (`codigo:frase_idx:emocion_idx`): se
    reconstruye a qué fila corresponde cada una para poder leer el
    agrupamiento en términos de sus componentes.
    """
    if df_metricas.empty or "comunidad" not in df_metricas.columns:
        return
    df = data.get_emociones_enriched(db_path)
    if df.empty:
        return
    registros = df.to_dict(orient="records")
    posicion = {sim.clave_simulacro(r): i for i, r in enumerate(registros)}
    grupos = {
        posicion[str(r["nodo"])]: int(r["comunidad"])
        for r in df_metricas.to_dict(orient="records")
        if str(r["nodo"]) in posicion
        and r.get("comunidad") is not None
        and not pd.isna(r["comunidad"])
    }
    if not grupos:
        return

    componentes = [c for c in sim.COMPONENTES_DEFAULT if c in sim.componentes_disponibles(df)]
    st.markdown("##### Grupos narrativos")
    st.caption(f"{len(grupos)} simulacros agrupados por parecido entre {', '.join(componentes)}.")
    st.dataframe(
        sim.perfil_grupos(df, grupos, componentes),
        use_container_width=True,
        hide_index=True,
    )

    df_posts = data.get_posts(db_path)
    if df_posts.empty:
        return
    autores = sim.grupos_por_autor(
        df,
        grupos,
        {str(r["post_id"]): str(r["autor_handle"]) for r in df_posts.to_dict(orient="records")},
    )
    if autores.empty:
        return
    st.markdown("##### Cuentas por grupo narrativo")
    grupo = st.selectbox(
        "Grupo",
        sorted(autores["grupo"].unique()),
        format_func=lambda g: f"Grupo {g}",
        key="red_grupo_narrativo",
    )
    st.dataframe(
        autores[autores["grupo"] == grupo].drop(columns=["grupo"]),
        use_container_width=True,
        hide_index=True,
    )


def _perfil_comunidades(db_path: Path, df_metricas: pd.DataFrame) -> None:
    """Perfil emocional de las comunidades de autores del grafo."""
    if df_metricas.empty:
        return
    comunidades = {
        str(r["nodo"]): int(r["comunidad"])
        for r in df_metricas.to_dict(orient="records")
        if r.get("comunidad") is not None and not pd.isna(r["comunidad"])
    }
    if not comunidades:
        return

    perfil = community_emotion_profile(
        data.get_posts(db_path), comunidades, data.get_emociones_carac(db_path)
    )
    st.markdown("##### Perfil emocional por comunidad")
    if perfil.empty:
        st.caption("Sin emociones caracterizadas en los posts de estas comunidades.")
        return

    st.plotly_chart(fig_perfil_forico(perfil), use_container_width=True)
    comunidad = st.selectbox(
        "Comunidad",
        sorted(perfil["comunidad"].unique()),
        format_func=lambda c: f"Comunidad {c}",
    )
    st.dataframe(
        perfil[perfil["comunidad"] == comunidad].drop(columns=["comunidad"]),
        use_container_width=True,
        hide_index=True,
    )
