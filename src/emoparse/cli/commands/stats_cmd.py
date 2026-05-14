# ══════════════════════════════════════════════════════════════════════════════
#  emoparse.cli.commands.stats_cmd
#
#  Subcomando `stats`: muestra las estadísticas del cache LLM de una DB.
#
#  Esto es útil después de un run para entender:
#  - Cuántas llamadas LLM hubo en total.
#  - Qué tan efectivo fue el cache (hit rate).
#  - Distribución por modelo (cuál procesó cuántas).
# ══════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

import argparse
from pathlib import Path

from loguru import logger

from emoparse.core.cache.repository import CacheRepository
from emoparse.storage.db import Database


def handle(args: argparse.Namespace) -> int:
    db_path = Path(args.db).expanduser().resolve()
    if not db_path.is_file():
        logger.error(f"DB no encontrada: {db_path}")
        return 1

    db = Database(db_path)
    repo = CacheRepository(db)
    stats = repo.stats()

    print()
    print(f"=== Cache stats: {db_path.name} ===")
    print(f"Entradas totales: {stats['total_entries']}")
    print()

    if not stats["by_model"]:
        print("(cache vacío)")
        return 0

    print("Por modelo:")
    name_w = max(len(m) for m in stats["by_model"]) + 2
    for alias, info in sorted(stats["by_model"].items()):
        entries = info["entries"]
        hits = info["lifetime_hits"]
        # `lifetime_hits` suma el hit_count de todas las filas del modelo.
        # Indica cantidad de reusos totales, no el hit rate.
        if entries > 0:
            avg = hits / entries
            print(f"  {alias:<{name_w}s} {entries:>5d} entradas, "
                  f"{hits:>5d} hits acumulados (avg {avg:.1f} reusos/entrada)")
        else:
            print(f"  {alias:<{name_w}s} (sin entradas)")
    print()

    # Stats de la sesión actual (siempre 0 en CLI, DB abierta solo en modo
    # lectura). Comentado para consistencia futura.
    return 0
