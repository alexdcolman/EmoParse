# ══════════════════════════════════════════════════════════════════════════════
#  emoparse.app.components.tab_hilos
#
#  Tab Hilos y citas: árbol conversacional navegable y vista de la
#  redocumentación (citas y reposts con comentario) del corpus entero.
#
#  Las dos vistas comparten el render de post porque son el mismo objeto
#  leído por dos criterios distintos: una respuesta pertenece a un hilo, una
#  cita no lo crea. Sin la segunda vista, los resultados de la stage
#  `reframing` quedan fuera de alcance del dashboard.
# ══════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

import html
from pathlib import Path

import pandas as pd
import streamlit as st

from emoparse.app import data
from emoparse.viz import foria as foria_viz

#: Tamaño de página de la vista de citas (el corpus entero no se pinta).
_PAGINA = 25

#: Sangría por nivel del árbol y tope de niveles indentados: más allá, el
#: ancho útil se come el texto de los posts.
_SANGRIA_PX = 22
_NIVEL_MAX = 8

#: Etiquetas visibles de la operación de reframing.
_OPERACIONES: dict[str, str] = {
    "adhesion": "adhesión",
    "ironia_distancia": "ironía / distancia",
    "denuncia": "denuncia",
    "neutra_informativa": "difusión neutra",
    "ambigua": "ambigua",
}

#: Qué hace el citador con el afecto de lo que cita. `ninguna` es el valor
#: del vocabulario anterior: se traduce para que los runs viejos se lean.
_EMOCIONES_CITADAS: dict[str, str] = {
    "asumidas": "afecto citado: asumido",
    "semiotizadas": "afecto citado: semiotizado",
    "no_retomadas": "afecto citado: no retomado",
    "ninguna": "afecto citado: no retomado",
}

#: Sobre qué se clasificó cada cita. Lo calcula la stage, no el modelo.
_EVIDENCIA: dict[str, str] = {
    "en_corpus": "citado en el corpus",
    "embebida": "citado por copia embebida",
    "ausente": "citado no disponible",
}

#: Tipos de post ofrecidos como filtro, en orden de lectura.
_TIPOS = ("original", "respuesta", "cita", "repost")


def render(db_path: Path) -> None:
    """Renderiza la tab de hilos y citas."""
    st.markdown("#### 🧵 Hilos y citas")
    st.caption(
        "La barra de color a la izquierda de cada post es su **foria "
        "dominante** (la misma paleta de la leyenda, abajo a la izquierda). "
        "Los posts que citan o repostean llevan además el chip de la "
        "operación de redocumentación clasificada por la stage `reframing`. "
        "Un citado marcado *fuera del corpus* se muestra desde el payload "
        "del citador: se lee, pero no fue analizado."
    )

    vista = st.radio(
        "Vista",
        ["Hilo conversacional", "Citas y reposts"],
        horizontal=True,
        key="hilos_vista",
        label_visibility="collapsed",
    )
    st.markdown("<hr class='ep-divider'>", unsafe_allow_html=True)
    if vista == "Hilo conversacional":
        _render_hilos(db_path)
    else:
        _render_citas(db_path)


# ══════════════════════════════════════════════════════════════════════════════
#  Vista de hilo
# ══════════════════════════════════════════════════════════════════════════════

def _render_hilos(db_path: Path) -> None:
    """Árbol de una conversación, ordenado por descendencia."""
    col_inc, col_sel = st.columns([1, 3])
    with col_inc:
        incluir_solos = st.toggle(
            "Incluir conversaciones de un post",
            value=False,
            key="hilos_solos",
            help=(
                "Una cita o un repost no abren conversación: quedan como "
                "hilo de un solo post."
            ),
        )
    df_hilos = data.get_hilos(db_path, min_posts=1 if incluir_solos else 2)
    if df_hilos.empty:
        st.info("El corpus no tiene conversaciones registradas.")
        return

    opciones = {
        f"{h['conversacion_id']}  ({h['n_posts']} posts, "
        f"prof. {h['profundidad_max']})": h["conversacion_id"]
        for _, h in df_hilos.iterrows()
    }
    with col_sel:
        etiqueta = st.selectbox("Conversación", list(opciones), key="hilos_conv")
    conversacion_id = opciones[etiqueta]

    df_posts = data.get_posts_de_hilo(db_path, conversacion_id)
    if df_posts.empty:
        st.warning("Sin posts capturados para esa conversación.")
        return

    df_posts = _panel_filtros(df_posts, key="hilos")
    if df_posts.empty:
        st.info("Ningún post del hilo pasa los filtros.")
        return

    citados, emociones = _citados_de(db_path, df_posts)
    st.caption(f"{len(df_posts)} post(s) en la vista.")
    for post, nivel in _orden_arbol(df_posts):
        _render_post(
            db_path, post, nivel=nivel, citados=citados, emociones=emociones,
        )


# ══════════════════════════════════════════════════════════════════════════════
#  Vista de citas y reposts
# ══════════════════════════════════════════════════════════════════════════════

def _render_citas(db_path: Path) -> None:
    """Posts que citan o repostean del corpus entero, con su reframing."""
    df = data.get_posts_citadores(db_path)
    if df.empty:
        st.info("El corpus no contiene citas ni reposts.")
        return

    df["operacion"] = df["reframing"].map(
        lambda r: str(r.get("operacion")) if isinstance(r, dict) else None
    )
    df["evidencia"] = df["reframing"].map(
        lambda r: str(r.get("evidencia_citada") or "")
        if isinstance(r, dict) else ""
    )
    _resumen_operaciones(df)

    col_op, col_ev, col_est = st.columns([2, 1.4, 1])
    with col_op:
        presentes = [o for o in _OPERACIONES if o in set(df["operacion"])]
        sel_op = st.multiselect(
            "Operación de redocumentación",
            presentes,
            format_func=lambda o: _OPERACIONES.get(o, o),
            key="citas_op",
        )
    with col_ev:
        # La calidad de la evidencia es una variable del análisis, no una
        # nota al pie: una cita clasificada sobre copia embebida no es lo
        # mismo que una clasificada sobre un post analizado.
        evidencias = [e for e in _EVIDENCIA if e in set(df["evidencia"])]
        sel_ev = st.multiselect(
            "Evidencia del citado",
            evidencias,
            format_func=lambda e: _EVIDENCIA.get(e, e),
            key="citas_evidencia",
        )
    with col_est:
        estado = st.selectbox(
            "Estado del reframing",
            ["Todos", "Clasificados", "Sin clasificar", "Con error"],
            key="citas_estado",
        )

    if sel_op:
        df = df[df["operacion"].isin(sel_op)]
    if sel_ev:
        df = df[df["evidencia"].isin(sel_ev)]
    # `reframing_error` puede faltar en runs anteriores a la migración.
    errores = (
        df["reframing_error"].notna() if "reframing_error" in df.columns
        else pd.Series(False, index=df.index)
    )
    if estado == "Clasificados":
        df = df[df["operacion"].notna()]
    elif estado == "Sin clasificar":
        df = df[df["operacion"].isna() & ~errores]
    elif estado == "Con error":
        df = df[errores]

    df = _panel_filtros(df, key="citas")
    if df.empty:
        st.info("Ninguna cita pasa los filtros.")
        return

    total = len(df)
    paginas = (total - 1) // _PAGINA + 1
    pagina = 1
    if paginas > 1:
        pagina = st.number_input(
            f"Página (de {paginas})",
            min_value=1, max_value=paginas, value=1, step=1,
            key="citas_pagina",
        )
    inicio = (int(pagina) - 1) * _PAGINA
    sub = df.iloc[inicio:inicio + _PAGINA]
    st.caption(f"{total} cita(s) o repost(s); mostrando {len(sub)}.")

    citados, emociones = _citados_de(db_path, sub)
    for _, post in sub.iterrows():
        _render_post(
            db_path, post, nivel=0, citados=citados, emociones=emociones,
        )


def _resumen_operaciones(df: pd.DataFrame) -> None:
    """Distribución de operaciones del corpus, como chips coloreados."""
    conteo = df["operacion"].value_counts()
    sin_clasificar = int(df["operacion"].isna().sum())
    chips = [
        f"<span class='ep-op ep-op-{op}'>{_OPERACIONES.get(op, op)} "
        f"· {int(conteo[op])}</span>"
        for op in _OPERACIONES if op in conteo
    ]
    if sin_clasificar:
        chips.append(
            f"<span class='badge badge-dim'>sin clasificar "
            f"· {sin_clasificar}</span>"
        )
    st.markdown(
        "<div style='display:flex;gap:0.4rem;flex-wrap:wrap;"
        f"margin-bottom:0.6rem;'>{''.join(chips)}</div>",
        unsafe_allow_html=True,
    )
    if "evidencia" in df.columns:
        conteo_ev = df["evidencia"].value_counts()
        partes = [
            f"{_EVIDENCIA.get(e, e)}: {int(conteo_ev[e])}"
            for e in _EVIDENCIA if e in conteo_ev
        ]
        if partes:
            st.caption("Evidencia sobre la que se clasificó · "
                       + " · ".join(partes))


# ══════════════════════════════════════════════════════════════════════════════
#  Filtros y ordenamiento
# ══════════════════════════════════════════════════════════════════════════════

def _panel_filtros(df: pd.DataFrame, key: str) -> pd.DataFrame:
    """Filtro por tipo de post y por presencia de reframing."""
    col_tipo, col_rt, col_ref = st.columns([2, 1, 1])
    en_corpus = set(df["tipo"]) if "tipo" in df.columns else set()
    presentes = [t for t in _TIPOS if t in en_corpus]
    with col_tipo:
        tipos = st.multiselect(
            "Tipo de post", presentes, key=f"{key}_tipos",
        ) if presentes else []
    with col_rt:
        solo_rt = st.toggle("Solo reposts", value=False, key=f"{key}_rt")
    with col_ref:
        solo_ref = st.toggle(
            "Solo con reframing", value=False, key=f"{key}_ref",
        )

    if tipos:
        df = df[df["tipo"].isin(tipos)]
    if solo_rt and "reposteo_a" in df.columns:
        df = df[df["reposteo_a"].notna()]
    if solo_ref:
        df = df[df["reframing"].map(lambda r: isinstance(r, dict))]
    return df


def _orden_arbol(df: pd.DataFrame) -> list[tuple[pd.Series, int]]:
    """Ordena los posts por descendencia (recorrido en profundidad).

    El orden por fecha con sangría por `profundidad` intercala ramas: una
    respuesta tardía a la raíz queda antes que la continuación de otra rama.
    Acá el nivel se calcula sobre el árbol efectivamente capturado, lo que
    además da profundidad a los huérfanos (que la traen nula).
    """
    posts = {str(r["post_id"]): r for _, r in df.iterrows()}
    hijos: dict[str, list[str]] = {pid: [] for pid in posts}
    raices: list[str] = []
    for pid, row in posts.items():
        padre = str(row.get("en_respuesta_a") or "").strip()
        if padre and padre != pid and padre in posts:
            hijos[padre].append(pid)
        else:
            raices.append(pid)

    def clave(pid: str) -> tuple[str, str]:
        return (str(posts[pid].get("fecha") or ""), pid)

    orden: list[tuple[pd.Series, int]] = []
    vistos: set[str] = set()
    pila = [(pid, 0) for pid in sorted(raices, key=clave, reverse=True)]
    while pila:
        pid, nivel = pila.pop()
        if pid in vistos:  # corta ciclos en cadenas anómalas de respuesta
            continue
        vistos.add(pid)
        orden.append((posts[pid], nivel))
        for hijo in sorted(hijos[pid], key=clave, reverse=True):
            pila.append((hijo, nivel + 1))

    # Un ciclo de respuestas deja posts sin raíz alcanzable: se anexan al pie
    # antes que perderlos de la vista.
    for pid in sorted(set(posts) - vistos, key=clave):
        orden.append((posts[pid], 0))
    return orden


def _citados_de(
    db_path: Path, df: pd.DataFrame,
) -> tuple[dict[str, dict], dict[str, list[dict]]]:
    """Posts citados por los de la vista y sus emociones, en dos consultas.

    Las emociones solo existen para los citados que son unidad del corpus:
    un citado leído de la copia embebida nunca pasó por `emotions`.
    """
    referencias: list[str] = []
    for col in ("cita_a", "reposteo_a"):
        if col in df.columns:
            referencias += [str(v) for v in df[col].dropna().tolist()]
    citados = data.get_posts_por_id(db_path, referencias)
    emociones = data.get_emociones_de_posts(db_path, citados)
    return citados, emociones


# ══════════════════════════════════════════════════════════════════════════════
#  Render de post
# ══════════════════════════════════════════════════════════════════════════════

def _render_post(
    db_path: Path,
    post: pd.Series,
    nivel: int,
    citados: dict[str, dict],
    emociones: dict[str, list[dict]],
) -> None:
    """Un post: cabecera con foria y reframing, texto, cita embebida y media."""
    foria = post.get("foria_dominante")
    color = foria_viz.color(foria)
    sangria = min(nivel, _NIVEL_MAX) * _SANGRIA_PX
    texto = str(post.get("texto") or "").strip() or "(repost sin texto)"

    partes = [
        f"<span class='ep-post-handle'>@{html.escape(str(post['autor_handle']))}"
        "</span>",
        f"<span>{html.escape(str(post.get('tipo') or 'original'))}</span>",
        _chip_foria(foria, color),
    ]
    partes += _chips_reframing(post)

    cuerpo = (
        f"<div class='ep-post' style='margin-left:{sangria}px;"
        f"border-left-color:{color};'>"
        f"<div class='ep-post-head'>{''.join(partes)}</div>"
        f"<div class='ep-post-texto'>{html.escape(texto)}</div>"
        f"{_bloque_citado(post, citados, emociones)}"
        f"{_bloque_justificacion(post)}"
        "</div>"
    )
    st.markdown(cuerpo, unsafe_allow_html=True)
    _render_media(db_path, str(post["post_id"]), sangria)


def _chip_foria(foria: object, color: str) -> str:
    """Chip con el nombre de la foria, del mismo color que la barra."""
    return (
        f"<span class='ep-foria' style='color:{color};border-color:{color};"
        f"background:{foria_viz.rgba(color, 0.15)};'>"
        f"{foria_viz.icono(foria)} {foria_viz.etiqueta(foria)}</span>"
    )


def _chips_reframing(post: pd.Series) -> list[str]:
    """Chips de la operación de redocumentación (o del estado pendiente)."""
    reframing = post.get("reframing")
    if isinstance(reframing, dict):
        op = str(reframing.get("operacion") or "ambigua")
        citadas = str(reframing.get("emociones_citadas") or "")
        chips = [
            f"<span class='ep-op ep-op-{html.escape(op)}'>↪ "
            f"{_OPERACIONES.get(op, op)}</span>"
        ]
        if citadas:
            chips.append(
                f"<span class='badge badge-dim' style='font-size:0.68rem;'>"
                f"{_EMOCIONES_CITADAS.get(citadas, citadas)}</span>"
            )
        return chips
    if post.get("reframing_error"):
        return ["<span class='badge badge-err'>reframing con error</span>"]
    if post.get("cita_a") or post.get("reposteo_a"):
        return ["<span class='badge badge-dim'>reframing sin correr</span>"]
    return []


def _bloque_citado(
    post: pd.Series,
    citados: dict[str, dict],
    emociones: dict[str, list[dict]] | None = None,
) -> str:
    """Bloque embebido del post citado o reposteado.

    Sin el citado, la operación clasificada no se puede leer: se afirma que
    hay denuncia sin mostrar qué se denuncia. Se distinguen tres situaciones,
    porque no significan lo mismo para el análisis:

    - el citado es unidad del corpus: se muestra con su foria;
    - no lo es, pero el citador trae su texto embebido: se muestra el texto
      y se aclara que está fuera del corpus (no tiene emociones ni foria
      porque nunca pasó por el pipeline);
    - no hay ni una cosa ni la otra: cita perdida.
    """
    referencia = post.get("cita_a") or post.get("reposteo_a")
    if not referencia:
        return ""
    etiqueta = "cita a" if post.get("cita_a") else "repostea a"

    citado = citados.get(str(referencia))
    if citado is not None:
        color = foria_viz.color(citado.get("foria_dominante"))
        return _quote_html(
            color,
            f"{etiqueta} @{html.escape(str(citado.get('autor_handle') or '?'))}",
            str(citado.get("texto") or "").strip() or "(sin texto)",
            _chips_emociones((emociones or {}).get(str(referencia))),
        )

    embebido = post.get("cita_embebida")
    if isinstance(embebido, dict):
        return _quote_html(
            foria_viz.FORIA_COLORS[None],
            f"{etiqueta} @{html.escape(str(embebido.get('autor_handle') or '?'))}"
            " · <i>fuera del corpus</i>",
            str(embebido.get("texto") or ""),
        )

    return (
        f"<div class='ep-quote'><span class='ep-quote-head'>{etiqueta} "
        f"{html.escape(str(referencia))} · no capturado</span></div>"
    )


def _quote_html(
    color: str, encabezado: str, texto: str, extra: str = "",
) -> str:
    """Bloque de cita con su barra de color, su encabezado y su análisis."""
    return (
        f"<div class='ep-quote' style='border-left:3px solid {color};'>"
        f"<span class='ep-quote-head'>{encabezado}</span><br>"
        f"<span class='ep-quote-texto'>{html.escape(texto)}</span>"
        f"{extra}</div>"
    )


def _chips_emociones(emociones: list[dict] | None) -> str:
    """Emociones detectadas en el citado, con su experienciador y su fuente.

    Decir que el citador semiotiza un afecto y no mostrar cuál obliga a
    creerle a la clasificación. Solo aparecen cuando el citado es unidad del
    corpus: es la única situación en que están analizadas.
    """
    if not emociones:
        return ""
    chips = []
    for e in emociones:
        color = foria_viz.color(e.get("foria"))
        fuente = str(e.get("fuente") or "")
        detalle = f"exp: {e.get('experienciador', '?')}"
        if fuente:
            detalle += f" ← {fuente}"
        chips.append(
            f"<span class='emo-chip' style='color:{color};"
            f"border-color:{foria_viz.rgba(color, 0.45)};"
            f"background:{foria_viz.rgba(color, 0.12)};'>"
            f"{html.escape(str(e.get('tipo', '?')))}"
            f"<span style='color:var(--dim);'> · {html.escape(detalle)}</span>"
            "</span>"
        )
    return (
        "<div style='margin-top:0.35rem;display:flex;flex-wrap:wrap;"
        f"gap:0.15rem;'>{''.join(chips)}</div>"
    )


def _bloque_justificacion(post: pd.Series) -> str:
    """Justificación del reframing, en segundo plano tipográfico."""
    reframing = post.get("reframing")
    if not isinstance(reframing, dict):
        return ""
    justificacion = str(reframing.get("justificacion") or "").strip()
    if not justificacion:
        return ""
    return f"<div class='ep-justif'>{html.escape(justificacion)}</div>"


def _render_media(db_path: Path, post_id: str, sangria: int) -> None:
    """Descripciones de los adjuntos del post, si `vision_describe` corrió."""
    for m in data.get_media_of_post(db_path, post_id):
        payload = m.get("descripcion_payload")
        if not isinstance(payload, dict):
            continue
        tipo = html.escape(str(payload.get("tipo_imagen") or "imagen"))
        descripcion = html.escape(str(payload.get("descripcion") or "")[:220])
        st.markdown(
            f"<div class='ep-media' style='margin-left:"
            f"{sangria + _SANGRIA_PX}px;'>🖼 [{tipo}] {descripcion}</div>",
            unsafe_allow_html=True,
        )
