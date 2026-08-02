# ══════════════════════════════════════════════════════════════════════════════
#  emoparse.app.components.tab_tecno
#
#  Tab Tecno: distribución de tecnolingüísticos, uso en contexto de menciones,
#  tecnografismos y links, y afecto de emojis por racha con drill-down a
#  frases.
# ══════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

import html
from pathlib import Path

import streamlit as st

from emoparse.app import data
from emoparse.viz import foria as foria_viz


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
        por_tipo = (
            df.groupby("tipo", as_index=False)
            .agg(entidades=("n", "sum"), distintos=("valor_norm", "count"))
            .sort_values("entidades", ascending=False)
        )
        st.dataframe(
            por_tipo,
            use_container_width=True,
            hide_index=True,
            column_config={
                "entidades": st.column_config.ProgressColumn(
                    "entidades",
                    format="%d",
                    min_value=0,
                    max_value=int(por_tipo["entidades"].max() or 1),
                ),
            },
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
        .size()
        .rename(columns={"size": "n"})
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
    st.caption(f"{len(resueltos)} de {len(df)} entidades con uso resuelto en contexto.")
    for tipo, titulo, prefijo, key in (
        ("mencion", "Menciones", "@", "tecno_uso_men"),
        ("tecnografismo", "Tecnografismos", "", "tecno_uso_tec"),
        ("url", "Links", "", "tecno_uso_url"),
    ):
        _render_uso_seccion(resueltos[resueltos["tipo"] == tipo], titulo, prefijo, key)


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
            .size()
            .rename(columns={"size": "usos"})
            .sort_values("usos", ascending=False)
        )
    elif titulo == "Links":
        # El dominio es lo que agrupa: una misma nota se comparte con URLs
        # distintas (parámetros de campaña, acortadores).
        resumen = (
            sub.groupby(["valor_norm", "uso"], as_index=False)
            .size()
            .rename(columns={"size": "usos", "valor_norm": "dominio"})
            .sort_values("usos", ascending=False)
        )
    else:
        resumen = (
            sub.groupby("uso", as_index=False)
            .size()
            .rename(columns={"size": "usos"})
            .sort_values("usos", ascending=False)
        )
    st.dataframe(
        resumen,
        use_container_width=True,
        hide_index=True,
        column_config={
            "usos": st.column_config.ProgressColumn(
                "usos",
                format="%d",
                min_value=0,
                max_value=int(resumen["usos"].max() or 1),
            ),
        },
    )

    valores = [f"{prefijo}{v}" for v in sub["valor_norm"].value_counts().index]
    sel = st.selectbox(
        f"Ver posts de una entidad ({titulo.lower()})",
        ["(elegir)"] + valores,
        key=key,
    )
    if sel == "(elegir)":
        return
    objetivo = sel[len(prefijo) :] if prefijo and sel.startswith(prefijo) else sel
    fila = sub[sub["valor_norm"].astype(str) == objetivo]
    for _, r in fila.head(40).iterrows():
        st.markdown(
            f"<div style='border-left:3px solid var(--ok);padding:0.3rem 0.7rem;"
            f"margin-bottom:0.35rem;background:var(--surface-sunken);border-radius:0 6px 6px 0;"
            f"font-size:0.82rem;line-height:1.5;'>"
            f"<span style='color:var(--ok);font-weight:600;'>{html.escape(str(r['uso']))}"
            f"</span><span style='color:var(--dim);'> · {html.escape(str(r['codigo']))}"
            f"</span><br><span style='color:var(--text-soft);'>{html.escape(str(r['frase'] or ''))}"
            f"</span>"
            + (
                f"<br><span style='color:var(--dim);font-style:italic;font-size:0.74rem;'>"
                f"{html.escape(str(r['uso_justificacion']))}</span>"
                if r.get("uso_justificacion")
                else ""
            )
            + "</div>",
            unsafe_allow_html=True,
        )


def _render_emojis(db_path: Path) -> None:
    """Afecto de emojis por racha, con las frases de cada emoji al elegirlo.

    La unidad que se lista es la racha, no la pulsación: 🤣🤣🤣 aparece una
    vez, marcado ×3, porque es un solo gesto intensificado.
    """
    st.markdown("##### Afecto de emojis")
    df_emojis = data.get_emojis_con_afecto(db_path)
    if df_emojis.empty:
        return
    rachas = df_emojis[df_emojis["primario"]]
    resueltos = rachas[rachas["candidato"].notna()]
    st.caption(
        f"{len(resueltos)} de {len(rachas)} rachas con afecto resuelto "
        f"({int((resueltos['origin'] == 'lexico').sum())} por léxico, "
        f"{int((resueltos['origin'] == 'llm').sum())} por LLM en contexto) "
        f"sobre {len(df_emojis)} ocurrencias del corpus."
    )
    if resueltos.empty:
        return
    resumen = (
        resueltos.groupby(["emoji", "candidato", "foria"], as_index=False)
        .agg(rachas=("emoji", "size"), ocurrencias=("repeticiones", "sum"))
        .sort_values("rachas", ascending=False)
        .head(60)
    )
    st.dataframe(
        resumen,
        use_container_width=True,
        hide_index=True,
        column_config={
            # Rachas y ocurrencias miden cosas distintas (gestos vs
            # pulsaciones): la barra va sobre las rachas, que es la unidad.
            "rachas": st.column_config.ProgressColumn(
                "rachas",
                format="%d",
                min_value=0,
                max_value=int(resumen["rachas"].max() or 1),
            ),
        },
    )

    emojis = resueltos["emoji"].value_counts().index.tolist()
    sel = st.selectbox("Ver frases de un emoji", ["(elegir)"] + emojis, key="tecno_emoji_sel")
    if sel == "(elegir)":
        return
    df_fr = data.get_frases_con_emoji(db_path, sel)
    df_fr = df_fr[df_fr["primario"]] if not df_fr.empty else df_fr
    if df_fr.empty:
        st.info("Sin frases para ese emoji.")
        return
    for _, r in df_fr.head(40).iterrows():
        _render_uso_emoji(sel, r)


def _render_uso_emoji(emoji: str, r) -> None:
    """Una racha: emoji con su multiplicador, afecto y frase con la racha
    resaltada en el punto exacto donde se usó."""
    color = foria_viz.color(r.get("foria"))
    n = int(r.get("repeticiones") or 1)
    multiplicador = (
        f"<span class='badge badge-dim' style='font-size:0.66rem;'>×{n} · "
        f"{html.escape(str(r.get('intensidad') or ''))}</span>"
        if n > 1
        else ""
    )
    st.markdown(
        f"<div class='ep-post' style='border-left-color:{color};'>"
        f"<div class='ep-post-head'>"
        f"<span style='font-size:1rem;'>{html.escape(emoji)}</span>"
        f"<span style='color:{color};font-weight:600;'>"
        f"{html.escape(str(r.get('candidato') or '—'))}</span>"
        f"{_chip_foria_emoji(r.get('foria'), color)}"
        f"{multiplicador}"
        f"<span>{html.escape(str(r['codigo']))}</span>"
        f"</div>"
        f"<div class='ep-post-texto'>{_resaltar_racha(r)}</div>"
        + (
            f"<div class='ep-justif'>{html.escape(str(r['justificacion']))}</div>"
            if r.get("justificacion")
            else ""
        )
        + "</div>",
        unsafe_allow_html=True,
    )


def _chip_foria_emoji(foria, color: str) -> str:
    """Chip de foria del uso, con la misma paleta que el resto del dashboard."""
    return (
        f"<span class='ep-foria' style='color:{color};border-color:{color};"
        f"background:{foria_viz.rgba(color, 0.15)};'>"
        f"{foria_viz.icono(foria)} {foria_viz.etiqueta(foria)}</span>"
    )


def _resaltar_racha(r) -> str:
    """Frase con la racha analizada marcada, si se conocen sus offsets.

    Sin la marca, un post con dos rachas del mismo emoji muestra dos veces
    el mismo texto y no se sabe a cuál de las dos refiere cada inferencia.
    """
    frase = str(r.get("frase") or "")
    inicio, fin = r.get("inicio_racha"), r.get("fin_racha")
    if inicio is None or fin is None or not 0 <= inicio < fin <= len(frase):
        return html.escape(frase)
    return (
        html.escape(frase[: int(inicio)])
        + "<mark style='background:rgba(200,169,110,0.28);color:inherit;"
        "border-radius:3px;padding:0 2px;'>"
        + html.escape(frase[int(inicio) : int(fin)])
        + "</mark>"
        + html.escape(frase[int(fin) :])
    )
