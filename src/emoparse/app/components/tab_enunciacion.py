# ══════════════════════════════════════════════════════════════════════════════
#  emoparse.app.components.tab_enunciacion
#
#  Edición de la estructura enunciativa por discurso: enunciador, enunciatarios,
#  auditorio y colectivos de identificación. Lo editado sobreescribe el
#  `enunciation_payload` del discurso (lo que consume el stage `deixis`) y, si se
#  renombra un referente, repunta sus vínculos deícticos en la base de marcas.
# ══════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

import html
import json
from pathlib import Path
from typing import Any

import pandas as pd
import streamlit as st

from emoparse.app import actions as actions_layer
from emoparse.app import data as data_layer
from emoparse.app import _knowledge
from emoparse.core.text import canonical_slug

_DEST_DEFAULT = ["prodestinatario", "paradestinatario", "contradestinatario"]


def render(db_path: Path) -> None:
    """Renderiza la tab de edición enunciativa."""
    st.markdown("### Enunciación")

    discursos = data_layer.list_discursos(db_path)
    if not discursos:
        st.info("No hay discursos en este run.")
        return

    labels = {
        (f"{cod} — {tit}" if tit else cod): cod for cod, tit in discursos
    }
    sel = st.selectbox("Discurso", list(labels), key="enun_disc")
    codigo = labels[sel]

    data = data_layer.get_enunciation_full(db_path, codigo)
    if data is None:
        st.info("Discurso sin datos.")
        return

    if data["titulo"]:
        st.markdown(
            f"<div style='font-size:1rem;color:#e8e4dc;font-weight:600;"
            f"margin-bottom:0.2rem;'>{html.escape(data['titulo'])}</div>",
            unsafe_allow_html=True,
        )
    if data["resumen"]:
        with st.expander("Resumen global", expanded=False):
            st.markdown(
                f"<div style='font-size:0.86rem;line-height:1.6;color:#c2bdb4;'>"
                f"{html.escape(data['resumen'])}</div>",
                unsafe_allow_html=True,
            )

    canonicos = data_layer.list_canonicos(db_path)
    if canonicos:
        st.caption("Referentes existentes (podés reusar estos nombres): "
                   + ", ".join(canonicos[:60])
                   + (" …" if len(canonicos) > 60 else ""))

    st.divider()

    # ── Enunciador ────────────────────────────────────────────────────────────
    st.markdown("#### Enunciador")
    e_key = f"enun_e_{codigo}"
    if e_key not in st.session_state:
        st.session_state[e_key] = data["enunciador"]

    pe1, pe2 = st.columns([3, 1])
    existente = pe1.selectbox(
        "Usar referente existente",
        ["—", *canonicos],
        key=f"enun_epick_{codigo}",
    )
    with pe2:
        st.markdown("<div style='height:1.8rem;'></div>", unsafe_allow_html=True)
        if st.button("usar", key=f"enun_euse_{codigo}",
                     use_container_width=True, disabled=existente == "—"):
            st.session_state[e_key] = existente
            st.rerun()

    e1, e2 = st.columns([2, 3])
    enunciador = e1.text_input("Enunciador", key=e_key)
    just = e2.text_input(
        "Justificación", value=data["enunciador_justificacion"],
        key=f"enun_ej_{codigo}",
    )

    # ── Enunciatarios ─────────────────────────────────────────────────────────
    st.markdown("#### Enunciatarios")
    tipo_opts = sorted(
        {str(e.get("tipo")) for e in data["enunciatarios"] if e.get("tipo")}
        | set(_DEST_DEFAULT)
    )
    edited_enun = st.data_editor(
        _to_df(data["enunciatarios"], ["actor", "tipo", "justificacion"]),
        num_rows="dynamic", hide_index=True, use_container_width=True,
        key=f"enun_eds_{codigo}",
        column_config={
            "actor": st.column_config.TextColumn("actor"),
            "tipo": st.column_config.SelectboxColumn("tipo", options=tipo_opts),
            "justificacion": st.column_config.TextColumn("justificación"),
        },
    )

    # ── Auditorio ─────────────────────────────────────────────────────────────
    st.markdown("#### Auditorio (destinatario directo)")
    edited_aud = st.data_editor(
        _to_df(data["auditorio"], ["actor", "justificacion"]),
        num_rows="dynamic", hide_index=True, use_container_width=True,
        key=f"enun_aud_{codigo}",
        column_config={
            "actor": st.column_config.TextColumn("auditorio"),
            "justificacion": st.column_config.TextColumn("justificación"),
        },
    )

    # ── Colectivos de identificación ──────────────────────────────────────────
    st.markdown("#### Colectivos de identificación")
    clase_opts = sorted(
        {str(c.get("clase")) for c in data["colectivos"] if c.get("clase")}
        | set(_knowledge.colectivo_clases())
    )
    edited_col = st.data_editor(
        _to_df(data["colectivos"], ["nombre", "clase", "justificacion"]),
        num_rows="dynamic", hide_index=True, use_container_width=True,
        key=f"enun_col_{codigo}",
        column_config={
            "nombre": st.column_config.TextColumn("nombre"),
            "clase": st.column_config.SelectboxColumn("clase", options=clase_opts),
            "justificacion": st.column_config.TextColumn("justificación"),
        },
    )

    st.divider()
    if st.button("💾 Guardar enunciación", type="primary",
                 key=f"enun_save_{codigo}"):
        _save(db_path, codigo, data, enunciador, just,
              edited_enun, edited_aud, edited_col)


# ── Helpers ──────────────────────────────────────────────────────────────────

def _cell(rec: dict, col: str) -> str:
    v = rec.get(col)
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return ""
    return str(v).strip()


def _to_df(items: list, cols: list[str]) -> pd.DataFrame:
    rows = [
        {c: str(it.get(c, "") or "") for c in cols}
        for it in items if isinstance(it, dict)
    ]
    return pd.DataFrame(rows, columns=cols)


def _records(df: pd.DataFrame, key_col: str, cols: list[str]) -> list[dict]:
    out: list[dict] = []
    for rec in df.to_dict("records"):
        if not _cell(rec, key_col):
            continue
        out.append({c: _cell(rec, c) for c in cols})
    return out


def _save(db_path, codigo, old, enunciador, just,
          edited_enun, edited_aud, edited_col) -> None:
    enunciatarios = _records(edited_enun, "actor", ["actor", "tipo", "justificacion"])
    auditorio = _records(edited_aud, "actor", ["actor", "justificacion"])
    colectivos = _records(edited_col, "nombre", ["nombre", "clase", "justificacion"])

    payload = {
        "enunciador": enunciador.strip(),
        "enunciador_justificacion": just.strip(),
        "enunciatarios": json.dumps(enunciatarios, ensure_ascii=False),
        "auditorio": json.dumps(auditorio, ensure_ascii=False),
        "colectivos_identificacion": json.dumps(colectivos, ensure_ascii=False),
    }
    moved = actions_layer.save_enunciation(db_path, codigo, payload)
    msg = "Enunciación guardada."
    if moved:
        msg += f" {moved} vínculo(s) deíctico(s) repuntado(s)."
    st.toast(msg, icon="✅")
    st.rerun()
