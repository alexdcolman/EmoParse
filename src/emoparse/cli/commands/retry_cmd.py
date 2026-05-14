# ══════════════════════════════════════════════════════════════════════════════
# emoparse.cli.commands.retry_cmd
#
# Subcomando `retry`:
# permite limpiar errores de stages o aplicar policies de retry desde archivo.
#
# Modos:
# - --stage <name>: limpia errores de una stage
# - --policy <file.yaml>: aplica policies de retry y opcionalmente ejecuta pipeline
# ══════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

import argparse
from pathlib import Path

from loguru import logger

from emoparse.storage.db import Database
from emoparse.storage.discursos import DiscursosRepository
from emoparse.storage.emociones import EmocionesRepository
from emoparse.storage.frases import FrasesRepository

#: Mapa de stage → (capa, key). La key corresponde a columnas
#: `<key>_payload` y `<key>_error` en las tablas.
_STAGE_DISPATCH: dict[str, tuple[str, str]] = {
    "summarizer": ("discursos", "summarizer"),
    "metadata": ("discursos", "metadata"),
    "enunciation": ("discursos", "enunciation"),
    "actores": ("frases", "actores"),
    "emociones": ("frases", "emociones"),
    "characterizer": ("emociones_table", ""),  # caso especial
}


def handle(args: argparse.Namespace) -> int:
    db_path = Path(args.db).expanduser().resolve()
    if not db_path.is_file():
        logger.error(f"DB no encontrada: {db_path}")
        return 1

    has_stage = getattr(args, "stage", None) is not None
    has_policy = getattr(args, "policy", None) is not None

    if has_stage and has_policy:
        logger.error(
            "Pasaste --stage y --policy a la vez. Son modos mutuamente "
            "excluyentes: --stage limpia errors de UNA stage; --policy "
            "aplica un archivo con N policies declarativas."
        )
        return 1

    if not has_stage and not has_policy:
        logger.error(
            "Falta argumento: --stage <name> o --policy <file.yaml>."
        )
        return 1

    if has_policy:
        return _handle_policy_mode(args, db_path)
    return _handle_stage_mode(args, db_path)


# ── Modo legacy: --stage X ──────────────────────────────────────────────────


def _handle_stage_mode(args: argparse.Namespace, db_path: Path) -> int:
    if args.stage not in _STAGE_DISPATCH:
        logger.error(
            f"Stage desconocida: '{args.stage}'. "
            f"Válidas: {', '.join(_STAGE_DISPATCH)}"
        )
        return 1

    db = Database(db_path)
    layer, key = _STAGE_DISPATCH[args.stage]

    if layer == "discursos":
        n = DiscursosRepository(db).clear_errors(key)  # type: ignore[arg-type]
    elif layer == "frases":
        n = FrasesRepository(db).clear_errors(key)  # type: ignore[arg-type]
    elif layer == "emociones_table":
        n = EmocionesRepository(db).clear_errors()
    else:
        logger.error(f"Capa desconocida: {layer}")
        return 2

    print()
    if n == 0:
        print(f"No había errors en stage '{args.stage}'. Nada que reintentar.")
    else:
        print(f"Limpiados {n} error(s) en stage '{args.stage}'.")
        print(f"En el próximo `emoparse run` se reintentarán.")
    return 0


# ── Modo policy: --policy file.yaml ─────────────────────────────────────────


def _handle_policy_mode(args: argparse.Namespace, db_path: Path) -> int:
    """Aplica policies declarativas desde archivo; opcionalmente ejecuta pipeline si se pasan config, input y run-id."""
    # Import diferido: evitar ciclo / no cargar pandera si no hace falta.
    from emoparse.pipeline.retry_policies import (
        RetryPolicyApplier,
        load_policy_file,
    )

    policy_path = Path(args.policy).expanduser().resolve()
    if not policy_path.is_file():
        logger.error(f"Archivo de policy no encontrado: {policy_path}")
        return 1

    try:
        policy_file = load_policy_file(policy_path)
    except Exception as e:
        logger.error(f"Policy file inválido: {e}")
        return 1

    if not policy_file.policies:
        logger.warning("Policy file no tiene policies. Nada que hacer.")
        return 0

    config = None
    config_path = getattr(args, "config", None)
    if config_path is not None:
        try:
            from emoparse.config.loader import load_config

            config = load_config(config_path)
        except Exception as e:
            logger.error(f"Config inválido en {config_path}: {e}")
            return 1

    db = Database(db_path)
    applier = RetryPolicyApplier(db)
    try:
        results, new_config = applier.apply(policy_file, base_config=config)
    except Exception as e:
        logger.error(f"Error aplicando policies: {e}")
        return 2

    print()
    print(f"Aplicadas {len(results)} policy(s) sobre {db_path.name}:")
    total = 0
    for r in results:
        line = f"  - {r.stage:18s} → {r.rows_marked_pending:>5d} fila(s) marcadas pending"
        if r.override_model:
            line += f"   [override: {r.override_model}]"
        print(line)
        total += r.rows_marked_pending
    print(f"Total: {total} fila(s).")

    input_path = getattr(args, "input", None)
    run_id = getattr(args, "run_id", None)
    if config is None or input_path is None or run_id is None:
        print()
        print("Modo prepare-only: filas marcadas, no se ejecutó el pipeline.")
        print("Para ejecutar: re-correr con --config, --input y --run-id, ")
        print("o disparar `emoparse run` manualmente.")
        return 0

    print()
    print("Ejecutando pipeline con config overrideado por policies...")

    try:
        from emoparse.inputs import load_discursos
        from emoparse.knowledge import KnowledgeLoader
        from emoparse.pipeline import PipelineRunner

        df_input = load_discursos(input_path)
        loader = KnowledgeLoader(new_config.paths.knowledge_dir)  # type: ignore[union-attr]

        # Subset opcional: solo stages incluidas en las policies.
        # Motivo: al reintentar `emotions` fallida, evitar ejecución completa de otras stages.
        stages_in_policies = tuple({r.stage for r in results})

        runner = PipelineRunner(
            run_id=run_id,
            config=new_config,  # type: ignore[arg-type]
            knowledge=loader,
            db_path=db_path,
            enabled_stages=stages_in_policies,
        )
        runner.ingest(df_input)
        report = runner.run()
        print()
        print(f"Pipeline completado. Reporte: {report}")
        return 0
    except Exception as e:
        logger.exception(f"Ejecución del pipeline falló: {e}")
        return 2
