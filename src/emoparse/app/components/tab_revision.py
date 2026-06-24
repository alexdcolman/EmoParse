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
#: fuente de verdad; si no se puede, se cae a text inputs (sin opciones).
try:
    from typing import get_args

    from emoparse.core import schemas as _sc

    _OPTS: dict[str, list[str]] = {
        "foria": list(get_args(_sc.Foria)),
        "intensidad": list(get_args(_sc.Intensidad)),
        "dominancia": list(get_args(_sc.Dominancia)),
        "duracion": list(get_args(_sc.TipoDuracion)),
        "atribucion": list(get_args(_sc.TipoAtribucion)),
        "modo_existencia": list(get_args(_sc.ModoExistenciaEmocion)),
        "tipo_configuracion": list(get_args(_sc.TipoConfiguracion)),
        "fuente_marca": list(get_args(_sc.FuenteMarca)),
        "fuente_inferencia": list(get_args(_sc.FuenteInferencia)),
    }
except Exception:  # pragma: no cover - fallback defensivo
    _OPTS = {
        "foria": ["euforico", "disforico", "aforico", "ambiforico", "indeterminado"],
        "intensidad": ["alta", "baja", "neutra_ambivalente"],
    }

_KB_TIPOS = ("individuo", "institucion", "colectivo", "desconocido")
_ACTANTE_KEYS = (
    "mediador", "verificador_normativo", "verificador_observacional",
    "operador_modificacion",
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
    fuente_canon = data_layer.get_fuente_canonico_map(db_path, codigo)
    exp_canon = data_layer.get_experienciador_canonico_map(db_path, codigo)

    st.markdown("<hr class='ep-divider'>", unsafe_allow_html=True)
    for _, fr in df_fr.sort_values("unit_idx").iterrows():
        _render_frase(
            ov, codigo,
            unit_idx=int(fr["unit_idx"]),
            frase=str(fr["frase"]),
            actores=actores_by_frase.get(int(fr["unit_idx"]), []),
            emociones=emos_by_frase.get(int(fr["unit_idx"]), []),
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

def _render_frase(
    ov: RevisionOverlay, codigo: str, *, unit_idx: int, frase: str,
    actores: list[dict[str, Any]], emociones: list[dict[str, Any]],
    kb_ids: list[str], kb_disp: dict[str, str],
    fuente_canon: dict[tuple[int, int], str] | None = None,
    exp_canon: dict[tuple[int, int], str] | None = None,
) -> None:
    n_emo = len([
        e for e in emociones
        if not ov.is_emocion_deleted(codigo, unit_idx, int(e["emocion_idx"]))
    ]) + len(ov.list_new_emociones(codigo, unit_idx))
    n_act = len(actores) + len(ov.get_frase(codigo, unit_idx).get("actores_agregados", []))

    st.markdown(
        f"<p style='margin:0.6rem 0 0.2rem;font-size:0.95rem;line-height:1.6;'>"
        f"<span style='color:#5a5d6e;font-family:DM Mono,monospace;font-size:0.78rem;'>"
        f"#{unit_idx}</span>&nbsp; {_esc(frase)}</p>",
        unsafe_allow_html=True,
    )
    if _toggle(
        f"actores ({n_act}) · emociones ({n_emo})",
        f"rev_fr_{codigo}_{unit_idx}",
    ):
        st.markdown("**Actores nombrados**")
        _render_actores(ov, codigo, unit_idx, actores, kb_ids, kb_disp)
        st.markdown("**Emociones**")
        for em in emociones:
            _render_emocion(ov, codigo, unit_idx, em, kb_ids, kb_disp,
                            fuente_canon or {}, exp_canon or {})
        _render_new_emociones(ov, codigo, unit_idx)
        _render_add_emocion(ov, codigo, unit_idx)
    st.markdown(
        "<div style='border-bottom:1px solid #1a1c22;margin:0.4rem 0;'></div>",
        unsafe_allow_html=True,
    )


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


# ── Emoción ──────────────────────────────────────────────────────────────────

def _render_emocion(
    ov: RevisionOverlay, codigo: str, unit_idx: int,
    em: dict[str, Any], kb_ids: list[str], kb_disp: dict[str, str],
    fuente_canon: dict[tuple[int, int], str] | None = None,
    exp_canon: dict[tuple[int, int], str] | None = None,
) -> None:
    eidx = int(em["emocion_idx"])
    eff = ov.effective_emocion(codigo, unit_idx, eidx, em)
    deleted = eff.get("_deleted")
    confirmado = eff.get("_confirmado", {})

    if deleted:
        c1, c2 = st.columns([5, 1])
        with c1:
            st.markdown(
                f"<span style='text-decoration:line-through;opacity:0.5;"
                f"font-size:0.85rem;'>emoción #{eidx} eliminada "
                f"({_esc(em.get('tipo_emocion'))})</span>",
                unsafe_allow_html=True,
            )
        with c2:
            if st.button("Restaurar", key=f"emres_{codigo}_{unit_idx}_{eidx}"):
                ov.restore_emocion(codigo, unit_idx, eidx)
                st.rerun()
        return

    tipo = eff.get("tipo_emocion_canonico") or eff.get("tipo_emocion") or "?"
    raw_exp = eff.get("experienciador") or "?"
    # Canónico del experienciador: prioriza el override de revisión; si no hay,
    # usa el resuelto por la base de marcas (incluye deixis: "yo" → "javier_milei").
    canon_exp = _canon_display(eff.get("experienciador_canonico"), kb_disp)
    if not canon_exp:
        deixis_cid = (exp_canon or {}).get((unit_idx, eidx))
        if deixis_cid:
            canon_exp = _canon_label(deixis_cid, kb_disp)
    if canon_exp and canon_exp != raw_exp:
        exp_eff = f"{canon_exp} ⟵ canónico (LLM: {raw_exp})"
    else:
        exp_eff = canon_exp or raw_exp
    chk = "✓ " if confirmado.get("_emocion") else ""
    if not _toggle(
        f"{chk}#{eidx} · {tipo} · {exp_eff}",
        f"rev_em_{codigo}_{unit_idx}_{eidx}",
    ):
        return

    fcanon = (fuente_canon or {}).get((unit_idx, eidx))
    if fcanon:
        st.markdown(
            f"<p style='font-size:0.78rem;color:#5a5d6e;'>fuente · "
            f"canónico (vale): <code>{_esc(_canon_label(fcanon, kb_disp))}</code></p>",
            unsafe_allow_html=True,
        )

    base = ["experienciador", "experienciador_canonico", "tipo_emocion",
            "modo_existencia", "fuente_marca", "fuente_inferencia", 
            "tipo_configuracion"]
    st.markdown("<u>Detección</u>", unsafe_allow_html=True)
    for f in base:
        _edit_scalar(ov, codigo, unit_idx, eidx, [f], f, eff.get(f))

    carac = eff.get("caracterizacion") or {}
    if carac:
        st.markdown("<u>Caracterización</u>", unsafe_allow_html=True)
        for f, v in carac.items():
            _edit_scalar(ov, codigo, unit_idx, eidx, ["caracterizacion", f], f, v)

    actantes = eff.get("actantes") or {}
    if actantes:
        st.markdown("<u>Actantes</u>", unsafe_allow_html=True)
        for ak in _ACTANTE_KEYS:
            sub = actantes.get(ak)
            if isinstance(sub, dict) and sub:
                st.markdown(f"<i>{ak}</i>", unsafe_allow_html=True)
                for f, v in sub.items():
                    _edit_scalar(ov, codigo, unit_idx, eidx,
                                 ["actantes", ak, f], f, v)
            elif sub is not None:
                _edit_scalar(ov, codigo, unit_idx, eidx, ["actantes", ak], ak, sub)

    juicio = em.get("juicio")
    if juicio:
        coh = juicio.get("coherente")
        st.markdown(
            f"<p style='font-size:0.78rem;color:#5a5d6e;'>juez: "
            f"{'coherente' if coh else 'incoherente' if coh is not None else '—'}"
            + (f" · {_esc(juicio.get('issues'))}" if juicio.get("issues") else "")
            + "</p>",
            unsafe_allow_html=True,
        )

    c1, c2, c3 = st.columns(3)
    with c1:
        st.checkbox(
            "✓ Confirmar correcta",
            value=bool(confirmado.get("_emocion")),
            key=f"emok_{codigo}_{unit_idx}_{eidx}",
            on_change=_on_confirm_emocion, args=(ov, codigo, unit_idx, eidx),
        )
    with c2:
        if st.button("Revertir ediciones", key=f"emrev_{codigo}_{unit_idx}_{eidx}"):
            _revert_emocion(ov, codigo, unit_idx, eidx)
            st.rerun()
    with c3:
        if st.button("Eliminar emoción", key=f"emdel_{codigo}_{unit_idx}_{eidx}"):
            ov.delete_emocion(codigo, unit_idx, eidx)
            st.rerun()


def _on_confirm_emocion(ov: RevisionOverlay, codigo: str, unit_idx: int, eidx: int) -> None:
    ov.confirm_emocion_field(
        codigo, unit_idx, eidx, "_emocion",
        st.session_state[f"emok_{codigo}_{unit_idx}_{eidx}"],
    )


def _revert_emocion(ov: RevisionOverlay, codigo: str, unit_idx: int, eidx: int) -> None:
    node = ov._emo(codigo, unit_idx, eidx)  # noqa: SLF001 - revertir todos los overrides
    node["overrides"] = {}
    ov._save()  # noqa: SLF001


def _edit_scalar(
    ov: RevisionOverlay, codigo: str, unit_idx: int, eidx: int,
    path: list[str], label: str, value: Any,
) -> None:
    leaf = path[-1]
    if leaf.endswith("_justificacion") or leaf == "justificacion":
        if value:
            st.markdown(
                f"<p style='font-size:0.76rem;color:#5a5d6e;margin:0.1rem 0;'>"
                f"<b>{_esc(label)}:</b> {_esc(value)}</p>",
                unsafe_allow_html=True,
            )
        return
    wkey = f"emf_{codigo}_{unit_idx}_{eidx}_{'.'.join(path)}"
    if leaf == "experienciador_canonico":
        cur = _join_canon(value)
        new = st.text_input(f"{label} (varios: separá con ;)", value=cur, key=wkey)
        if new != cur:
            ov.set_emocion_override_path(
                codigo, unit_idx, eidx, path, _parse_canon(new)
            )
            st.rerun()
        return
    opts = _OPTS.get(leaf)
    cur = "" if value is None else str(value)
    if opts:
        options = opts if cur in opts else [cur, *opts] if cur else opts
        new = st.selectbox(label, options, index=options.index(cur) if cur in options else 0,
                           key=wkey)
    else:
        new = st.text_input(label, value=cur, key=wkey)
    if str(new) != cur:
        ov.set_emocion_override_path(codigo, unit_idx, eidx, path, new)
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
