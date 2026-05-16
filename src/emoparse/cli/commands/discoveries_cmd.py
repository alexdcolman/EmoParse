# ══════════════════════════════════════════════════════════════════════════════
#  emoparse.cli.commands.discoveries_cmd
#
#  Subcomando `emoparse discoveries`. Verbos:
#    - list      : lista discoveries pendientes (filtros opcionales).
#    - export    : exporta a CSV.
#    - promote   : registra decisión de promover discovery a canónico nuevo.
#    - merge     : registra decisión de mergear discovery como alias.
#    - discard   : registra decisión de descartar discovery (ruido).
#    - apply     : aplica todas las decisiones pendientes al JSON de la KB,
#                  con backup automático. Idempotente.
# ══════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

import argparse
import csv
from pathlib import Path

from loguru import logger

from emoparse.knowledge.kb_editor import (
    KbEditorError,
    backup_kb,
    discard as kb_discard,
    load_kb,
    merge as kb_merge,
    promote as kb_promote,
)
from emoparse.storage.actors_kb_discoveries import ActorsKbDiscoveriesRepository
from emoparse.storage.db import Database


def handle(args: argparse.Namespace) -> int:
    """Dispatcher según `args.action`."""
    action = args.action
    if action == "list":
        return _handle_list(args)
    if action == "export":
        return _handle_export(args)
    if action == "promote":
        return _handle_promote(args)
    if action == "merge":
        return _handle_merge(args)
    if action == "discard":
        return _handle_discard(args)
    if action == "apply":
        return _handle_apply(args)
    logger.error(f"Acción desconocida: {action}")
    return 1


# ══════════════════════════════════════════════════════════════════════════════
#  list
# ══════════════════════════════════════════════════════════════════════════════

def _handle_list(args: argparse.Namespace) -> int:
    repo, exit_code = _open_repo(args.db)
    if repo is None:
        return exit_code
    pending = repo.list_pending_review(
        codigo=args.codigo,
        confianza=args.confianza,
    )
    if not pending:
        print("Sin discoveries pendientes.")
        return 0

    print(f"=== {len(pending)} discoveries pendientes ===")
    print()
    print(f"{'ID':>5}  {'codigo':<20s}  {'unit':>4s}  {'conf':<6s}  mención")
    print("-" * 80)
    for d in pending:
        # Verificar si tiene decisión registrada para mostrar marca.
        decision = repo.find_decision(d["id"])
        marker = ""
        if decision is not None:
            status = decision["status"]
            if status == "pending":
                marker = f"  [decisión {decision['decision']} pendiente]"
            elif status == "failed":
                marker = f"  [decisión {decision['decision']} FALLÓ]"
        print(
            f"{d['id']:>5}  {d['codigo']:<20s}  {d['unit_idx']:>4d}  "
            f"{d['confianza']:<6s}  {d['actor_mencionado']!r}{marker}"
        )
        contexto = (d.get("contexto") or "").strip()
        if contexto:
            print(f"       contexto: {contexto[:100]}")
    print()
    return 0


# ══════════════════════════════════════════════════════════════════════════════
#  export
# ══════════════════════════════════════════════════════════════════════════════

def _handle_export(args: argparse.Namespace) -> int:
    repo, exit_code = _open_repo(args.db)
    if repo is None:
        return exit_code

    output = Path(args.output).expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)

    pending = repo.list_pending_review(codigo=args.codigo)
    fieldnames = [
        "id", "codigo", "unit_idx", "actor_mencionado",
        "confianza", "contexto", "justificacion", "discovered_at",
        "decision_actual", "decision_status",
    ]
    with output.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for d in pending:
            decision = repo.find_decision(d["id"])
            writer.writerow({
                "id":                d["id"],
                "codigo":            d["codigo"],
                "unit_idx":          d["unit_idx"],
                "actor_mencionado":  d["actor_mencionado"],
                "confianza":         d["confianza"],
                "contexto":          d.get("contexto") or "",
                "justificacion":     d.get("justificacion") or "",
                "discovered_at":     str(d.get("discovered_at") or ""),
                "decision_actual":   decision["decision"] if decision else "",
                "decision_status":   decision["status"] if decision else "",
            })
    print(f"Exportadas {len(pending)} filas → {output}")
    return 0


# ══════════════════════════════════════════════════════════════════════════════
#  promote / merge / discard
# ══════════════════════════════════════════════════════════════════════════════

def _handle_promote(args: argparse.Namespace) -> int:
    repo, exit_code = _open_repo(args.db)
    if repo is None:
        return exit_code
    if repo.find_discovery(args.id) is None:
        logger.error(f"Discovery {args.id} no existe.")
        return 1
    try:
        repo.upsert_decision(
            discovery_id=args.id,
            decision="promote",
            canonical_id=args.canonical_id,
            display_name=args.display_name,
            tipo=args.tipo,
            rol=args.rol,
            origin="cli",
        )
    except ValueError as e:
        logger.error(f"No pude registrar la decisión: {e}")
        return 1
    print(
        f"✓ Decisión registrada: discovery {args.id} → promote "
        f"como '{args.canonical_id}' ('{args.display_name}'). Pendiente de "
        f"aplicar con `emoparse discoveries apply`."
    )
    return 0


def _handle_merge(args: argparse.Namespace) -> int:
    repo, exit_code = _open_repo(args.db)
    if repo is None:
        return exit_code
    if repo.find_discovery(args.id) is None:
        logger.error(f"Discovery {args.id} no existe.")
        return 1
    try:
        repo.upsert_decision(
            discovery_id=args.id,
            decision="merge",
            canonical_id=args.into,
            origin="cli",
        )
    except ValueError as e:
        logger.error(f"No pude registrar la decisión: {e}")
        return 1
    print(
        f"✓ Decisión registrada: discovery {args.id} → merge "
        f"como alias de '{args.into}'. Pendiente de aplicar con "
        f"`emoparse discoveries apply`."
    )
    return 0


def _handle_discard(args: argparse.Namespace) -> int:
    repo, exit_code = _open_repo(args.db)
    if repo is None:
        return exit_code
    if repo.find_discovery(args.id) is None:
        logger.error(f"Discovery {args.id} no existe.")
        return 1
    try:
        repo.upsert_decision(
            discovery_id=args.id,
            decision="discard",
            origin="cli",
        )
    except ValueError as e:
        logger.error(f"No pude registrar la decisión: {e}")
        return 1
    print(
        f"✓ Decisión registrada: discovery {args.id} → discard. "
        f"Pendiente de aplicar con `emoparse discoveries apply`."
    )
    return 0


# ══════════════════════════════════════════════════════════════════════════════
#  apply
# ══════════════════════════════════════════════════════════════════════════════

def _handle_apply(args: argparse.Namespace) -> int:
    repo, exit_code = _open_repo(args.db)
    if repo is None:
        return exit_code

    kb_path = Path(args.kb).expanduser().resolve()
    try:
        load_kb(kb_path)  # Falla pronto si la KB está rota.
    except KbEditorError as e:
        logger.error(f"KB inválida: {e}")
        return 1

    decisions = repo.list_decisions(status="pending")
    if not decisions:
        print("Sin decisiones pendientes.")
        return 0

    if args.dry_run:
        print(f"[DRY-RUN] {len(decisions)} decisiones a aplicar sobre {kb_path}:")
        for d in decisions:
            print(f"  - discovery {d['discovery_id']}: {d['decision']} "
                  f"(actor='{d['actor_mencionado']}', "
                  f"canonical_id={d.get('canonical_id')!r})")
        return 0

    # Backup antes de cualquier mutación.
    bak = backup_kb(kb_path)
    print(f"Backup: {bak}")

    n_ok = 0
    n_failed = 0
    for d in decisions:
        try:
            _apply_one(kb_path, d)
            repo.mark_decision_applied(d["discovery_id"])
            n_ok += 1
        except KbEditorError as e:
            msg = str(e)
            repo.mark_decision_failed(d["discovery_id"], msg)
            logger.error(
                f"Discovery {d['discovery_id']} falló: {msg}"
            )
            n_failed += 1
        except Exception as e:  # noqa: BLE001 — se captura para no abortar lote.
            msg = f"Error inesperado: {e}"
            repo.mark_decision_failed(d["discovery_id"], msg)
            logger.error(
                f"Discovery {d['discovery_id']} falló: {msg}"
            )
            n_failed += 1

    print()
    print(f"=== apply terminado ===")
    print(f"  Aplicadas: {n_ok}")
    print(f"  Falladas:  {n_failed}")
    if n_failed > 0:
        print(
            "Revisar errores con `emoparse discoveries list` y "
            "re-registrar la decisión corregida (sobrescribe la fallida)."
        )
    return 0 if n_failed == 0 else 2


def _apply_one(kb_path: Path, decision: dict) -> None:
    """Aplica una decisión sobre el JSON de la KB."""
    kind = decision["decision"]
    if kind == "promote":
        kb_promote(
            kb_path,
            canonical_id=decision["canonical_id"],
            display_name=decision["display_name"],
            aliases_iniciales=[decision["actor_mencionado"]],
            tipo=decision.get("tipo") or "desconocido",
            rol=decision.get("rol"),
        )
    elif kind == "merge":
        kb_merge(
            kb_path,
            canonical_id=decision["canonical_id"],
            alias_to_add=decision["actor_mencionado"],
        )
    elif kind == "discard":
        kb_discard(kb_path, mencion=decision["actor_mencionado"])
    else:
        raise KbEditorError(f"Decisión desconocida: {kind!r}")


# ══════════════════════════════════════════════════════════════════════════════
#  Helpers
# ══════════════════════════════════════════════════════════════════════════════

def _open_repo(
    db_arg: str,
) -> tuple[ActorsKbDiscoveriesRepository | None, int]:
    """Abre el repo. Devuelve (repo, 0) o (None, exit_code)."""
    db_path = Path(db_arg).expanduser().resolve()
    if not db_path.is_file():
        logger.error(f"DB no encontrada: {db_path}")
        return None, 1
    db = Database(db_path)
    if not db.table_exists("actors_kb_discoveries"):
        logger.error(
            f"La DB no tiene la tabla 'actors_kb_discoveries'. "
            f"Probablemente es anterior a v0.3.0. Correr `emoparse run` "
            f"sobre ella primero (aplica la migración aditiva)."
        )
        return None, 1
    return ActorsKbDiscoveriesRepository(db), 0
