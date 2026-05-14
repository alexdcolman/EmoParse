# ══════════════════════════════════════════════════════════════════════════════
#  emoparse.cli.commands.validate_cmd
#
#  Subcomando: emoparse validate --db <path> [--codigo <code>] [--verbose-issues]
#
#  Ejecuta los domain validators sobre las emociones caracterizadas de
#  una DB y muestra un resumen de las issues encontradas.
#
#  Salida:
#  - Resumen por validator (count).
#  - Detalle de issues (si --verbose-issues o si hay pocas).
#  - Exit code 0 siempre (las issues son warnings, no errores de pipeline).
# ══════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

import argparse
import json
from pathlib import Path

from loguru import logger

from emoparse.domain.validators.runner import ValidationRunner
from emoparse.storage.db import Database
from emoparse.storage.validation import ValidationRepository

#: Umbral: si hay ≤ N issues en total, se muestran en detalle sin --verbose-issues.
_AUTO_DETAIL_THRESHOLD = 10


def handle(args: argparse.Namespace) -> int:
    """Handler del subcomando validate."""
    db_path = Path(args.db)
    if not db_path.exists():
        logger.error(f"[validate] DB no encontrada: {db_path}")
        return 2

    db = Database(db_path)

    # Verificación de existencia de tabla `emociones` (DB inicializada).
    if not db.table_exists("emociones"):
        logger.error(
            "[validate] La DB no tiene tabla 'emociones'. "
            "¿El pipeline corrió al menos hasta la etapa de emociones?"
        )
        return 2

    # Filtro por código si está definido.
    codigo_filter: str | None = getattr(args, "codigo", None)

    runner = ValidationRunner(db)

    if codigo_filter:
        # Ejecución limitada al discurso especificado.
        issues = runner._run_discurso(codigo_filter)  # noqa: SLF001
        if issues:
            runner._repo.delete_issues_for_codigo(codigo_filter)  # noqa: SLF001
            runner._repo.save_issues(issues)  # noqa: SLF001
    else:
        issues = runner.run()

    repo = ValidationRepository(db)
    total = repo.count_total()
    by_validator = repo.count_by_validator()

    if total == 0:
        print("✓ Sin issues de coherencia encontradas.")
        return 0

    print(f"\n{'─'*60}")
    print(f"  VALIDATION ISSUES — {total} en total")
    print(f"{'─'*60}")
    print(f"  {'Validator':<12}  {'Issues':>6}")
    print(f"  {'─'*12}  {'─'*6}")
    for vid, cnt in sorted(by_validator.items()):
        print(f"  {vid:<12}  {cnt:>6}")
    print(f"{'─'*60}\n")

    # Detalle mostrado siempre si verbose o si el total es bajo.
    show_detail = getattr(args, "verbose_issues", False) or total <= _AUTO_DETAIL_THRESHOLD

    if show_detail:
        all_issues = repo.list_issues(codigo=codigo_filter)
        _print_issues_detail(all_issues)
    else:
        print(
            f"  Usá --verbose-issues para ver el detalle de cada issue.\n"
            f"  O inspeccioná la tabla 'validation_issues' en la DB.\n"
        )

    return 0


def _print_issues_detail(issues: list[dict]) -> None:
    """Imprime el detalle de cada issue en formato legible."""
    for issue in issues:
        fi = issue["frase_idx"]
        ei = issue["emocion_idx"]
        loc = f"frase {fi}, emoción {ei}" if fi is not None else "discurso"

        print(f"[{issue['validator_id']}] {issue['codigo']} — {loc}")
        print(f"  {issue['mensaje']}")
        if issue.get("contexto"):
            ctx_str = json.dumps(issue["contexto"], ensure_ascii=False)
            print(f"  contexto: {ctx_str}")
        print()
