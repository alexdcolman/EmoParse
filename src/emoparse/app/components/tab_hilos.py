# ══════════════════════════════════════════════════════════════════════════════
#  emoparse.app.components.tab_hilos
#
#  Tab Hilos: árbol conversacional navegable con foria por post.
# ══════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

from pathlib import Path

import streamlit as st

from emoparse.app import data
from emoparse.viz.network_charts import FORIA_COLORS


def render(db_path: Path) -> None:
    """Renderiza la tab de hilos."""
    st.markdown("#### 🧵 Hilos")
    df_hilos = data.get_hilos(db_path, min_posts=2)
    if df_hilos.empty:
        st.info(
            "El corpus no tiene conversaciones con más de un post capturado."
        )
        return

    opciones = {
        f"{h['conversacion_id']}  ({h['n_posts']} posts, "
        f"prof. {h['profundidad_max']})": h["conversacion_id"]
        for _, h in df_hilos.iterrows()
    }
    etiqueta = st.selectbox("Conversación", list(opciones))
    conversacion_id = opciones[etiqueta]

    df_posts = data.get_posts_de_hilo(db_path, conversacion_id)
    if df_posts.empty:
        st.warning("Sin posts capturados para esa conversación.")
        return

    profundidad = {
        str(r["post_id"]): int(r["profundidad"]) if r["profundidad"] is not None else 0
        for _, r in df_posts.iterrows()
    }
    for _, post in df_posts.iterrows():
        _render_post(db_path, post, nivel=profundidad.get(str(post["post_id"]), 0))


def _render_post(db_path: Path, post, nivel: int) -> None:
    """Un post del hilo, indentado por profundidad y coloreado por foria."""
    foria = post.get("foria_dominante")
    color = FORIA_COLORS.get(foria, FORIA_COLORS[None])
    indent = min(nivel, 8) * 22
    texto = str(post.get("texto") or "").strip() or "(repost sin texto)"
    tipo = post.get("tipo", "original")
    reframing = post.get("reframing")
    linea_reframing = ""
    if isinstance(reframing, dict):
        linea_reframing = (
            f"<div style='color:#8a8799;font-size:0.8rem;'>↪ operación sobre "
            f"lo citado: <b>{reframing.get('operacion', '?')}</b> · emociones "
            f"citadas: {reframing.get('emociones_citadas', '?')}</div>"
        )
    st.markdown(
        f"<div style='margin-left:{indent}px;border-left:3px solid {color};"
        f"padding:0.35rem 0.7rem;margin-bottom:0.4rem;background:#1c1a28;"
        f"border-radius:0 6px 6px 0;'>"
        f"<span style='color:#8a8799;font-size:0.8rem;'>@{post['autor_handle']}"
        f" · {tipo}" + (f" · foria: {foria}" if foria else "") + "</span><br>"
        f"{texto}{linea_reframing}</div>",
        unsafe_allow_html=True,
    )
    for m in data.get_media_of_post(db_path, str(post["post_id"])):
        payload = m.get("descripcion_payload")
        if isinstance(payload, dict):
            st.markdown(
                f"<div style='margin-left:{indent + 22}px;color:#8a8799;"
                f"font-size:0.8rem;'>🖼 [{payload.get('tipo_imagen', 'imagen')}] "
                f"{payload.get('descripcion', '')[:220]}</div>",
                unsafe_allow_html=True,
            )
