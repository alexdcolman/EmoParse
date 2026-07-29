# ══════════════════════════════════════════════════════════════════════════════
#  emoparse.app.components.tab_deixis
#
#  Revisión de sugerencias deícticas: por cada marca deíctica ("nosotros",
#  "tenemos", "veamos"…) el stage `deixis` propone uno o varios referentes
#  concretos (enunciador, auditorio, colectivo de identificación). Aceptar
#  inscribe la marca en ese referente; rechazar la descarta. Como la marca es
#  de toda la unidad, aplicarla a un simulacro es una decisión por emoción: se
#  elige reemplazar el referente que rige ese rol o sumar el nuevo. Se revisa
#  de a 10.
# ══════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

import html
from pathlib import Path

import streamlit as st

from emoparse.app import actions as actions_layer
from emoparse.app import data as data_layer

_PAGE = 10

#: Roles actanciales con simulacro: los que la tarjeta ofrece aplicar.
_ROL_LABEL = {"experienciador": "exp", "fuente": "fte"}

#: Color por rol, consistente con la tab Simulacros.
_ROL_COLOR = {"experienciador": "#7c9ec8", "fuente": "#6ec89a"}

_TIPO_LABEL = {
    "enunciador": "enunciador",
    "auditorio": "auditorio",
    "colectivo_identificacion": "colectivo de identificación",
    "otro": "otro",
}

#: Modos de existencia del simulacro, tomados del esquema como fuente de verdad.
try:
    from typing import get_args

    from emoparse.core import schemas as _sc

    _MODOS: list[str] = list(get_args(_sc.ModoExistenciaEmocion))
except Exception:  # pragma: no cover — fallback defensivo
    _MODOS = [
        "realizada", "potencial", "actual", "virtual", "inducida_proyectada",
    ]

#: Opción neutra del selector de modo: el simulacro conserva el suyo.
_SIN_CAMBIO = "(sin cambio)"

#: Modo propuesto al atribuir una emoción a un tipo de referente. Una emoción
#: atribuida al auditorio es potencial salvo que el texto simule que ya la
#: siente (regla de las heurísticas de emociones); el resto conserva el suyo,
#: y en todos los casos se puede fijar a mano.
_MODO_SUGERIDO = {"auditorio": "potencial"}
#: Estado de un referente frente a los simulacros de su unidad. Lo que importa
#: no es el estado del vínculo sino si ya rige algún simulacro: inscribir la
#: marca en un referente no decide nada por sí solo.
_SIN_APLICAR = ("sin aplicar", "#c8a96e")
_DESCARTADO = ("descartado", "#c86e6e")
_APLICADO_COLOR = "#6ec89a"


def _pretty(canonical_id: str) -> str:
    return str(canonical_id or "").replace("_", " ").strip().capitalize()


def render(db_path: Path) -> None:
    """Renderiza la tab de revisión de deixis."""
    st.markdown("### Deixis")

    fcol1, fcol2 = st.columns([1, 2])
    with fcol1:
        only_pending = st.toggle(
            "Solo pendientes", value=True, key="deixis_only_pending",
            help="Oculta las marcas cuyos referentes ya fueron aplicados a un "
                 "simulacro o descartados.",
        )
        include_unlinked = st.toggle(
            "Incluir marcas sin sugerencia", value=False,
            key="deixis_include_unlinked",
            help="Muestra también marcas deícticas (yo/nosotros/ustedes…) que el "
                 "LLM no asignó, para asignarles un referente a mano.",
        )
    with fcol2:
        func_inc = st.multiselect(
            "Función incluye",
            ["actor", "experienciador", "fuente"],
            key="deixis_func_inc",
            placeholder="cualquiera",
        )
        func_exc = st.multiselect(
            "Función NO incluye (excluir)",
            ["actor", "experienciador", "fuente"],
            key="deixis_func_exc",
            placeholder="ninguna",
        )
    sugerencias = data_layer.get_deixis_suggestions(
        db_path, only_pending=only_pending, include_unlinked=include_unlinked
    )
    if func_inc:
        inc = set(func_inc)
        sugerencias = [s for s in sugerencias if inc & set(s["funciones"])]
    if func_exc:
        exc = set(func_exc)
        sugerencias = [s for s in sugerencias if not (exc & set(s["funciones"]))]

    if not sugerencias:
        st.info(
            "No hay sugerencias deícticas pendientes. Corré el stage `deixis` "
            "(necesita `enunciation` con auditorio/colectivos)."
        )
        return

    st.markdown(
        f"<p style='color:#8a8799;font-size:0.9rem;'>Se encontraron "
        f"<b>{len(sugerencias)}</b> marcas deícticas "
        f"<span style='color:#5a5d6e;'>(un referente empieza a regir cuando "
        f"lo aplicás a un simulacro: reemplazando el que estaba o sumándose a "
        f"él).</span></p>",
        unsafe_allow_html=True,
    )

    n_pages = (len(sugerencias) - 1) // _PAGE + 1
    page = st.session_state.get("deixis_page", 0)
    page = max(0, min(page, n_pages - 1))
    p1, p2, p3 = st.columns([1, 6, 1])
    with p1:
        if st.button("◀", key="deixis_prev", disabled=page == 0,
                     use_container_width=True):
            st.session_state["deixis_page"] = page - 1
            st.rerun()
    with p3:
        if st.button("▶", key="deixis_next", disabled=page >= n_pages - 1,
                     use_container_width=True):
            st.session_state["deixis_page"] = page + 1
            st.rerun()
    with p2:
        st.markdown(
            f"<p style='text-align:center;color:#5a5d6e;font-size:0.8rem;'>"
            f"página {page + 1} de {n_pages}</p>",
            unsafe_allow_html=True,
        )

    pagina = sugerencias[page * _PAGE:(page + 1) * _PAGE]
    ref_map = data_layer.get_deixis_referentes_map(
        db_path, codigos=sorted({s["codigo"] for s in pagina})
    )
    canonicos = data_layer.list_canonicos(db_path)
    emo_brief = data_layer.get_frase_emociones_brief(db_path)
    for sug in pagina:
        _render_sugerencia(
            db_path, sug, ref_map.get(sug["codigo"], []), canonicos, emo_brief
        )


def _render_sugerencia(
    db_path: Path, sug: dict, referentes_discurso: list[dict],
    canonicos: list[str],
    emo_brief: dict[tuple[str, int], list[dict[str, str]]] | None = None,
) -> None:
    funcs = "/".join(sug["funciones"]) or "—"
    with st.container(border=True):
        st.markdown(
            f"<span style='font-size:1rem;color:#e8e4dc;'><b>"
            f"{html.escape(str(sug['marca']))}</b></span> "
            f"<span style='font-size:0.72rem;color:#b08ad0;'>{html.escape(funcs)}</span> "
            f"<span style='font-family:DM Mono,monospace;font-size:0.7rem;"
            f"color:#5a5d6e;'> · {html.escape(str(sug['codigo']))}·u{sug['unit_idx']}"
            f"</span>",
            unsafe_allow_html=True,
        )
        if str(sug["frase"]).strip():
            st.markdown(
                f"<div style='margin:0.3rem 0 0.5rem;padding:0.45rem 0.7rem;"
                f"background:#15171c;border-radius:6px;font-size:0.84rem;"
                f"line-height:1.55;color:#c2bdb4;'>"
                f"{html.escape(str(sug['frase']))}</div>",
                unsafe_allow_html=True,
            )

        solo_actor = not (set(sug["funciones"]) & set(_ROL_LABEL))
        for ref in sug["referentes"]:
            _render_referente(db_path, sug["mencion_id"], ref, solo_actor)

        _render_agregar(db_path, sug, referentes_discurso)
        _render_agregar_canonico(db_path, sug, canonicos)
        _render_simulacros(db_path, sug, emo_brief)


def _roles_en_emocion(sug: dict, brief: dict) -> list[str]:
    """Roles que ocupa la marca de la sugerencia en esa emoción.

    Una misma marca puede ser experienciador en un simulacro y fuente en otro,
    así que la comparación es contra la marca de cada rol, no contra las
    funciones de la mención.
    """
    marca = str(sug["marca"]).strip().lower()
    funciones = set(sug["funciones"])
    return [
        rol for rol in _ROL_LABEL
        if rol in funciones
        and str(brief.get(f"{rol}_marca") or "").strip().lower() == marca
    ]


def _render_simulacros(
    db_path: Path, sug: dict,
    emo_brief: dict[tuple[str, int], list[dict[str, str]]] | None,
) -> None:
    """Simulacros de la unidad, con la acción por emoción y por rol.

    Solo para marcas de experienciador o de fuente: una marca de actor no
    interviene en ningún simulacro, y su relación con el referente se agota en
    el vínculo mención↔canónico.
    """
    if not (set(sug["funciones"]) & set(_ROL_LABEL)):
        return
    briefs = (emo_brief or {}).get((str(sug["codigo"]), int(sug["unit_idx"]))) or []
    aplicables = [(b, _roles_en_emocion(sug, b)) for b in briefs]
    aplicables = [(b, roles) for b, roles in aplicables if roles]
    if not aplicables:
        return

    vigentes = [r for r in sug["referentes"] if r["status"] != "rejected"]
    if not vigentes:
        return
    elegibles = [r["canonical_id"] for r in vigentes]
    tipo_de = {r["canonical_id"]: r["deixis_tipo"] for r in vigentes}
    mid = sug["mencion_id"]
    # Se listan solo los simulacros donde esta marca interviene, y los índices
    # son los de la frase entera: por eso pueden verse salteados.
    resto = len(briefs) - len(aplicables)
    detalle = (
        f" <span style='color:#5a5d6e;'>· {len(aplicables)} de {len(briefs)} "
        f"de la unidad; el resto no usa esta marca</span>" if resto else ""
    )
    st.markdown(
        f"<div style='color:#8a8799;font-size:0.78rem;margin:0.55rem 0 0.2rem;'>"
        f"Simulacros donde interviene «{html.escape(str(sug['marca']))}»"
        f"{detalle}</div>",
        unsafe_allow_html=True,
    )
    destino = (
        elegibles[0] if len(elegibles) == 1
        else st.selectbox(
            "referente a aplicar", elegibles, key=f"dxap_ref_{mid}",
            format_func=_pretty, label_visibility="collapsed",
        )
    )
    sugerido = _MODO_SUGERIDO.get(tipo_de.get(destino, ""), "")
    opciones = [_SIN_CAMBIO, *_MODOS]
    mcol, _ = st.columns([2, 3])
    with mcol:
        elegido = st.selectbox(
            "modo de existencia del simulacro que lo recibe",
            opciones,
            index=opciones.index(sugerido) if sugerido in opciones else 0,
            key=f"dxap_modo_{mid}_{destino}",
            help="Con «sin cambio» el simulacro conserva su modo. Una emoción "
                 "atribuida al auditorio se propone como potencial; cambialo "
                 "si el texto simula que ya la siente.",
        )
    modo_dest = "" if elegido == _SIN_CAMBIO else elegido
    for brief, roles in aplicables:
        _render_simulacro(db_path, sug, brief, roles, destino, modo_dest)


def _render_simulacro(
    db_path: Path, sug: dict, brief: dict, roles: list[str], destino: str,
    modo_dest: str = "",
) -> None:
    """Una emoción de la unidad, con sus dos acciones en el rol que toca."""
    mid = sug["mencion_id"]
    eidx = int(brief["emocion_idx"])
    c_enc, c_del = st.columns([6, 1])
    with c_enc:
        st.markdown(
            f"<div style='margin-top:0.4rem;font-size:0.8rem;color:#c2bdb4;'>"
            f"<span style='font-family:DM Mono,monospace;color:#5a5d6e;'>"
            f"#{eidx}</span> <b style='color:#b08ad0;'>"
            f"{html.escape(str(brief['emocion']))}</b> "
            f"<span style='color:#5a5d6e;'>"
            f"({html.escape(str(brief['modo']))})</span></div>",
            unsafe_allow_html=True,
        )
    with c_del:
        if st.button("🗑 eliminar", key=f"dxdel_{mid}_{eidx}",
                     use_container_width=True,
                     help="Elimina este simulacro de la base. No se deshace."):
            actions_layer.emocion_delete(
                db_path, str(sug["codigo"]), int(sug["unit_idx"]), eidx
            )
            st.toast(f"Emoción #{eidx} eliminada.", icon="🗑")
            st.rerun()
    for rol in _ROL_LABEL:
        actual = str(brief["experienciador" if rol == "experienciador" else "fuente"])
        marcado = rol in roles
        c_lbl, c_rep, c_add = st.columns([5, 1, 1])
        with c_lbl:
            flecha = (
                f" <span style='color:#5a5d6e;'>← marca «"
                f"{html.escape(str(sug['marca']))}»</span>" if marcado else ""
            )
            st.markdown(
                f"<div style='padding-top:0.3rem;font-size:0.78rem;'>"
                f"<span style='color:{_ROL_COLOR[rol]};'>{_ROL_LABEL[rol]}</span> "
                f"<span style='color:#e8e4dc;'>{html.escape(actual)}</span>"
                f"{flecha}</div>",
                unsafe_allow_html=True,
            )
        if not marcado:
            continue
        duplica = rol == "experienciador" and destino not in actual.split("; ")
        with c_rep:
            if st.button(
                "reemplazar", key=f"dxrep_{mid}_{eidx}_{rol}",
                use_container_width=True,
                help=f"«{_pretty(destino)}» pasa a ser el único referente de "
                     f"este rol en esta emoción.",
            ):
                _aplicar(db_path, sug, eidx, rol, destino, "reemplazar", modo_dest)
        with c_add:
            if st.button(
                "añadir", key=f"dxadd2_{mid}_{eidx}_{rol}",
                use_container_width=True,
                help=(
                    "El experienciador es uno solo: la emoción se duplica, una "
                    "por referente." if rol == "experienciador"
                    else "La fuente admite combinación: el referente se suma "
                         "sin duplicar la emoción."
                ),
                disabled=rol == "experienciador" and not duplica,
            ):
                _aplicar(db_path, sug, eidx, rol, destino, "anadir", modo_dest)


def _aplicar(
    db_path: Path, sug: dict, emocion_idx: int, rol: str, destino: str,
    modo: str, modo_dest: str = "",
) -> None:
    """Ejecuta la acción por emoción y avisa qué pasó."""
    res = actions_layer.deixis_aplicar_a_emocion(
        db_path, str(sug["codigo"]), int(sug["unit_idx"]), emocion_idx,
        rol, destino, modo, mencion_id=sug["mencion_id"],
        modo_existencia=modo_dest if rol == "experienciador" else None,
    )
    if res["duplicada"]:
        detalle = f"emoción #{emocion_idx} duplicada ({len(res['nuevos'])} nueva)"
    elif modo == "anadir":
        detalle = f"sumado a la fuente de #{emocion_idx}"
    else:
        detalle = f"{rol} de #{emocion_idx} reemplazado"
    st.toast(f"«{_pretty(destino)}»: {detalle}.", icon="✅")
    st.rerun()


def _render_agregar(db_path: Path, sug: dict, referentes_discurso: list[dict]) -> None:
    """Permite sumar a la marca otro referente deíctico del discurso."""
    ya = {r["canonical_id"] for r in sug["referentes"]}
    opciones = [r for r in referentes_discurso if r["canonical_id"] not in ya]
    if not opciones:
        return
    mid = sug["mencion_id"]
    labels = {
        f"{r['nombre']} ({_TIPO_LABEL.get(r['tipo'], r['tipo'])})": r
        for r in opciones
    }
    ac1, ac2 = st.columns([5, 1])
    sel = ac1.selectbox(
        "agregar otro referente",
        ["— agregar otro —", *labels.keys()],
        key=f"dxadd_sel_{mid}",
        label_visibility="collapsed",
    )
    with ac2:
        st.markdown("<div style='height:0.35rem;'></div>", unsafe_allow_html=True)
        if st.button("＋ agregar", key=f"dxadd_btn_{mid}",
                     use_container_width=True,
                     disabled=sel == "— agregar otro —"):
            r = labels[sel]
            actions_layer.deixis_add(db_path, mid, r["canonical_id"], r["tipo"])
            st.toast(f"«{r['nombre']}» agregado.", icon="✅")
            st.rerun()


def _render_agregar_canonico(db_path: Path, sug: dict, canonicos: list[str]) -> None:
    """Asigna a la marca un referente canónico existente (de tab Referentes) o nuevo."""
    mid = sug["mencion_id"]
    ya = {r["canonical_id"] for r in sug["referentes"]}
    opciones = [c for c in canonicos if c not in ya]
    tipos = list(_TIPO_LABEL)
    with st.expander("Asignar canónico existente o nuevo", expanded=False):
        existente = st.selectbox(
            "Canónico existente",
            ["— ninguno —", *opciones],
            key=f"dxc_sel_{mid}",
        )
        nuevo = st.text_input(
            "… o nuevo referente",
            key=f"dxc_new_{mid}",
            placeholder="nombre del referente nuevo",
        )
        tcol, bcol = st.columns([3, 1])
        tipo = tcol.selectbox(
            "Tipo",
            tipos,
            format_func=lambda t: _TIPO_LABEL.get(t, t),
            key=f"dxc_tipo_{mid}",
        )
        with bcol:
            st.markdown("<div style='height:1.8rem;'></div>", unsafe_allow_html=True)
            if st.button("＋ agregar", key=f"dxc_btn_{mid}",
                         use_container_width=True):
                canonical = nuevo.strip() or (
                    existente if existente != "— ninguno —" else ""
                )
                if not canonical:
                    st.warning("Elegí un canónico existente o escribí uno nuevo.")
                else:
                    actions_layer.deixis_add(db_path, mid, canonical, tipo)
                    st.toast(f"«{canonical}» agregado.", icon="✅")
                    st.rerun()


def _render_referente(
    db_path: Path, mencion_id: int, ref: dict, solo_actor: bool
) -> None:
    """Un referente de la marca, con su estado frente a los simulacros.

    En una marca de actor el vínculo agota la relación, así que se inscribe
    desde acá. En una marca con simulacro, en cambio, inscribirla no decide
    nada: lo que la hace regir es aplicarla a una emoción.
    """
    cid = ref["canonical_id"]
    tipo = _TIPO_LABEL.get(ref["deixis_tipo"], ref["deixis_tipo"] or "—")
    descartado = ref["status"] == "rejected"
    aplicado = ref.get("aplicado_en") or []
    if descartado:
        badge_txt, badge_col = _DESCARTADO
    elif aplicado:
        badge_txt, badge_col = f"rige {', '.join(aplicado)}", _APLICADO_COLOR
    elif solo_actor:
        badge_txt, badge_col = (
            ("inscripto", _APLICADO_COLOR) if ref["status"] == "accepted"
            else _SIN_APLICAR
        )
    else:
        badge_txt, badge_col = _SIN_APLICAR

    c_lbl, c_ok, c_no = st.columns([5, 1, 1])
    with c_lbl:
        st.markdown(
            f"<div style='padding-top:0.35rem;'>"
            f"<b style='color:#e8e4dc;'>{html.escape(_pretty(cid))}</b> "
            f"<span style='color:#7c9ec8;font-size:0.78rem;'>({html.escape(tipo)})</span>"
            f"<span style='color:{badge_col};font-size:0.7rem;'> · {badge_txt}</span>"
            f"<br><span style='font-family:DM Mono,monospace;font-size:0.68rem;"
            f"color:#5a5d6e;'>{html.escape(cid)}</span></div>",
            unsafe_allow_html=True,
        )
    with c_ok:
        if solo_actor and not descartado:
            if st.button("✓ inscribir", key=f"dxok_{mencion_id}_{cid}",
                         disabled=ref["status"] == "accepted",
                         use_container_width=True,
                         help="Inscribe la marca en el referente."):
                actions_layer.deixis_accept(db_path, mencion_id, cid)
                st.toast(f"«{_pretty(cid)}» inscripto.", icon="✅")
                st.rerun()
        elif descartado:
            if st.button("↺ restaurar", key=f"dxres_{mencion_id}_{cid}",
                         use_container_width=True):
                actions_layer.deixis_restore(db_path, mencion_id, cid)
                st.toast(f"«{_pretty(cid)}» restaurado.", icon="↩")
                st.rerun()
    with c_no:
        if st.button("✗ descartar", key=f"dxno_{mencion_id}_{cid}",
                     disabled=descartado, use_container_width=True,
                     help="Lo quita de los simulacros donde rija y evita que "
                          "vuelva a proponerse para esta marca."):
            limpiadas = actions_layer.deixis_reject(db_path, mencion_id, cid)
            extra = (
                f" Quitado de {limpiadas} simulacro(s)." if limpiadas else ""
            )
            st.toast(f"«{_pretty(cid)}» descartado.{extra}", icon="🗑")
            st.rerun()
