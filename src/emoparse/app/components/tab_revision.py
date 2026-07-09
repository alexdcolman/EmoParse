# ══════════════════════════════════════════════════════════════════════════════
#  emoparse.app.components.tab_revision
#
#  Revisión y edición frase por frase. Lee de las bases (solo lectura) y guarda
#  las correcciones del analista en un overlay aparte (emoparse.app.revision_
#  overlay), sin tocar nunca las bases del pipeline ni la KB.
# ══════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

import html
from pathlib import Path
from typing import Any

import streamlit as st

from emoparse.app import data as data_layer
from emoparse.app.revision_overlay import (
    OverlayCorruptError,
    RevisionOverlay,
    default_overlay_path,
)

#: Opciones de los campos tipados (Literal). Se importan del esquema como única
#: fuente de verdad, campo por campo (si falta uno, no invalida el resto).
def _safe_opts(litname: str) -> list[str] | None:
    try:
        from typing import get_args

        from emoparse.core import schemas as _sc

        return list(get_args(getattr(_sc, litname)))
    except Exception:
        return None


_OPTS: dict[str, list[str]] = {}
for _leaf, _lit in (
    ("foria", "Foria"),
    ("intensidad", "Intensidad"),
    ("dominancia", "Dominancia"),
    ("duracion", "TipoDuracion"),
    ("tipo_atribucion", "TipoAtribucion"),
    ("modo_existencia", "ModoExistenciaEmocion"),
    ("tipo_configuracion", "TipoConfiguracion"),
    ("temporalidad", "Temporalidad"),
    ("aspecto", "Aspecto"),
):
    _o = _safe_opts(_lit)
    if _o:
        _OPTS[_leaf] = _o
_OPTS.setdefault("foria", ["euforico", "disforico", "aforico", "ambiforico", "indeterminado"])
_OPTS.setdefault("intensidad", ["alta", "baja", "neutra_ambivalente"])

_KB_TIPOS = ("individuo", "institucion", "colectivo", "desconocido")
_ACTANTE_KEYS = (
    "mediador", "verificador_normativo", "verificador_observacional",
    "operador_modificacion", "polaridad",
)


def _esc(s: Any) -> str:
    return html.escape(str(s)) if s is not None else ""


def _join_canon(v: Any) -> str:
    """Representa `experienciador_canonico` (str o lista) como texto editable."""
    if isinstance(v, (list, tuple)):
        return "; ".join(str(x) for x in v if str(x).strip())
    return "" if v is None else str(v)


def _parse_canon(s: str) -> Any:
    """Texto 'a; b' → lista; un solo valor → str; vacío → None."""
    parts = [p.strip() for p in str(s).split(";") if p.strip()]
    if not parts:
        return None
    return parts[0] if len(parts) == 1 else parts


def _referentes_kb_index() -> dict[str, str]:
    """Lee referentes_kb.json (KB persistente de referentes) → {canonical_id: display_name}."""
    import json
    import os
    path = Path(os.environ.get("EMOPARSE_KNOWLEDGE_DIR", "knowledge")) / "referentes_kb.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    refs = data.get("referentes", {}) if isinstance(data, dict) else {}
    return {cid: str(info.get("display_name") or cid) for cid, info in refs.items()}


def _kb_display(db_path: Path, ov: RevisionOverlay) -> dict[str, str]:
    """Mapa canonical_id → display_name (referentes_kb + actores propuestos en el overlay)."""
    disp: dict[str, str] = dict(_referentes_kb_index())
    try:
        for cid, info in ov.list_proposed_actors().items():
            disp.setdefault(cid, str(info.get("display_name") or cid))
    except Exception:
        pass
    return disp


def _canon_label(canon: Any, kb_disp: dict[str, str]) -> str:
    """Resuelve un canónico (slug) a su display_name si está en la KB."""
    if canon is None or str(canon).strip() == "":
        return ""
    return kb_disp.get(str(canon), str(canon))


def _canon_display(value: Any, kb_disp: dict[str, str]) -> str:
    """Como `_canon_label` pero acepta str o lista (varios experienciadores)."""
    if isinstance(value, (list, tuple)):
        return "; ".join(
            _canon_label(x, kb_disp) for x in value if str(x).strip()
        )
    return _canon_label(value, kb_disp)


def _toggle(label: str, key: str) -> bool:
    fn = getattr(st, "toggle", st.checkbox)
    return bool(fn(label, key=key, value=st.session_state.get(key, False)))


def render(db_path: Path) -> None:
    """Renderiza la tab de revisión y edición frase por frase."""
    st.markdown("### Revisión frase por frase")
    st.markdown(
        """<style>
        .ep-el{font-size:0.78rem;line-height:1.32;margin:0.05rem 0;}
        .ep-el .sec{color:#5a5d6e;font-size:0.66rem;}
        .ep-el .chip{color:#6ec89a;font-size:0.66rem;}
        .ep-el .just{display:block;color:#5a5d6e;font-size:0.66rem;
                     line-height:1.25;margin-top:0.05rem;font-style:italic;}
        .ep-sec-h{margin:0.5rem 0 0.15rem;font-size:0.68rem;letter-spacing:0.06em;
                  text-transform:uppercase;color:#7c7a89;border-top:1px solid #23252c;
                  padding-top:0.25rem;}
        div[data-testid="stButton"] button{padding:0 0.35rem;min-height:1.5rem;
            line-height:1.2;font-size:0.72rem;}
        </style>""",
        unsafe_allow_html=True,
    )

    df_disc = data_layer.get_discursos(db_path)
    if df_disc.empty:
        st.info("No hay discursos cargados para este run.")
        return
    codigos = sorted(df_disc["codigo"].astype(str).unique().tolist())
    codigo = st.selectbox("Discurso", codigos, key="rev_codigo")

    overlay_path = default_overlay_path(db_path)
    try:
        ov = RevisionOverlay(overlay_path)
    except OverlayCorruptError as exc:
        st.error(
            f"El archivo de revisión está dañado y no se tocó. Revisalo o "
            f"movelo a un lado:\n\n`{exc}`"
        )
        return

    st.caption(f"Ediciones guardadas en `{overlay_path}` (aparte de las bases).")

    _render_header(ov, codigo, data_layer.get_discurso_header(db_path, codigo))

    df_fr = data_layer.get_frases(db_path, [codigo])
    if df_fr.empty:
        st.info("Este discurso no tiene frases procesadas.")
        return
    actores_by_frase = data_layer.get_actores_por_frase(db_path, codigo)
    emos_full = data_layer.get_emociones_full(db_path, codigo)
    emos_by_frase: dict[int, list[dict[str, Any]]] = {}
    for em in emos_full:
        emos_by_frase.setdefault(int(em["frase_idx"]), []).append(em)

    kb_ids = _kb_ids(db_path, ov)
    kb_disp = _kb_display(db_path, ov)
    fuente_canon = data_layer.get_fuente_canonicos_map(db_path, codigo)
    exp_canon = data_layer.get_experienciador_canonicos_map(db_path, codigo)

    st.markdown("<hr class='ep-divider'>", unsafe_allow_html=True)

    only_sug = st.toggle(
        "🔎 Solo emociones con sugerencias del juez sin resolver",
        key=f"rev_sugfilter_{codigo}",
    )

    frases_sorted = df_fr.sort_values("unit_idx")
    if only_sug:
        frases_list: list[tuple[Any, list[dict[str, Any]]]] = []
        n_sug_total = 0
        for _, fr in frases_sorted.iterrows():
            ui = int(fr["unit_idx"])
            pend = [
                e for e in emos_by_frase.get(ui, [])
                if _emotion_pending_sug_count(ov, codigo, ui, e) > 0
            ]
            if pend:
                n_sug_total += sum(
                    _emotion_pending_sug_count(ov, codigo, ui, e) for e in pend
                )
                frases_list.append((fr, pend))
        st.caption(
            f"{n_sug_total} sugerencia(s) sin resolver en "
            f"{len(frases_list)} frase(s)."
            if frases_list else "No hay sugerencias del juez sin resolver. 🎉"
        )
    else:
        frases_list = [
            (fr, emos_by_frase.get(int(fr["unit_idx"]), []))
            for _, fr in frases_sorted.iterrows()
        ]

    total = len(frases_list)
    c1, c2 = st.columns([1, 2])
    with c1:
        page_size = st.selectbox(
            "Frases por página", [10, 20, 50, 100], index=0,
            key=f"rev_ps_{codigo}",
        )
    n_pages = max(1, (total + page_size - 1) // page_size)
    with c2:
        page = int(st.number_input(
            "Página", min_value=1, max_value=n_pages, value=1, step=1,
            key=f"rev_pg_{codigo}_{page_size}_{int(only_sug)}",
        ))
    start = (page - 1) * page_size
    end = min(start + page_size, total)
    if total:
        st.caption(f"Frases {start + 1}–{end} de {total} · página {page}/{n_pages}.")

    for fr, emos in frases_list[start:end]:
        _render_frase(
            ov, codigo,
            unit_idx=int(fr["unit_idx"]),
            frase=str(fr["frase"]),
            actores=actores_by_frase.get(int(fr["unit_idx"]), []),
            emociones=emos,
            kb_ids=kb_ids,
            kb_disp=kb_disp,
            fuente_canon=fuente_canon,
            exp_canon=exp_canon,
        )


# ── Header (una sola vez) ────────────────────────────────────────────────────

def _render_header(ov: RevisionOverlay, codigo: str, header: dict[str, Any]) -> None:
    disc_ov = ov.get_discurso(codigo)
    overrides = disc_ov.get("overrides", {})

    def eff(field: str) -> str:
        return str(overrides.get(field, header.get(field) or "") or "")

    enunciatarios = header.get("enunciatarios")
    enun_str = ""
    if isinstance(enunciatarios, list):
        nombres = [
            str(e.get("actor") or e.get("nombre") or e.get("tipo") or "")
            for e in enunciatarios if isinstance(e, dict)
        ]
        enun_str = "; ".join(n for n in nombres if n)
    elif enunciatarios:
        enun_str = str(enunciatarios)

    titulo = header.get("titulo") or codigo
    st.markdown(
        f"<div class='ep-card ep-card-accent'>"
        f"<p style='margin:0;font-family:var(--font-serif);font-size:1.2rem;"
        f"color:var(--accent);'>{_esc(titulo)}</p>"
        f"<p style='margin:0.2rem 0 0;color:#8a8799;font-size:0.82rem;"
        f"font-family:DM Mono,monospace;'>{_esc(codigo)}"
        + (f" · {_esc(header.get('fecha'))}" if header.get("fecha") else "")
        + (f" · enunciatarios: {_esc(enun_str)}" if enun_str else "")
        + "</p></div>",
        unsafe_allow_html=True,
    )

    if _toggle("Editar cabecera (tipo, lugar, enunciador)", f"rev_hdr_{codigo}"):
        for field, label in (
            ("tipo_discurso", "Tipo de discurso"),
            ("lugar", "Lugar"),
            ("enunciador", "Enunciador"),
        ):
            c1, c2 = st.columns([4, 1])
            with c1:
                new = st.text_input(label, value=eff(field), key=f"hdr_{codigo}_{field}")
            with c2:
                st.checkbox(
                    "✓ ok", value=bool(disc_ov.get("confirmado", {}).get(field)),
                    key=f"hdrok_{codigo}_{field}",
                    on_change=_on_confirm_header, args=(ov, codigo, field),
                )
            if new != eff(field):
                if new.strip() and new != str(header.get(field) or ""):
                    ov.set_discurso_override(codigo, field, new)
                else:
                    ov.clear_discurso_override(codigo, field)
                st.rerun()


def _on_confirm_header(ov: RevisionOverlay, codigo: str, field: str) -> None:
    ov.confirm_discurso_field(codigo, field, st.session_state[f"hdrok_{codigo}_{field}"])


# ── Frase ────────────────────────────────────────────────────────────────────

#: Cuántas tarjetas de emoción por fila (al costado, no apiladas).
_EMOS_PER_ROW = 2


def _emotion_pending_sug_count(
    ov: RevisionOverlay, codigo: str, unit_idx: int, em: dict[str, Any],
) -> int:
    """Cuántas sugerencias del juez de esta emoción siguen SIN resolver
    (ni aceptadas ni rechazadas en el overlay)."""
    sugs = (em.get("juicio") or {}).get("sugerencias") or []
    if not sugs:
        return 0
    states = ov.get_suggestion_states(codigo, unit_idx, int(em["emocion_idx"]))
    return sum(
        1 for s in sugs
        if s.get("campo") and states.get(s["campo"]) not in ("accepted", "rejected")
    )


def _render_frase(
    ov: RevisionOverlay, codigo: str, *, unit_idx: int, frase: str,
    actores: list[dict[str, Any]], emociones: list[dict[str, Any]],
    kb_ids: list[str], kb_disp: dict[str, str],
    fuente_canon: dict[tuple[int, int], list[str]] | None = None,
    exp_canon: dict[tuple[int, int], str] | None = None,
) -> None:
    activos = [
        e for e in emociones
        if not ov.is_emocion_deleted(codigo, unit_idx, int(e["emocion_idx"]))
    ]
    eliminadas = [
        e for e in emociones
        if ov.is_emocion_deleted(codigo, unit_idx, int(e["emocion_idx"]))
    ]
    n_nuevas = len(ov.list_new_emociones(codigo, unit_idx))
    n_act = len(actores) + len(ov.get_frase(codigo, unit_idx).get("actores_agregados", []))

    st.markdown(
        f"<div style='margin:0.9rem 0 0.3rem;padding:0.55rem 0.75rem;"
        f"background:#15171c;border-left:3px solid var(--accent);border-radius:6px;"
        f"font-size:0.95rem;line-height:1.6;color:#d8d3ca;'>"
        f"<span style='color:#5a5d6e;font-family:DM Mono,monospace;font-size:0.76rem;'>"
        f"#{unit_idx}</span>&nbsp; {_esc(frase)}</div>",
        unsafe_allow_html=True,
    )
    st.caption(
        f"{len(activos) + n_nuevas} emoción(es) · {n_act} actor(es)"
        + (f" · {len(eliminadas)} eliminada(s)" if eliminadas else "")
    )

    # Emociones al costado, en tarjetas, de a _EMOS_PER_ROW por fila.
    for i in range(0, len(activos), _EMOS_PER_ROW):
        fila = activos[i:i + _EMOS_PER_ROW]
        cols = st.columns(_EMOS_PER_ROW, gap="small")
        for col, em in zip(cols, fila):
            with col:
                _render_emocion_card(
                    ov, codigo, unit_idx, em, kb_ids, kb_disp,
                    fuente_canon or {}, exp_canon or {},
                )

    if eliminadas:
        _render_deleted_emociones(ov, codigo, unit_idx, eliminadas)
    _render_new_emociones(ov, codigo, unit_idx)

    with st.expander(f"Actores nombrados ({n_act}) · agregar emoción", expanded=False):
        _render_actores(ov, codigo, unit_idx, actores, kb_ids, kb_disp)
        st.markdown("<hr class='ep-divider'>", unsafe_allow_html=True)
        _render_add_emocion(ov, codigo, unit_idx)

    st.markdown(
        "<div style='border-bottom:1px solid #1a1c22;margin:0.5rem 0;'></div>",
        unsafe_allow_html=True,
    )


def _render_deleted_emociones(
    ov: RevisionOverlay, codigo: str, unit_idx: int,
    eliminadas: list[dict[str, Any]],
) -> None:
    for em in eliminadas:
        eidx = int(em["emocion_idx"])
        c1, c2 = st.columns([5, 1])
        with c1:
            st.markdown(
                f"<span style='text-decoration:line-through;opacity:0.5;"
                f"font-size:0.82rem;'>emoción #{eidx} eliminada "
                f"({_esc(em.get('tipo_emocion'))})</span>",
                unsafe_allow_html=True,
            )
        with c2:
            if st.button("Restaurar", key=f"emres_{codigo}_{unit_idx}_{eidx}"):
                ov.restore_emocion(codigo, unit_idx, eidx)
                st.rerun()


# ── Actores de la frase ──────────────────────────────────────────────────────

def _render_actores(
    ov: RevisionOverlay, codigo: str, unit_idx: int,
    actores: list[dict[str, Any]], kb_ids: list[str],
    kb_disp: dict[str, str],
) -> None:
    fr_ov = ov.get_frase(codigo, unit_idx)
    removed = set(fr_ov.get("actores_removidos", []))

    for i, link in enumerate(actores):
        key = str(i)
        mencion = str(link.get("actor_mencionado", ""))
        canon = link.get("actor_canonico")
        resuelto = link.get("resuelto_por")
        badge = (
            " <span style='color:#7c9ec8;font-size:0.7rem;'>[deixis]</span>"
            if resuelto == "deixis_enunciador" else ""
        )
        is_removed = key in removed
        style = "text-decoration:line-through;opacity:0.5;" if is_removed else ""
        c1, c2 = st.columns([5, 1])
        with c1:
            st.markdown(
                f"<span style='{style}font-size:0.86rem;'>{_esc(mencion)}"
                f"<span style='color:#5a5d6e;'> → </span>"
                f"<code>{_esc(_canon_label(canon, kb_disp)) if canon else '∅'}</code>{badge}</span>",
                unsafe_allow_html=True,
            )
        with c2:
            if is_removed:
                if st.button("Restaurar", key=f"acr_{codigo}_{unit_idx}_{i}"):
                    ov.restore_actor(codigo, unit_idx, key)
                    st.rerun()
            else:
                if st.button("Quitar", key=f"acx_{codigo}_{unit_idx}_{i}"):
                    ov.remove_actor(codigo, unit_idx, key)
                    st.rerun()

    # Actores agregados a mano.
    for pos, a in enumerate(fr_ov.get("actores_agregados", [])):
        c1, c2 = st.columns([5, 1])
        with c1:
            st.markdown(
                f"<span style='font-size:0.86rem;color:#6ec89a;'>+ "
                f"{_esc(a.get('actor_mencionado'))}"
                f"<span style='color:#5a5d6e;'> → </span>"
                f"<code>{_esc(_canon_label(a.get('actor_canonico'), kb_disp))}</code></span>",
                unsafe_allow_html=True,
            )
        with c2:
            if st.button("Borrar", key=f"acdel_{codigo}_{unit_idx}_{pos}"):
                ov.remove_added_actor(codigo, unit_idx, pos)
                st.rerun()

    _render_add_actor(ov, codigo, unit_idx, kb_ids)


def _render_add_actor(
    ov: RevisionOverlay, codigo: str, unit_idx: int, kb_ids: list[str],
) -> None:
    if not _toggle("+ agregar actor", f"rev_addact_{codigo}_{unit_idx}"):
        return
    mencion = st.text_input("Mención", key=f"addact_men_{codigo}_{unit_idx}")
    modo = st.radio(
        "Vincular a", ["Actor existente de la KB", "Actor nuevo"],
        key=f"addact_modo_{codigo}_{unit_idx}", horizontal=True,
    )
    if modo == "Actor existente de la KB":
        canon = st.selectbox(
            "Canónico", kb_ids or ["(KB vacía)"], key=f"addact_canon_{codigo}_{unit_idx}",
        )
        if st.button("Agregar", key=f"addact_btn_{codigo}_{unit_idx}",
                     disabled=not mencion.strip() or not kb_ids):
            ov.add_actor(codigo, unit_idx, {
                "actor_mencionado": mencion.strip(),
                "actor_canonico": canon,
                "es_nuevo": False,
                "origen": "revision",
            })
            st.session_state.pop(f"addact_men_{codigo}_{unit_idx}", None)
            st.rerun()
    else:
        from emoparse.core.text import slugify
        nombre = st.text_input("Nombre del actor nuevo", key=f"addact_nom_{codigo}_{unit_idx}")
        tipo = st.selectbox("Tipo", _KB_TIPOS, key=f"addact_tipo_{codigo}_{unit_idx}")
        slug = slugify(nombre) if nombre.strip() else ""
        exists = bool(slug) and slug in set(kb_ids)
        if nombre.strip():
            st.caption(
                f"⚠️ ya existe `{slug}` en la KB" if exists
                else f"canonical_id propuesto: `{slug}`"
            )
        if st.button("Crear y agregar", key=f"addact_new_{codigo}_{unit_idx}",
                     disabled=not (mencion.strip() and slug) or exists):
            try:
                ov.propose_actor(slug, nombre.strip(), tipo, set(kb_ids))
            except ValueError as e:
                st.error(str(e))
                return
            ov.add_actor(codigo, unit_idx, {
                "actor_mencionado": mencion.strip(),
                "actor_canonico": slug,
                "es_nuevo": True,
                "origen": "revision_nuevo",
            })
            for k in ("men", "nom"):
                st.session_state.pop(f"addact_{k}_{codigo}_{unit_idx}", None)
            st.rerun()


# ── Emoción (tarjeta) ────────────────────────────────────────────────────────

def _render_emocion_card(
    ov: RevisionOverlay, codigo: str, unit_idx: int,
    em: dict[str, Any], kb_ids: list[str], kb_disp: dict[str, str],
    fuente_canon: dict[tuple[int, int], list[str]] | None = None,
    exp_canon: dict[tuple[int, int], str] | None = None,
) -> None:
    """Tarjeta de UNA emoción: info completa en solo-lectura; la edición de cada
    campo aparece vacía y solo al pulsar su botón, con confirmación visible."""
    eidx = int(em["emocion_idx"])
    eff = ov.effective_emocion(codigo, unit_idx, eidx, em)
    confirmado = eff.get("_confirmado", {})

    tipo = eff.get("tipo_emocion_canonico") or eff.get("tipo_emocion") or "?"
    canon_exp = _canon_display(eff.get("experienciador_canonico"), kb_disp)
    deixis_cids = (exp_canon or {}).get((unit_idx, eidx)) or []
    if not canon_exp and deixis_cids:
        canon_exp = _canon_label(deixis_cids[0], kb_disp)
        if len(deixis_cids) > 1:
            canon_exp += f" (+{len(deixis_cids) - 1})"

    juicio = em.get("juicio") or {}
    sug_by_path: dict[tuple[str, ...], dict[str, Any]] = {}
    for s in (juicio.get("sugerencias") or []):
        campo = s.get("campo")
        if campo:
            sug_by_path[tuple(str(campo).split("."))] = s
    sctx: dict[str, Any] = {
        "by_path": sug_by_path,
        "states": ov.get_suggestion_states(codigo, unit_idx, eidx),
        "rendered": set(),
    }

    with st.container(border=True):
        conf = "✓ " if confirmado.get("_emocion") else ""
        st.markdown(
            f"<div style='font-size:0.92rem;margin-bottom:0.1rem;'>"
            f"<span style='color:#5a5d6e;font-family:DM Mono,monospace;"
            f"font-size:0.72rem;'>#{eidx}</span> "
            f"<span style='color:var(--accent);font-weight:600;'>{_esc(conf)}"
            f"{_esc(tipo)}</span></div>",
            unsafe_allow_html=True,
        )
        if juicio:
            coh = juicio.get("coherente")
            n_sug = len(juicio.get("sugerencias") or [])
            if coh is True:
                jtxt, jcol = "✓ juez: correcto", "#6ec89a"
            elif coh is False:
                jtxt, jcol = "⚠ juez: revisar", "#c9a86a"
            else:
                jtxt, jcol = "juez: —", "#5a5d6e"
            if n_sug:
                jtxt += f" · {n_sug} sug."
            st.markdown(
                f"<div style='font-size:0.72rem;color:{jcol};margin-bottom:0.3rem;'>"
                f"{_esc(jtxt)}</div>",
                unsafe_allow_html=True,
            )

        det = em
        fuente_cids = (fuente_canon or {}).get((unit_idx, eidx)) or []
        canon_fte = "; ".join(_canon_label(c, kb_disp) for c in fuente_cids)
        _element(ov, codigo, unit_idx, eidx, label="Experienciador",
                 path=["experienciador"], value=det.get("experienciador"),
                 det_value=det.get("experienciador"), sctx=sctx,
                 canonico=canon_exp, marca=det.get("experienciador_marca"))
        _element(ov, codigo, unit_idx, eidx, label="Tipo de emoción",
                 path=["tipo_emocion"], value=det.get("tipo_emocion"),
                 det_value=det.get("tipo_emocion"), sctx=sctx,
                 canonico=det.get("tipo_emocion_canonico"))
        _element(ov, codigo, unit_idx, eidx, label="Modo de existencia",
                 path=["modo_existencia"], value=eff.get("modo_existencia"),
                 det_value=det.get("modo_existencia"), sctx=sctx)
        _element(ov, codigo, unit_idx, eidx, label="Fuente",
                 path=["fuente_inferencia"], value=det.get("fuente_inferencia"),
                 det_value=det.get("fuente_inferencia"), sctx=sctx,
                 canonico=canon_fte or None, marca=det.get("fuente_marca"))
        _element(ov, codigo, unit_idx, eidx, label="Configuración",
                 path=["tipo_configuracion"], value=eff.get("tipo_configuracion"),
                 det_value=det.get("tipo_configuracion"), sctx=sctx)

        carac = eff.get("caracterizacion") or {}
        det_carac = det.get("caracterizacion") or {}
        if carac:
            _section("Caracterización")
            for f in ("foria", "dominancia", "intensidad", "duracion",
                      "tipo_atribucion", "temporalidad", "aspecto"):
                if f in carac:
                    _element(ov, codigo, unit_idx, eidx, label=f,
                             path=["caracterizacion", f], value=carac.get(f),
                             det_value=det_carac.get(f), sctx=sctx,
                             just=carac.get(f + "_justificacion"))

        actantes = eff.get("actantes") or {}
        det_act = det.get("actantes") or {}
        if actantes:
            _section("Actantes")
            for ak, leaf in (
                ("mediador", "tipo"),
                ("verificador_normativo", "tipo"),
                ("verificador_normativo", "evaluacion"),
                ("verificador_observacional", "tipo"),
                ("verificador_observacional", "evaluacion"),
                ("operador_modificacion", "funcion"),
                ("polaridad", "tipo"),
            ):
                sub = actantes.get(ak)
                if isinstance(sub, dict) and leaf in sub:
                    dsub = det_act.get(ak) if isinstance(det_act.get(ak), dict) else {}
                    _element(ov, codigo, unit_idx, eidx, label=f"{ak} · {leaf}",
                             path=["actantes", ak, leaf], value=sub.get(leaf),
                             det_value=dsub.get(leaf), sctx=sctx,
                             just=(sub.get("justificacion")
                                   if leaf in ("funcion", "tipo") else None))

        for path, sug in sug_by_path.items():
            if path not in sctx["rendered"]:
                _render_suggestion(ov, codigo, unit_idx, eidx, list(path), sug,
                                   sctx["states"].get(".".join(path)))

        st.markdown("<div style='height:0.3rem;'></div>", unsafe_allow_html=True)
        st.checkbox(
            "✓ Confirmar correcta",
            value=bool(confirmado.get("_emocion")),
            key=f"emok_{codigo}_{unit_idx}_{eidx}",
            on_change=_on_confirm_emocion, args=(ov, codigo, unit_idx, eidx),
        )
        fc1, fc2 = st.columns(2)
        with fc1:
            if st.button("Revertir", key=f"emrev_{codigo}_{unit_idx}_{eidx}",
                         use_container_width=True):
                _revert_emocion(ov, codigo, unit_idx, eidx)
                st.rerun()
        with fc2:
            if st.button("Eliminar", key=f"emdel_{codigo}_{unit_idx}_{eidx}",
                         use_container_width=True):
                ov.delete_emocion(codigo, unit_idx, eidx)
                st.rerun()


def _section(title: str) -> None:
    st.markdown(
        f"<div class='ep-sec-h'>{_esc(title)}</div>",
        unsafe_allow_html=True,
    )


def _on_confirm_emocion(ov: RevisionOverlay, codigo: str, unit_idx: int, eidx: int) -> None:
    ov.confirm_emocion_field(
        codigo, unit_idx, eidx, "_emocion",
        st.session_state[f"emok_{codigo}_{unit_idx}_{eidx}"],
    )


def _revert_emocion(ov: RevisionOverlay, codigo: str, unit_idx: int, eidx: int) -> None:
    node = ov._emo(codigo, unit_idx, eidx)  # noqa: SLF001 - revertir todos los overrides
    node["overrides"] = {}
    node["sugerencias"] = {}
    ov._save()  # noqa: SLF001


def _override_at(
    ov: RevisionOverlay, codigo: str, unit_idx: int, eidx: int, path: list[str],
) -> tuple[bool, Any]:
    """(True, valor) si hay override del analista en `path`; (False, None) si no."""
    node: Any = ov.get_emocion(codigo, unit_idx, eidx).get("overrides", {})
    for p in path:
        if not isinstance(node, dict) or p not in node:
            return False, None
        node = node[p]
    return True, node


def _fmt_val(v: Any) -> str:
    if v is None:
        return "—"
    if isinstance(v, (list, tuple)):
        return "; ".join(str(x) for x in v if str(x).strip()) or "—"
    return str(v).strip() or "—"


def _element(
    ov: RevisionOverlay, codigo: str, unit_idx: int, eidx: int, *,
    label: str, path: list[str], value: Any, det_value: Any,
    sctx: dict[str, Any], canonico: Any = None, marca: Any = None,
    just: Any = None,
) -> None:
    """Un elemento del simulacro, en una línea compacta.

    Por defecto el valor PRINCIPAL es el canónico (lo revisado en Referentes);
    si el analista corrige el campo acá, pasa a ser la corrección. La inferencia
    del LLM y la marca quedan chicas, como contexto secundario. La edición
    aparece vacía y solo al pulsar ✎."""
    leaf = path[-1]
    opts = _OPTS.get(leaf)
    has_ov, ov_val = _override_at(ov, codigo, unit_idx, eidx, path)
    ekey = f"ed_{codigo}_{unit_idx}_{eidx}_{'.'.join(path)}"

    if has_ov:
        main = _fmt_val(ov_val)
    elif canonico not in (None, "", []):
        main = _fmt_val(canonico)
    else:
        main = _fmt_val(value)

    chip = "<span class='chip'> ✎ corregido</span>" if has_ov else ""
    parts: list[str] = []
    llm_txt = _fmt_val(det_value)
    if det_value is not None and llm_txt not in ("—", main):
        parts.append(f"LLM: {_esc(llm_txt)}")
    if marca:
        m = _fmt_val(marca)
        if m not in ("—", llm_txt, main):
            parts.append(f"marca: {_esc(m)}")
    if canonico not in (None, "", []):
        c = _fmt_val(canonico)
        if c != main and c != "—":
            parts.append(f"canónico: {_esc(c)}")
    sec = f"<span class='sec'> · {' · '.join(parts)}</span>" if parts else ""
    just_html = f"<span class='just'>{_esc(just)}</span>" if just else ""

    cv, cb = st.columns([13, 1], gap="small")
    with cv:
        st.markdown(
            f"<div class='ep-el'><b style='color:#8a8799;'>{_esc(label)}:</b> "
            f"<span style='color:#e0dccf;'>{_esc(main)}</span>{chip}{sec}"
            f"{just_html}</div>",
            unsafe_allow_html=True,
        )
    with cb:
        if st.button("✎", key=f"edb_{ekey}", help=f"Editar {label}"):
            st.session_state[ekey] = not st.session_state.get(ekey, False)

    key_str = ".".join(path)
    sug = sctx["by_path"].get(tuple(path))
    if sug is not None:
        sctx["rendered"].add(tuple(path))
        _render_suggestion(ov, codigo, unit_idx, eidx, path, sug,
                           sctx["states"].get(key_str))

    if has_ov:
        if st.button("↺ deshacer", key=f"und_{ekey}"):
            ov.clear_emocion_override_path(codigo, unit_idx, eidx, path)
            st.session_state.pop(ekey, None)
            st.rerun()

    if st.session_state.get(ekey, False):
        _render_edit_input(ov, codigo, unit_idx, eidx, path, opts, ekey)


def _render_edit_input(
    ov: RevisionOverlay, codigo: str, unit_idx: int, eidx: int,
    path: list[str], opts: list[str] | None, ekey: str,
) -> None:
    inkey = f"in_{ekey}"
    if opts:
        choice = st.selectbox(
            "nuevo valor", ["— elegir —"] + list(opts), index=0,
            key=inkey, label_visibility="collapsed",
        )
        newval: Any = None if choice == "— elegir —" else choice
    else:
        txt = st.text_input(
            "nuevo valor", value="", key=inkey,
            placeholder="escribí la corrección…", label_visibility="collapsed",
        )
        newval = txt.strip() or None
    ec1, ec2 = st.columns(2)
    with ec1:
        if st.button("guardar", key=f"sv_{ekey}", use_container_width=True):
            if newval is None:
                st.toast("Escribí o elegí un valor.", icon="⚠️")
            else:
                ov.set_emocion_override_path(codigo, unit_idx, eidx, path, newval)
                st.session_state[ekey] = False
                st.session_state.pop(inkey, None)
                st.rerun()
    with ec2:
        if st.button("cancelar", key=f"cx_{ekey}", use_container_width=True):
            st.session_state[ekey] = False
            st.session_state.pop(inkey, None)
            st.rerun()


def _render_suggestion(
    ov: RevisionOverlay, codigo: str, unit_idx: int, eidx: int,
    path: list[str], sug: dict[str, Any], state: str | None,
) -> None:
    """Sugerencia del juez sobre un elemento: aceptar / rechazar."""
    campo = ".".join(path)
    valor = str(sug.get("valor_sugerido", ""))
    just = str(sug.get("justificacion", ""))
    base = f"sug_{codigo}_{unit_idx}_{eidx}_{campo}"
    if state in ("accepted", "rejected"):
        icon = "🟢 aceptada" if state == "accepted" else "⚪ rechazada"
        col = "#6ec89a" if state == "accepted" else "#8a8799"
        cs1, cs2 = st.columns([4, 1])
        with cs1:
            st.markdown(
                f"<div style='font-size:0.7rem;color:{col};margin:0 0 0.15rem 0.4rem;'>"
                f"💡 sugerencia {icon}: <code>{_esc(valor)}</code></div>",
                unsafe_allow_html=True,
            )
        with cs2:
            if st.button("↺", key=f"{base}_undo", help="Reconsiderar"):
                ov.clear_suggestion_state(codigo, unit_idx, eidx, campo)
                st.rerun()
        return
    st.markdown(
        f"<div style='font-size:0.7rem;color:#c9a86a;margin:0 0 0.1rem 0.4rem;'>"
        f"💡 juez sugiere <b>{_esc(valor)}</b>"
        + (f" — {_esc(just)}" if just else "")
        + "</div>",
        unsafe_allow_html=True,
    )
    cs1, cs2 = st.columns(2)
    with cs1:
        if st.button("aceptar sug.", key=f"{base}_ok", use_container_width=True):
            ov.set_emocion_override_path(codigo, unit_idx, eidx, path, valor)
            ov.set_suggestion_state(codigo, unit_idx, eidx, campo, "accepted")
            st.rerun()
    with cs2:
        if st.button("rechazar", key=f"{base}_no", use_container_width=True):
            ov.set_suggestion_state(codigo, unit_idx, eidx, campo, "rejected")
            st.rerun()


# ── Emociones nuevas / agregar ───────────────────────────────────────────────

def _render_new_emociones(ov: RevisionOverlay, codigo: str, unit_idx: int) -> None:
    for pos, em in enumerate(ov.list_new_emociones(codigo, unit_idx)):
        c1, c2 = st.columns([5, 1])
        with c1:
            st.markdown(
                f"<span style='font-size:0.85rem;color:#6ec89a;'>+ emoción nueva: "
                f"{_esc(em.get('tipo_emocion'))} · {_esc(em.get('experienciador'))}"
                f"</span>",
                unsafe_allow_html=True,
            )
        with c2:
            if st.button("Borrar", key=f"emnewdel_{codigo}_{unit_idx}_{pos}"):
                ov.remove_new_emocion(codigo, unit_idx, pos)
                st.rerun()


def _render_add_emocion(ov: RevisionOverlay, codigo: str, unit_idx: int) -> None:
    if not _toggle("+ agregar emoción", f"rev_addem_{codigo}_{unit_idx}"):
        return
    exp = st.text_input("Experienciador", key=f"addem_exp_{codigo}_{unit_idx}")
    tipo = st.text_input("Tipo de emoción", key=f"addem_tipo_{codigo}_{unit_idx}")
    modo = st.selectbox(
        "Modo de existencia",
        _OPTS.get("modo_existencia", ["realizada"]),
        key=f"addem_modo_{codigo}_{unit_idx}",
    )
    fuente = st.text_input("Fuente de la emoción", key=f"addem_fte_{codigo}_{unit_idx}")
    if st.button("Agregar emoción", key=f"addem_btn_{codigo}_{unit_idx}",
                 disabled=not (exp.strip() and tipo.strip())):
        ov.add_emocion(codigo, unit_idx, {
            "experienciador": exp.strip(),
            "tipo_emocion": tipo.strip(),
            "modo_existencia": modo,
            "fuente_inferencia": fuente.strip(),
            "origen": "revision",
        })
        for k in ("exp", "tipo"):
            st.session_state.pop(f"addem_{k}_{codigo}_{unit_idx}", None)
        st.rerun()


# ── Helpers ──────────────────────────────────────────────────────────────────

def _kb_ids(db_path: Path, ov: RevisionOverlay) -> list[str]:
    """canonical_ids del referentes_kb + los propuestos en el overlay (para no chocar)."""
    ids: set[str] = set(ov.list_proposed_actors().keys())
    ids |= set(_referentes_kb_index().keys())
    return sorted(ids)
