# ══════════════════════════════════════════════════════════════════════════════
#  emoparse.cli.commands.status_cmd
#
#  Subcomando `status`: muestra el progreso del pipeline en una DB.
#
#  Output formato tabla:
#    Stage          | Pending | Failed | Completed | n/a | Total
#    ───────────────┼─────────┼────────┼───────────┼─────┼──────
#    summarizer     |       0 |      1 |        99 |   0 |   100
#    metadata       |      12 |      0 |        88 |   0 |   100
#    ...
#
#  El conteo lo resuelve `pipeline.status`, que es la misma fuente que usa
#  la tab Estado del dashboard. Las columnas no se solapan:
#  - Pending:   la unidad entra en el alcance de la stage y falta procesarla.
#  - Failed:    corrió y falló (no se reintenta automático).
#  - Completed: resuelta.
#  - n/a:       fuera del alcance de la stage; no entra en el porcentaje.
#  Una stage que no corrió en este run se marca aparte, sin porcentaje.
#
#  Si alguna corrida acotó el input con un selector, se lista antes de la
#  tabla: una DB corrida parcialmente se lee igual que una completa, y dos
#  runs comparados más adelante pueden estar midiendo universos distintos.
# ══════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

import argparse
from pathlib import Path

from loguru import logger

from emoparse.pipeline.status import StageStatus, collect_from_path
from emoparse.storage.db import Database
from emoparse.storage.discursos import DiscursosRepository
from emoparse.storage.runs import RunsRepository


def handle(args: argparse.Namespace) -> int:
    db_path = Path(args.db).expanduser().resolve()
    if not db_path.is_file():
        logger.error(f"DB no encontrada: {db_path}")
        return 1

    db = Database(db_path)
    runs_repo = RunsRepository(db)
    ctx = runs_repo.get_run()
    if ctx is None:
        logger.error(f"DB {db_path} no contiene un run inicializado.")
        return 1

    print()
    print(f"=== Run {ctx.run_id} ===")
    print(f"DB:         {db_path}")
    print(f"Iniciado:   {ctx.started_at}")
    if ctx.notes:
        print(f"Notas:      {ctx.notes[:80]}")
    print(f"Versions:   knowledge={ctx.versions.knowledge}, "
          f"prompt={ctx.versions.prompt}, "
          f"ontology={ctx.versions.ontology}, "
          f"schema={ctx.versions.schema}")
    print()

    total_discursos = len(DiscursosRepository(db).list_codigos())
    print(f"Discursos: {total_discursos}")
    _print_alcance(runs_repo)
    print()

    _print_stage_table(collect_from_path(db_path))

    return 0


def _print_alcance(runs_repo: RunsRepository) -> None:
    """Lista las corridas que analizaron solo una parte del input."""
    corridas = [c for c in runs_repo.list_alcance() if c.get("seleccion")]
    if not corridas:
        return
    print()
    print("Corridas con alcance acotado:")
    for c in corridas:
        fecha = str(c.get("fecha", ""))[:10]
        print(
            f"  {fecha}  {c.get('n_en_alcance')} de {c.get('n_input')} "
            f"unidades del input  ·  {c.get('seleccion')}"
        )


def _print_stage_table(rows: list[StageStatus]) -> None:
    """Imprime el estado de cada stage como tabla ASCII."""
    headers = ("Stage", "Pending", "Failed", "Completed", "n/a", "Total")
    unidad_w = max((len(r.unidad) for r in rows), default=0)
    name_w = max(len(headers[0]), max((len(r.stage) for r in rows), default=0))
    num_w = 9

    sep = "─" * (name_w + 2) + "┼" + ("─" * num_w + "┼") * 4 + "─" * num_w
    print(f"  {headers[0]:<{name_w}}  │ " + " │ ".join(
        f"{h:>{num_w - 2}}" for h in headers[1:]
    ))
    print(f"  {sep}")
    for r in rows:
        # Una stage que no corrió no tiene pendientes: tiene un universo a
        # su alcance por si se la habilita.
        pending = r.pending if r.ejecutada else 0
        print(f"{_marca(r)} {r.stage:<{name_w}}  │ " + " │ ".join(
            f"{v:>{num_w - 2}}" for v in (
                pending, r.failed, r.completed, r.no_aplica, r.total
            )
        ) + f"  {r.unidad:<{unidad_w}}")
    print()

    sin_correr = [r.stage for r in rows if not r.ejecutada]
    if sin_correr:
        print(f"  No corrieron en este run: {', '.join(sin_correr)}")
        print()


def _marca(r: StageStatus) -> str:
    """Marca visual del estado de una stage."""
    if not r.ejecutada:
        return " "
    if r.failed and not r.completed:
        return "✗"
    if r.failed:
        return "~"
    if r.pending:
        return "·"
    return "✓"


def register(subparsers: argparse._SubParsersAction) -> None:
    """Registra `status` como subcomando en el CLI principal."""
    p = subparsers.add_parser(
        "status",
        help="Muestra el progreso del pipeline en una DB.",
    )
    p.add_argument("--db", required=True, help="Path al .sqlite.")
    p.set_defaults(handler=handle)
