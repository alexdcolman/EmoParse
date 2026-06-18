# ══════════════════════════════════════════════════════════════════════════════
#  emoparse.app.actions
#
#  Capa de escritura de la UI Streamlit.
#
#  Este módulo expone funciones puras para registrar decisiones de triage sobre
#  discoveries de actores: promote / merge / discard.
# ══════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

from pathlib import Path

from loguru import logger

from emoparse.knowledge.kb_editor import (
    KbEditorError,
    backup_kb,
    discard as kb_discard,
    edit_actor as kb_edit_actor,
    load_kb,
    merge as kb_merge,
    promote as kb_promote,
)
from emoparse.storage.actors_kb_discoveries import ActorsKbDiscoveriesRepository
from emoparse.storage.db import Database
from emoparse.storage.emociones import EmocionesRepository
from emoparse.storage.experiencer_equivalences import (
    ExperiencerEquivalencesRepository,
)
from emoparse.storage.runs import RunsRepository


def register_promote(
    db_path: Path,
    discovery_id: int,
    *,
    canonical_id: str,
    display_name: str,
    tipo: str = "desconocido",
    rol: str | None = None,
) -> None:
    """Registra desde el dashboard una decisión de promover un discovery.

    La decisión queda pending hasta que se corra `emoparse discoveries apply`.
    """
    repo = _open_repo(db_path)
    repo.upsert_decision(
        discovery_id=discovery_id,
        decision="promote",
        canonical_id=canonical_id,
        display_name=display_name,
        tipo=tipo,
        rol=rol,
        origin="dashboard",
    )
    logger.info(
        f"[app.actions] Registrada promote desde dashboard: "
        f"discovery={discovery_id} → '{canonical_id}'"
    )


def register_merge(
    db_path: Path,
    discovery_id: int,
    *,
    into_canonical_id: str,
) -> None:
    """Registra desde el dashboard una decisión de merge."""
    repo = _open_repo(db_path)
    repo.upsert_decision(
        discovery_id=discovery_id,
        decision="merge",
        canonical_id=into_canonical_id,
        origin="dashboard",
    )
    logger.info(
        f"[app.actions] Registrada merge desde dashboard: "
        f"discovery={discovery_id} → '{into_canonical_id}'"
    )


def register_discard(
    db_path: Path,
    discovery_id: int,
) -> None:
    """Registra desde el dashboard una decisión de descarte."""
    repo = _open_repo(db_path)
    repo.upsert_decision(
        discovery_id=discovery_id,
        decision="discard",
        origin="dashboard",
    )
    logger.info(
        f"[app.actions] Registrada discard desde dashboard: "
        f"discovery={discovery_id}"
    )


def register_merge_many(
    db_path: Path,
    discovery_ids: list[int],
    *,
    into_canonical_id: str,
) -> int:
    """Registra un merge en lote: varias discoveries → un mismo canónico.

    Devuelve la cantidad de decisiones registradas. Abre el repo una sola vez.
    """
    ids = [int(d) for d in dict.fromkeys(discovery_ids)]
    if not ids:
        return 0
    target = (into_canonical_id or "").strip()
    if not target:
        raise ValueError("into_canonical_id vacío.")
    repo = _open_repo(db_path)
    for discovery_id in ids:
        repo.upsert_decision(
            discovery_id=discovery_id,
            decision="merge",
            canonical_id=target,
            origin="dashboard",
        )
    logger.info(
        f"[app.actions] Merge masivo desde dashboard: "
        f"{len(ids)} discoveries → '{target}'"
    )
    return len(ids)


def register_discard_many(
    db_path: Path,
    discovery_ids: list[int],
) -> int:
    """Registra un discard en lote. Devuelve la cantidad de decisiones."""
    ids = [int(d) for d in dict.fromkeys(discovery_ids)]
    if not ids:
        return 0
    repo = _open_repo(db_path)
    for discovery_id in ids:
        repo.upsert_decision(
            discovery_id=discovery_id,
            decision="discard",
            origin="dashboard",
        )
    logger.info(
        f"[app.actions] Discard masivo desde dashboard: {len(ids)} discoveries"
    )
    return len(ids)


def register_group_decisions(
    db_path: Path,
    *,
    canonical_id: str,
    display_name: str,
    tipo: str,
    member_ids: list[int],
    discard_ids: list[int] | None = None,
) -> None:
    """Encola las decisiones de un grupo de discoveries (un promote + N merges).

    El primer miembro se promueve al `canonical_id` del grupo; el resto se
    mergean hacia él. Como las decisiones se aplican por orden de creación,
    el promote queda antes que los merges y el lote se aplica de una sola vez.
    `discard_ids` (los miembros que el analista destildó) se descartan.
    """
    if not member_ids:
        raise ValueError("El grupo no tiene miembros incluidos.")
    first, *rest = member_ids
    register_promote(
        db_path,
        first,
        canonical_id=canonical_id,
        display_name=display_name,
        tipo=tipo,
    )
    for mid in rest:
        register_merge(db_path, mid, into_canonical_id=canonical_id)
    for mid in discard_ids or []:
        register_discard(db_path, mid)
    logger.info(
        f"[app.actions] Grupo encolado: promote '{canonical_id}' "
        f"(+{len(rest)} merges, {len(discard_ids or [])} descartes)."
    )


def undo_decision(db_path: Path, discovery_id: int) -> None:
    """Borra una decisión `pending` previamente registrada."""
    repo = _open_repo(db_path)
    existing = repo.find_decision(discovery_id)
    if existing is None:
        return
    if existing["status"] == "applied":
        raise ValueError(
            f"Decisión sobre discovery {discovery_id} ya aplicada. "
            f"No se puede deshacer desde la UI."
        )
    repo.delete_decision(discovery_id)
    logger.info(
        f"[app.actions] Deshecha decisión: discovery={discovery_id}"
    )


def _open_repo(db_path: Path) -> ActorsKbDiscoveriesRepository:
    """Abre el repo en modo read-write."""
    if not db_path.is_file():
        raise FileNotFoundError(f"DB no encontrada: {db_path}")
    db = Database(db_path)
    if not db.table_exists("actors_kb_discoveries"):
        raise RuntimeError(
            f"DB sin tabla actors_kb_discoveries."
        )
    return ActorsKbDiscoveriesRepository(db)


# ══════════════════════════════════════════════════════════════════════════════
#  Equivalencias de experienciador
# ══════════════════════════════════════════════════════════════════════════════

def register_experiencer_accept(
    db_path: Path,
    equivalence_id: int,
    *,
    canonical: str | None = None,
) -> None:
    """Acepta desde el dashboard una equivalencia de experienciador.

    Queda accepted hasta correr `emoparse experiencers apply`. Si `canonical`
    es None se usa el sugerido (o el crudo si la clase es 'literal').
    """
    repo = _open_equiv_repo(db_path)
    repo.accept(equivalence_id, canonical=canonical, origin="dashboard")
    logger.info(
        f"[app.actions] Aceptada equivalencia desde dashboard: "
        f"id={equivalence_id} canonical={canonical!r}"
    )


def register_experiencer_reject(db_path: Path, equivalence_id: int) -> None:
    """Rechaza desde el dashboard una equivalencia de experienciador."""
    repo = _open_equiv_repo(db_path)
    repo.reject(equivalence_id, origin="dashboard")
    logger.info(
        f"[app.actions] Rechazada equivalencia desde dashboard: "
        f"id={equivalence_id}"
    )


def undo_experiencer_decision(db_path: Path, equivalence_id: int) -> None:
    """Vuelve a pending una equivalencia decidida (no aplicada)."""
    repo = _open_equiv_repo(db_path)
    repo.reset_to_pending(equivalence_id)
    logger.info(
        f"[app.actions] Equivalencia vuelta a pending: id={equivalence_id}"
    )


def _open_equiv_repo(db_path: Path) -> ExperiencerEquivalencesRepository:
    """Abre el repo de equivalencias de experienciador en modo read-write."""
    if not db_path.is_file():
        raise FileNotFoundError(f"DB no encontrada: {db_path}")
    db = Database(db_path)
    if not db.table_exists("experiencer_equivalences"):
        raise RuntimeError("DB sin tabla experiencer_equivalences.")
    return ExperiencerEquivalencesRepository(db)


# ══════════════════════════════════════════════════════════════════════════════
#  Aplicación (apply) desde el dashboard
# ══════════════════════════════════════════════════════════════════════════════

def pending_promote_canonical_ids(db_path: Path) -> list[str]:
    """canonical_ids de los promotes pendientes (aún no aplicados a la KB).

    Permite ofrecerlos como destino de un merge antes de aplicar, de modo que
    se pueda encolar `promote A` + `merge B→A` y aplicarlos en un solo lote.
    """
    repo = _open_repo(db_path)
    out = {
        d["canonical_id"]
        for d in repo.list_decisions(status="pending")
        if d["decision"] == "promote" and d.get("canonical_id")
    }
    return sorted(out)


def apply_actor_decisions(db_path: Path, kb_path: Path) -> dict:
    """Aplica las decisiones de actores pendientes al JSON de la KB.

    Hace un backup antes de mutar y procesa el lote por orden de creación
    (así un `merge` hacia un `promote` del mismo lote encuentra su destino).
    Devuelve {applied, failed, backup, errors}. Idempotente.
    """
    repo = _open_repo(db_path)
    try:
        load_kb(kb_path)
    except KbEditorError as e:
        raise RuntimeError(f"KB inválida: {e}") from e

    decisions = repo.list_decisions(status="pending")
    if not decisions:
        return {"applied": 0, "failed": 0, "backup": None, "errors": []}

    backup = backup_kb(kb_path)
    applied = failed = 0
    errors: list[tuple[int, str]] = []
    for d in decisions:
        try:
            _apply_actor_one(kb_path, d)
            repo.mark_decision_applied(d["discovery_id"])
            applied += 1
        except Exception as e:  # noqa: BLE001 — no abortar el lote.
            repo.mark_decision_failed(d["discovery_id"], str(e))
            failed += 1
            errors.append((d["discovery_id"], str(e)))
    logger.info(
        f"[app.actions] apply actores: {applied} ok, {failed} fallidas "
        f"(backup {backup})"
    )
    return {
        "applied": applied,
        "failed": failed,
        "backup": str(backup),
        "errors": errors,
    }


def _apply_actor_one(kb_path: Path, d: dict) -> None:
    kind = d["decision"]
    if kind == "promote":
        kb_promote(
            kb_path,
            canonical_id=d["canonical_id"],
            display_name=d["display_name"],
            aliases_iniciales=[d["actor_mencionado"]],
            tipo=d.get("tipo") or "desconocido",
            rol=d.get("rol"),
        )
    elif kind == "merge":
        kb_merge(
            kb_path,
            canonical_id=d["canonical_id"],
            alias_to_add=d["actor_mencionado"],
        )
    elif kind == "discard":
        kb_discard(kb_path, mencion=d["actor_mencionado"])
    else:
        raise KbEditorError(f"Decisión desconocida: {kind!r}")


def apply_experiencer_decisions(db_path: Path) -> dict:
    """Aplica las equivalencias de experienciador aceptadas a `emociones`.

    Escribe `experienciador_canonico` (estampando la versión de prompt del run
    como provenance) y marca las equivalencias como aplicadas. Idempotente.
    Devuelve {equivalences, rows}.
    """
    if not db_path.is_file():
        raise FileNotFoundError(f"DB no encontrada: {db_path}")
    db = Database(db_path)
    if not db.table_exists("experiencer_equivalences"):
        raise RuntimeError("DB sin tabla experiencer_equivalences.")
    eq = ExperiencerEquivalencesRepository(db)
    emo = EmocionesRepository(db)

    accepted = eq.list_accepted_unapplied()
    version = _run_prompt_version(db)
    rows = 0
    for r in accepted:
        rows += emo.set_experienciador_canonico(
            r["codigo"], r["raw_experienciador"], r["canonical_final"],
            version=version,
        )
        eq.mark_applied(r["id"])
    logger.info(
        f"[app.actions] apply experienciadores: {len(accepted)} equivalencias, "
        f"{rows} emociones."
    )
    return {"equivalences": len(accepted), "rows": rows}


def _run_prompt_version(db: Database) -> str | None:
    """Versión de prompt del run (provenance del canónico)."""
    try:
        ctx = RunsRepository(db).get_run()
    except Exception:
        return None
    return ctx.versions.prompt if ctx is not None else None


# ══════════════════════════════════════════════════════════════════════════════
#  Edición directa de la KB de actores (revisión manual desde el dashboard)
# ══════════════════════════════════════════════════════════════════════════════

def kb_save_actor(
    kb_path: Path,
    canonical_id: str,
    *,
    display_name: str | None = None,
    tipo: str | None = None,
    rol: str | None = None,
    notas: str | None = None,
    aliases: list[str] | None = None,
) -> Path:
    """Guarda ediciones de un actor existente (NO cambia el canonical_id).

    Hace backup antes de escribir y delega en el editor seguro (atómico).
    Devuelve el path del backup creado.
    """
    if not kb_path.is_file():
        raise FileNotFoundError(f"KB no encontrada: {kb_path}")
    backup = backup_kb(kb_path)
    kb_edit_actor(
        kb_path,
        canonical_id=canonical_id,
        display_name=display_name,
        tipo=tipo,
        rol=rol,
        notas=notas,
        aliases=aliases,
    )
    logger.info(
        f"[app.actions] KB editada desde dashboard: '{canonical_id}' "
        f"(backup {backup})"
    )
    return backup


def kb_create_actor(
    kb_path: Path,
    *,
    canonical_id: str,
    display_name: str,
    tipo: str = "desconocido",
    rol: str | None = None,
    aliases: list[str] | None = None,
) -> Path:
    """Crea un actor nuevo en la KB (vía editor seguro). Devuelve el backup."""
    if not kb_path.is_file():
        raise FileNotFoundError(f"KB no encontrada: {kb_path}")
    backup = backup_kb(kb_path)
    kb_promote(
        kb_path,
        canonical_id=canonical_id,
        display_name=display_name,
        aliases_iniciales=aliases or [],
        tipo=tipo,
        rol=rol,
    )
    logger.info(
        f"[app.actions] KB alta desde dashboard: '{canonical_id}' "
        f"(backup {backup})"
    )
    return backup
