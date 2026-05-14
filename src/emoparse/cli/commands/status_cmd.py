# ══════════════════════════════════════════════════════════════════════════════
#  emoparse.cli.commands.status_cmd
#
#  Subcomando `status`: muestra el progreso del pipeline en una DB.
#
#  Output formato tabla:
#    Stage          | Pending | Failed | Completed | Total
#    ───────────────┼─────────┼────────┼───────────┼──────
#    summarizer     |       0 |      1 |        99 |   100
#    metadata       |      12 |      0 |        88 |   100
#    ...
#
#  Las columnas Pending y Failed son distintas (gracias al fix anterior):
#  - Pending: nunca corrió.
#  - Failed: corrió y falló (no se reintenta automático).
# ══════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

import argparse
from pathlib import Path

from loguru import logger

from emoparse.storage.db import Database
from emoparse.storage.discursos import DiscursosRepository
from emoparse.storage.emociones import EmocionesRepository
from emoparse.storage.frases import FrasesRepository
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

    d_repo = DiscursosRepository(db)
    f_repo = FrasesRepository(db)
    e_repo = EmocionesRepository(db)

    total_discursos = len(d_repo.list_codigos())
    print(f"Discursos: {total_discursos}")
    print()

    rows = _collect_stage_rows(d_repo, f_repo, e_repo, total_discursos)
    _print_stage_table(rows)

    return 0


def _collect_stage_rows(
    d_repo: DiscursosRepository,
    f_repo: FrasesRepository,
    e_repo: EmocionesRepository,
    total_discursos: int,
) -> list[tuple[str, int, int, int, int]]:
    """Genera filas con stats de cada stage (stage, pending, failed, completed, total).

    Discurso: usa total_discursos.  
    Frase: usa total de frases.  
    Caracterización: usa total de emociones.
    """
    rows: list[tuple[str, int, int, int, int]] = []

    for stage in ("summarizer", "metadata", "enunciation"):
        pending = len(d_repo.list_pending(stage))  # type: ignore[arg-type]
        failed = len(d_repo.list_failed(stage))  # type: ignore[arg-type]
        completed = len(d_repo.list_completed(stage))  # type: ignore[arg-type]
        rows.append((stage, pending, failed, completed, total_discursos))

    total_frases = _count_frases(f_repo)
    for stage_name, stage_key in (("actors", "actores"), ("emotions", "emociones")):
        pending = len(f_repo.list_pending(stage_key))  # type: ignore[arg-type]
        # list_failed no disponible para frases; se usa conteo directo.
        failed = _count_frase_failed(f_repo, stage_key)
        completed = total_frases - pending - failed
        rows.append((stage_name, pending, failed, completed, total_frases))

    total_emociones = _count_emociones(e_repo)
    pending_e = len(e_repo.list_pending_caracterizacion())
    failed_e = _count_emociones_failed(e_repo)
    completed_e = total_emociones - pending_e - failed_e
    rows.append(("characterizer", pending_e, failed_e, completed_e, total_emociones))

    return rows


def _count_frases(f_repo: FrasesRepository) -> int:
    """Total de frases en la tabla."""
    row = f_repo._db.execute("SELECT COUNT(*) AS n FROM frases").fetchone()
    return int(row["n"])


def _count_frase_failed(f_repo: FrasesRepository, stage_key: str) -> int:
    """Frases con error registrado en una stage."""
    col = f"{stage_key}_error"
    row = f_repo._db.execute(
        f"SELECT COUNT(*) AS n FROM frases WHERE {col} IS NOT NULL"
    ).fetchone()
    return int(row["n"])


def _count_emociones(e_repo: EmocionesRepository) -> int:
    """Total de emociones en la tabla."""
    row = e_repo._db.execute("SELECT COUNT(*) AS n FROM emociones").fetchone()
    return int(row["n"])


def _count_emociones_failed(e_repo: EmocionesRepository) -> int:
    """Emociones con error registrado en caracterización."""
    row = e_repo._db.execute(
        "SELECT COUNT(*) AS n FROM emociones WHERE caracterizacion_error IS NOT NULL"
    ).fetchone()
    return int(row["n"])


def _print_stage_table(
    rows: list[tuple[str, int, int, int, int]],
) -> None:
    """Imprime las filas como tabla ASCII."""
    headers = ("Stage", "Pending", "Failed", "Completed", "Total")
    name_w = max(len(headers[0]), max(len(r[0]) for r in rows))
    num_w = 9

    sep = "─" * (name_w + 2) + "┼" + ("─" * num_w + "┼") * 3 + "─" * num_w

    print(f"  {headers[0]:<{name_w}}  │ {headers[1]:>{num_w - 2}} │ "
          f"{headers[2]:>{num_w - 2}} │ {headers[3]:>{num_w - 2}} │ "
          f"{headers[4]:>{num_w - 2}}")
    print(f"  {sep}")
    for stage, p, f, c, t in rows:
        # Marca visual del estado.
        if t == 0:
            mark = " "
        elif p > 0:
            mark = "·"  # pendiente
        elif f > 0 and c == 0:
            mark = "✗"  # fallo
        elif f > 0:
            mark = "~"  # parcial
        else:
            mark = "✓"  # ok
        print(f"{mark} {stage:<{name_w}}  │ {p:>{num_w - 2}} │ "
              f"{f:>{num_w - 2}} │ {c:>{num_w - 2}} │ {t:>{num_w - 2}}")
    print()
