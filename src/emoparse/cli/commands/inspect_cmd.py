# ══════════════════════════════════════════════════════════════════════════════
#  emoparse.cli.commands.inspect_cmd
#
#  Subcomando `inspect`.
#
#  Imprime el estado completo de un discurso almacenado en la DB,
#  incluyendo input original, stages a nivel discurso, frases y
#  emociones detectadas.
# ══════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

import argparse
import json
from pathlib import Path

from loguru import logger

from emoparse.storage.db import Database
from emoparse.storage.discursos import DiscursosRepository
from emoparse.storage.emociones import EmocionesRepository
from emoparse.storage.frases import FrasesRepository


def handle(args: argparse.Namespace) -> int:
    db_path = Path(args.db).expanduser().resolve()
    if not db_path.is_file():
        logger.error(f"DB no encontrada: {db_path}")
        return 1

    db = Database(db_path)
    d_repo = DiscursosRepository(db)
    f_repo = FrasesRepository(db)
    e_repo = EmocionesRepository(db)

    codigo = args.codigo
    input_data = d_repo.get_input(codigo)
    if input_data is None:
        logger.error(f"Discurso '{codigo}' no encontrado en la DB.")
        return 1

    print()
    print(f"=== Discurso {codigo} ===")
    print(f"Título:    {input_data.get('titulo', '(sin título)')}")
    print(f"Fecha:     {input_data.get('fecha', '(sin fecha)')}")
    contenido = str(input_data.get("contenido", ""))
    print(f"Contenido: {len(contenido)} chars, {len(contenido.split())} palabras")
    print()

    print("Stages a nivel discurso:")
    for stage in ("summarizer", "metadata", "enunciation"):
        _print_discurso_stage(d_repo, codigo, stage)
    print()

    frases = f_repo.list_frases_of_discurso(codigo)
    print(f"Frases: {len(frases)}")
    if frases:
        ok_actores, fail_actores = _count_frase_status(f_repo, codigo, "actores")
        ok_emociones, fail_emociones = _count_frase_status(f_repo, codigo, "emociones")
        print(f"  actores:   {ok_actores} ok, {fail_actores} failed, "
              f"{len(frases) - ok_actores - fail_actores} pending")
        print(f"  emociones: {ok_emociones} ok, {fail_emociones} failed, "
              f"{len(frases) - ok_emociones - fail_emociones} pending")
    print()

    emociones = e_repo.list_emociones_of_discurso(codigo)
    print(f"Emociones detectadas (explotadas): {len(emociones)}")
    if emociones:
        ok_c = sum(1 for e in emociones if e["caracterizacion_payload"] is not None)
        fail_c = sum(1 for e in emociones if e["caracterizacion_error"] is not None)
        pending_c = len(emociones) - ok_c - fail_c
        print(f"  caracterizadas: {ok_c} ok, {fail_c} failed, {pending_c} pending")

        from collections import Counter
        tipos = Counter(e["tipo_emocion"] for e in emociones)
        if tipos:
            print(f"  tipos: {dict(tipos.most_common(5))}")
    print()

    return 0


def _print_discurso_stage(
    d_repo: DiscursosRepository,
    codigo: str,
    stage: str,
) -> None:
    """Imprime el estado resumido de un stage a nivel discurso."""
    payload = d_repo.get_payload(codigo, stage)  # type: ignore[arg-type]
    if payload is not None:
        summary = _summarize_payload(stage, payload)
        print(f"  ✓ {stage:<13s} {summary}")
        return

    failed = codigo in d_repo.list_failed(stage)  # type: ignore[arg-type]
    if failed:
        print(f"  ✗ {stage:<13s} (failed)")
    else:
        print(f"  · {stage:<13s} (pending)")


def _summarize_payload(stage: str, payload: dict) -> str:
    """Devuelve un resumen de una línea para el payload de un stage."""
    if stage == "summarizer":
        rg = payload.get("resumen_global", "")
        return f'"{rg[:80]}{"..." if len(rg) > 80 else ""}"'
    if stage == "metadata":
        return (
            f'tipo={payload.get("tipo_discurso", "?")}, '
            f'lugar={payload.get("ciudad", "?")}, {payload.get("pais", "?")}'
        )
    if stage == "enunciation":
        try:
            enunciatarios = json.loads(payload.get("enunciatarios", "[]"))
            n = len(enunciatarios) if isinstance(enunciatarios, list) else 0
        except (json.JSONDecodeError, TypeError):
            n = 0
        return f'enunciador="{payload.get("enunciador", "?")}", {n} enunciatarios'
    return "(payload presente)"


def _count_frase_status(
    f_repo: FrasesRepository,
    codigo: str,
    stage_key: str,
) -> tuple[int, int]:
    """Devuelve la cantidad de frases en estado ok y failed para una stage."""
    col_p = f"{stage_key}_payload"
    col_e = f"{stage_key}_error"
    row = f_repo._db.execute(
        f"""
        SELECT
            SUM(CASE WHEN {col_p} IS NOT NULL THEN 1 ELSE 0 END) AS ok,
            SUM(CASE WHEN {col_e} IS NOT NULL THEN 1 ELSE 0 END) AS failed
        FROM frases WHERE codigo = ?
        """,
        (codigo,),
    ).fetchone()
    return int(row["ok"] or 0), int(row["failed"] or 0)


