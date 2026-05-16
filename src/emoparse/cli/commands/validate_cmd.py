# ══════════════════════════════════════════════════════════════════════════════
#  emoparse.cli.commands.validate_cmd
#
#  Subcomando: emoparse validate --db <path> [opciones]
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
from typing import Any

from loguru import logger

from emoparse.domain.validators.runner import ValidationRunner
from emoparse.knowledge.loader import KnowledgeError, KnowledgeLoader
from emoparse.storage.db import Database
from emoparse.storage.validation import ValidationRepository

#: Umbral: si hay ≤ N issues en total, se muestran en detalle sin --verbose-issues.
_AUTO_DETAIL_THRESHOLD = 10

#: Nombre por default del archivo de ontología de emociones.
_DEFAULT_ONTOLOGY_FILENAME = "emociones_ontologia.json"


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

    # Carga opcional de la ontología de emociones para V11.
    emotion_ontology: dict[str, Any] | None = _load_emotion_ontology(args)

    # Filtro por código si está definido.
    codigo_filter: str | None = getattr(args, "codigo", None)

    runner = ValidationRunner(db, emotion_ontology=emotion_ontology)

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
    print(f"  {'Validator':<30}  {'Issues':>6}")
    print(f"  {'─'*30}  {'─'*6}")
    for vid, cnt in sorted(by_validator.items()):
        print(f"  {vid:<30}  {cnt:>6}")
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


# ── Helpers ───────────────────────────────────────────────────────────────────

def _load_emotion_ontology(args: argparse.Namespace) -> dict[str, Any] | None:
    """Intenta cargar la ontología de emociones para V11.

    Si --knowledge-dir no se especificó o el archivo no existe, loguea
    a INFO y devuelve None (el runner corre sin V11). Nunca bloquea.
    """
    knowledge_dir: str | None = getattr(args, "knowledge_dir", None)
    if not knowledge_dir:
        logger.info(
            "[validate] --knowledge-dir no especificado: V11_DesviacionOntologica "
            "no se ejecutará. Pasá --knowledge-dir <path> para activarlo."
        )
        return None

    ontology_filename: str = getattr(args, "ontology_file", _DEFAULT_ONTOLOGY_FILENAME)

    try:
        loader = KnowledgeLoader(knowledge_dir)
        ontology = loader.load_emotion_ontology(ontology_filename)
        logger.info(
            f"[validate] Ontología de emociones cargada desde "
            f"'{ontology_filename}' — V11 activo."
        )
        return ontology
    except KnowledgeError as e:
        logger.info(
            f"[validate] No se pudo cargar la ontología de emociones "
            f"({e}). V11_DesviacionOntologica no se ejecutará."
        )
        return None


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
