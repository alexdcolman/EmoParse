# ══════════════════════════════════════════════════════════════════════════════
# emoparse.cli.commands.experiencers_cmd
#
# Comando `emoparse experiencers` para gestionar equivalencias de experienciadores.
# ══════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

import argparse
import csv
from pathlib import Path

from loguru import logger

from emoparse.storage.db import Database
from emoparse.storage.emociones import EmocionesRepository
from emoparse.storage.experiencer_equivalences import (
    ExperiencerEquivalencesRepository,
)
from emoparse.storage.runs import RunsRepository


def handle(args: argparse.Namespace) -> int:
    """Dispatcher según `args.action`."""
    action = args.action
    if action == "list":
        return _handle_list(args)
    if action == "export":
        return _handle_export(args)
    if action == "accept":
        return _handle_accept(args)
    if action == "reject":
        return _handle_reject(args)
    if action == "apply":
        return _handle_apply(args)
    logger.error(f"Acción desconocida: {action}")
    return 1


# ══════════════════════════════════════════════════════════════════════════════
#  list
# ══════════════════════════════════════════════════════════════════════════════

def _handle_list(args: argparse.Namespace) -> int:
    repo, _e, exit_code = _open(args.db)
    if repo is None:
        return exit_code
    rows = repo.list_by_status(status=args.status, codigo=args.codigo)
    if not rows:
        print(f"Sin equivalencias en estado '{args.status}'.")
        return 0

    print(f"=== {len(rows)} equivalencias ({args.status}) ===")
    print()
    print(f"{'ID':>5}  {'codigo':<18s}  {'clase':<12s}  {'conf':<5s}  "
          f"{'x':>3s}  crudo → sugerido")
    print("-" * 88)
    for r in rows:
        destino = r["canonical_final"] or r["canonical_sugerido"] or "—"
        print(
            f"{r['id']:>5}  {r['codigo']:<18s}  {r['clase']:<12s}  "
            f"{r['confianza']:<5s}  {r['ocurrencias']:>3d}  "
            f"{r['raw_experienciador']!r} → {destino!r}"
        )
        just = (r.get("justificacion") or "").strip()
        if just:
            print(f"       {just[:100]}")
    print()
    return 0


# ══════════════════════════════════════════════════════════════════════════════
#  export
# ══════════════════════════════════════════════════════════════════════════════

def _handle_export(args: argparse.Namespace) -> int:
    repo, _e, exit_code = _open(args.db)
    if repo is None:
        return exit_code

    output = Path(args.output).expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)

    rows = repo.list_by_status(status=args.status, codigo=args.codigo)
    fieldnames = [
        "id", "codigo", "raw_experienciador", "clase", "canonical_sugerido",
        "canonical_final", "confianza", "ocurrencias", "justificacion",
        "status", "discovered_at",
    ]
    with output.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for r in rows:
            writer.writerow({k: ("" if r.get(k) is None else r.get(k))
                             for k in fieldnames})
    print(f"Exportadas {len(rows)} filas → {output}")
    return 0


# ══════════════════════════════════════════════════════════════════════════════
#  accept / reject
# ══════════════════════════════════════════════════════════════════════════════

def _handle_accept(args: argparse.Namespace) -> int:
    repo, _e, exit_code = _open(args.db)
    if repo is None:
        return exit_code
    try:
        repo.accept(args.id, canonical=args.canonical, origin="cli")
    except ValueError as e:
        logger.error(f"No pude aceptar: {e}")
        return 1
    row = repo.find(args.id)
    destino = row["canonical_final"] if row else args.canonical
    print(
        f"✓ Equivalencia {args.id} aceptada → {destino!r}. Pendiente de "
        f"aplicar con `emoparse experiencers apply`."
    )
    return 0


def _handle_reject(args: argparse.Namespace) -> int:
    repo, _e, exit_code = _open(args.db)
    if repo is None:
        return exit_code
    try:
        repo.reject(args.id, origin="cli")
    except ValueError as e:
        logger.error(f"No pude rechazar: {e}")
        return 1
    print(f"✓ Equivalencia {args.id} rechazada (queda sin canónico).")
    return 0


# ══════════════════════════════════════════════════════════════════════════════
#  apply
# ══════════════════════════════════════════════════════════════════════════════

def _handle_apply(args: argparse.Namespace) -> int:
    repo, emo_repo, exit_code = _open(args.db)
    if repo is None:
        return exit_code

    accepted = repo.list_accepted_unapplied()
    if not accepted:
        print("Sin equivalencias aceptadas pendientes de aplicar.")
        return 0

    if args.dry_run:
        print(f"[DRY-RUN] {len(accepted)} equivalencias a aplicar:")
        for r in accepted:
            print(f"  - {r['codigo']}: {r['raw_experienciador']!r} → "
                  f"{r['canonical_final']!r}")
        return 0

    n_rows = 0
    version = _run_prompt_version(args.db)
    for r in accepted:
        afectadas = emo_repo.set_experienciador_canonico(
            r["codigo"],
            r["raw_experienciador"],
            r["canonical_final"],
            version=version,
        )
        repo.mark_applied(r["id"])
        n_rows += afectadas
        logger.info(
            f"[experiencers] {r['codigo']}: {r['raw_experienciador']!r} → "
            f"{r['canonical_final']!r} ({afectadas} emociones)"
        )

    print()
    print("=== apply terminado ===")
    print(f"  Equivalencias aplicadas: {len(accepted)}")
    print(f"  Emociones actualizadas:  {n_rows}")
    return 0


# ══════════════════════════════════════════════════════════════════════════════
#  Helpers
# ══════════════════════════════════════════════════════════════════════════════

def _run_prompt_version(db_arg: str) -> str | None:
    """Versión de prompt del run, como provenance del canónico aplicado.

    Una DB = un run, así que este valor es estable. None si no hay fila de run.
    """
    db = Database(Path(db_arg).expanduser().resolve())
    try:
        ctx = RunsRepository(db).get_run()
    except Exception:
        return None
    return ctx.versions.prompt if ctx is not None else None


def _open(
    db_arg: str,
) -> tuple[
    ExperiencerEquivalencesRepository | None,
    EmocionesRepository | None,
    int,
]:
    """Abre los repos. Devuelve (equiv_repo, emociones_repo, 0) o (None, None, ec)."""
    db_path = Path(db_arg).expanduser().resolve()
    if not db_path.is_file():
        logger.error(f"DB no encontrada: {db_path}")
        return None, None, 1
    db = Database(db_path)
    if not db.table_exists("experiencer_equivalences"):
        logger.error(
            "La DB no tiene la tabla 'experiencer_equivalences'. Correr "
            "`emoparse run` sobre ella primero (aplica la migración aditiva), "
            "y la stage `normalize_experiencers` para generar propuestas."
        )
        return None, None, 1
    return (
        ExperiencerEquivalencesRepository(db),
        EmocionesRepository(db),
        0,
    )
