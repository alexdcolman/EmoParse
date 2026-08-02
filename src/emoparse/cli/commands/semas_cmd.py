# ══════════════════════════════════════════════════════════════════════════════
#  emoparse.cli.commands.semas_cmd
#
#  Subcomando `semas`: mantenimiento de los semas de referentes canónicos de
#  una DB existente. Por ahora, un solo modo: --reset, que limpia
#  `canonico_semas` (propuestos y editados a mano) para forzar un reproceso
#  completo del vocabulario vigente en el próximo `emoparse run --stages
#  ...,semas` (mismo run-id/DB).
# ══════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

import argparse
from pathlib import Path

from loguru import logger


def handle(args: argparse.Namespace) -> int:
    """Ejecuta las operaciones de mantenimiento de semas sobre la DB dada."""
    from emoparse.storage.db import Database
    from emoparse.storage.menciones import MencionesRepository

    db_path = Path(args.db)
    if not db_path.exists():
        logger.error(f"[semas] No existe la DB: {db_path}")
        return 2

    if not args.reset:
        logger.error("[semas] Nada que hacer: pasá --reset para limpiar los semas existentes.")
        return 1

    db = Database(db_path)
    repo = MencionesRepository(db)

    n = repo.reset_semas()
    logger.info(
        f"[semas] {n} semas eliminados (incluye editados a mano). "
        "Corré `emoparse run --stages ...,semas` sobre el mismo run para "
        "reasignarlos con el vocabulario vigente."
    )
    return 0


def register(subparsers: argparse._SubParsersAction) -> None:
    """Registra `semas` como subcomando en el CLI principal."""
    p = subparsers.add_parser(
        "semas",
        help="Mantenimiento de los semas de referentes canónicos de una DB.",
        description=(
            "Read-only por default (no ejecuta nada sin flags). Con --reset, "
            "borra todos los semas persistidos en `canonico_semas` (propuestos "
            "y editados a mano), sin distinguir origen. Para reasignarlos con "
            "el vocabulario vigente, correr después "
            "`emoparse run --stages ...,semas` sobre el mismo run."
        ),
    )
    p.add_argument("--db", required=True, help="Path al .sqlite del run.")
    p.add_argument(
        "--reset",
        action="store_true",
        help=("Borra todos los semas existentes (propuestos y humanos). No hay vuelta atrás."),
    )
    p.set_defaults(handler=handle)
