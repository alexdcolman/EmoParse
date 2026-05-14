# ══════════════════════════════════════════════════════════════════════════════
#  emoparse.cli.commands.judge_cmd
#
#  Subcomando `judge`: resume los juicios persistidos en `judgments`.
#
#  Lee una DB existente e imprime el estado de coherencia registrado
#  por JudgeStage. No ejecuta validaciones ni modifica datos; solo
#  inspecciona resultados previamente persistidos.
# ══════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

import argparse
from pathlib import Path

from loguru import logger

from emoparse.storage.db import Database
from emoparse.storage.judgments import JudgmentsRepository


def handle(args: argparse.Namespace) -> int:
    """Handler del subcomando `judge`."""
    db_path = Path(args.db).expanduser().resolve()
    if not db_path.is_file():
        logger.error(f"DB no encontrada: {db_path}")
        return 1

    db = Database(db_path)
    repo = JudgmentsRepository(db)
    codigo = getattr(args, "codigo", None)

    counts = repo.count_by_coherence(codigo=codigo)

    print()
    scope = f"discurso {codigo}" if codigo else "todos los discursos"
    print(f"=== Judge results: {db_path.name} ({scope}) ===")
    print()
    print(f"Total juzgadas:    {counts['total']}")
    print(f"  Coherentes:      {counts['coherent']}")
    print(f"  Incoherentes:    {counts['incoherent']}")
    print(f"  Errores:         {counts['errors']}")
    print()

    if counts["incoherent"] == 0 and not getattr(args, "verbose", False):
        return 0

    judgments = (
        repo.list_for_discurso(codigo) if codigo
        else _list_all(db)
    )
    incoherent = [j for j in judgments if j.get("coherente") is False]

    if incoherent:
        print("INCOHERENCIAS DETECTADAS:")
        print("-" * 60)
        for j in incoherent:
            print(
                f"  [{j['codigo']} f{j['frase_idx']} e{j['emocion_idx']}] "
                f"confianza={j['confianza']}"
            )
            print(f"    {j['issues']}")
        print()

    if getattr(args, "verbose", False):
        coherent_rows = [j for j in judgments if j.get("coherente") is True]
        if coherent_rows:
            print(f"COHERENTES ({len(coherent_rows)}):")
            for j in coherent_rows:
                print(
                    f"  [{j['codigo']} f{j['frase_idx']} e{j['emocion_idx']}] "
                    f"confianza={j['confianza']}"
                )
            print()

    return 0


def _list_all(db: Database) -> list[dict]:
    """Lista todos los juicios persistidos cuando no se filtra por `codigo`."""
    rows = db.execute(
        """
        SELECT codigo, frase_idx, emocion_idx,
               coherente, issues, confianza,
               judge_version, judge_error
        FROM judgments
        ORDER BY codigo, frase_idx, emocion_idx
        """,
    ).fetchall()
    out: list[dict] = []
    for row in rows:
        d = dict(row)
        if d["coherente"] is not None:
            d["coherente"] = bool(d["coherente"])
        out.append(d)
    return out
