# ══════════════════════════════════════════════════════════════════════════════
#  emoparse.app.components.tab_tecno
#
#  Tab Tecno: distribución de tecnolingüísticos, uso en contexto de menciones,
#  tecnografismos y links, y afecto de emojis con drill-down a frases.
# ══════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

import html
from pathlib import Path

import streamlit as st

from emoparse.app import data


def render(db_path: Path) -> None:
    """Renderiza la tab de tecnolingüísticos."""
    st.markdown("#### ✳ Tecnolingüísticos")
    df = data.get_tecno_resumen(db_path)
    if df.empty:
        st.info(
            "Sin tecno-entidades: corré la stage `technoparse` "
            "(el género tuit la habilita por defecto)."
        )
        return

    col1, col2 = st.columns(2)
    with col1:
        st.markdown("##### Por tipo")
        st.dataframe(
            df.groupby("tipo", as_index=False)
            .agg(entidades=("n", "sum"), distintos=("valor_norm", "count"))
            .sort_values("entidades", ascending=False),
            use_container_width=True,
            hide_index=True,
        )
    with col2:
        tipo = st.selectbox("Detalle de tipo", sorted(df["tipo"].unique()))
        if tipo == "tecnografismo":
            detalle = _detalle_tecnografismos(db_path)
        else:
            detalle = df[df["tipo"] == tipo].copy()
            if tipo == "mencion":
                detalle["valor_norm"] = "@" + detalle["valor_norm"].astype(str)
            elif tipo == "hashtag":
                detalle["valor_norm"] = "#" + detalle["valor_norm"].astype(str)
        st.dataframe(
            detalle.head(60),
            use_container_width=True,
            hide_index=True,
        )

    _render_usos(db_path)
    _render_emojis(db_path)


def _display_tecnografismo(r) -> str:
    """Etiqueta agrupada de un tecnografismo para las tablas.

    Las mayúsculas de frase entera ya vienen normalizadas
    ('mayusculas_sostenidas'); las palabras y expresiones cuyo uso inferido
    es énfasis se agrupan en 'mayusculas (énfasis en palabras)' para no
    dispersar la tabla; con otro uso (o sin uso resuelto), la entidad
    específica.
    """
    if str(r.get("atributo")) == "mayusculas":
        if str(r.get("alcance")) == "frase":
            return "mayusculas_sostenidas"
        if str(r.get("uso") or "") == "enfasis":
            return "mayusculas (énfasis en palabras)"
    return str(r.get("valor_norm") or "")


def _detalle_tecnografismos(db_path: Path):
    """Tabla de tecnografismos con la etiqueta agrupada (anti-dispersión)."""
    df = data.get_tecno_usos(db_path)
    df = df[df["tipo"] == "tecnografismo"]
    if df.empty:
        return df
    df = df.assign(valor=df.apply(_display_tecnografismo, axis=1))
    return (
        df.groupby(["valor", "atributo"], as_index=False)
        .size().rename(columns={"size": "n"})
        .sort_values("n", ascending=False)
    )


def _render_usos(db_path: Path) -> None:
    """Uso en contexto de menciones, tecnografismos y URLs, por separado."""
    df = data.get_tecno_usos(db_path)
    if df.empty:
        return
    st.markdown("##### Uso en contexto")
    resueltos = df[df["uso"].notna()]
    if resueltos.empty:
        st.info(
            "Usos sin analizar: corré la stage `tecno_usage` "
            "(requiere modelo asignado en el config)."
        )
        return
    st.caption(
        f"{len(resueltos)} de {len(df)} entidades con uso resuelto en contexto."
    )
    for tipo, titulo, prefijo, key in (
        ("mencion", "Menciones", "@", "tecno_uso_men"),
        ("tecnografismo", "Tecnografismos", "", "tecno_uso_tec"),
        ("url", "Links", "", "tecno_uso_url"),
    ):
        _render_uso_seccion(
            resueltos[resueltos["tipo"] == tipo], titulo, prefijo, key
        )


def _render_uso_seccion(sub, titulo: str, prefijo: str, key: str) -> None:
    """Una sección de usos (resumen + drill-down a posts) de un solo tipo.

    Menciones y links agrupan por entidad (handle, dominio); los
    tecnografismos, por la etiqueta agrupada que evita la dispersión.
    """
    if sub.empty:
        return
    st.markdown(f"###### {titulo}")
    if titulo == "Tecnografismos":
        agrupado = sub.assign(valor=sub.apply(_display_tecnografismo, axis=1))
        resumen = (
            agrupado.groupby(["valor", "uso"], as_index=False)
            .size().rename(columns={"size": "usos"})
            .sort_values("usos", ascending=False)
        )
    elif titulo == "Links":
        # El dominio es lo que agrupa: una misma nota se comparte con URLs
        # distintas (parámetros de campaña, acortadores).
        resumen = (
            sub.groupby(["valor_norm", "uso"], as_index=False)
            .size().rename(columns={"size": "usos", "valor_norm": "dominio"})
            .sort_values("usos", ascending=False)
        )
    else:
        resumen = (
            sub.groupby("uso", as_index=False)
            .size().rename(columns={"size": "usos"})
            .sort_values("usos", ascending=False)
        )
    st.dataframe(resumen, use_container_width=True, hide_index=True)

    valores = [
        f"{prefijo}{v}" for v in sub["valor_norm"].value_counts().index
    ]
    sel = st.selectbox(
        f"Ver posts de una entidad ({titulo.lower()})",
        ["(elegir)"] + valores, key=key,
    )
    if sel == "(elegir)":
        return
    objetivo = sel[len(prefijo):] if prefijo and sel.startswith(prefijo) else sel
    fila = sub[sub["valor_norm"].astype(str) == objetivo]
    for _, r in fila.head(40).iterrows():
        st.markdown(
            f"<div style='border-left:3px solid #6ec89a;padding:0.3rem 0.7rem;"
            f"margin-bottom:0.35rem;background:#15171c;border-radius:0 6px 6px 0;"
            f"font-size:0.82rem;line-height:1.5;'>"
            f"<span style='color:#6ec89a;font-weight:600;'>{html.escape(str(r['uso']))}"
            f"</span><span style='color:#5a5d6e;'> · {html.escape(str(r['codigo']))}"
            f"</span><br><span style='color:#c2bdb4;'>{html.escape(str(r['frase'] or ''))}"
            f"</span>"
            + (f"<br><span style='color:#5a5d6e;font-style:italic;font-size:0.74rem;'>"
               f"{html.escape(str(r['uso_justificacion']))}</span>"
               if r.get("uso_justificacion") else "")
            + "</div>",
            unsafe_allow_html=True,
        )


def _render_emojis(db_path: Path) -> None:
    """Afecto de emojis, con las frases de cada emoji al seleccionarlo."""
    st.markdown("##### Afecto de emojis")
    df_emojis = data.get_emojis_con_afecto(db_path)
    if df_emojis.empty:
        return
    resueltos = df_emojis[df_emojis["candidato"].notna()]
    st.caption(
        f"{len(resueltos)} de {len(df_emojis)} usos con afecto resuelto "
        f"({int((resueltos['origin'] == 'lexico').sum())} por léxico, "
        f"{int((resueltos['origin'] == 'llm').sum())} por LLM en contexto)."
    )
    if resueltos.empty:
        return
    st.dataframe(
        resueltos.groupby(["emoji", "candidato", "foria"], as_index=False)
        .size()
        .rename(columns={"size": "usos"})
        .sort_values("usos", ascending=False)
        .head(60),
        use_container_width=True,
        hide_index=True,
    )

    emojis = resueltos["emoji"].value_counts().index.tolist()
    sel = st.selectbox("Ver frases de un emoji", ["(elegir)"] + emojis,
                       key="tecno_emoji_sel")
    if sel == "(elegir)":
        return
    df_fr = data.get_frases_con_emoji(db_path, sel)
    if df_fr.empty:
        st.info("Sin frases para ese emoji.")
        return
    for _, r in df_fr.head(40).iterrows():
        afecto = str(r.get("candidato") or "—")
        foria = str(r.get("foria") or "")
        st.markdown(
            f"<div style='border-left:3px solid #c8a96e;padding:0.3rem 0.7rem;"
            f"margin-bottom:0.35rem;background:#15171c;border-radius:0 6px 6px 0;"
            f"font-size:0.82rem;line-height:1.5;'>"
            f"<span style='color:#c8a96e;font-weight:600;'>{html.escape(sel)} "
            f"{html.escape(afecto)}</span>"
            + (f"<span style='color:#5a5d6e;'> · {html.escape(foria)}</span>"
               if foria else "")
            + f"<span style='color:#5a5d6e;'> · {html.escape(str(r['codigo']))}</span>"
            f"<br><span style='color:#c2bdb4;'>{html.escape(str(r['frase'] or ''))}"
            f"</span></div>",
            unsafe_allow_html=True,
        )
