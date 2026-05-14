# ══════════════════════════════════════════════════════════════════════════════
#  emoparse.cli.commands.export_cmd
#
#  Subcomando `emoparse export`.
#
#  Exporta las tablas principales de una corrida desde una DB SQLite
#  hacia archivos CSV en un directorio de salida.
# ══════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

import argparse
from pathlib import Path

from loguru import logger

from emoparse.io.exporters import export_full_run
from emoparse.storage.db import Database


def handle(args: argparse.Namespace) -> int:
    """Ejecuta el subcomando `export`."""
    db_path = Path(args.db)
    if not db_path.is_file():
        logger.error(f"[export] DB no encontrada: {db_path}")
        return 1

    output_dir = Path(args.output_dir)

    try:
        db = Database(db_path)
        counts = export_full_run(db, output_dir)
    except Exception as e:
        logger.error(f"[export] Error inesperado: {e}")
        return 1

    print(f"Export completado → {output_dir.resolve()}")
    print(f"  discursos.csv : {counts['discursos']} filas")
    print(f"  frases.csv    : {counts['frases']} filas")
    print(f"  emociones.csv : {counts['emociones']} filas")

    return 0
