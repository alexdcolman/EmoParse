# ══════════════════════════════════════════════════════════════════════════════
#  emoparse.cli.commands.run_cmd
#
#  Subcomando `run`: orquesta el pipeline completo desde CLI.
#
#  Flujo:
#  1) Cargar config YAML (validado por Pydantic).
#  2) Cargar discursos del input (CSV/JSON).
#  3) Resolver path de la DB (default: <runs_dir>/<run_id>.sqlite).
#  4) Resolver el género: --genre <id> o default ('discurso_presidencial').
#  5) Construir KnowledgeLoader.
#  6) Construir PipelineRunner con enabled_stages parseado y el género.
#  7) Ingest + run.
#  8) Imprimir reporte final.
#
#  Flag --genre <id>: define el género del pipeline.
#  Default: 'discurso_presidencial'. Si se especifica otro, se resuelve vía registry.
#  Si no existe, error explícito con lista de géneros disponibles.
# ══════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

import argparse
from pathlib import Path

from loguru import logger

from emoparse.config import ConfigError, load_config
from emoparse.genres import (
    GenreRegistryError,
    default_genre,
    get_genre,
)
from emoparse.inputs import InputError, load_discursos
from emoparse.knowledge import KnowledgeLoader
from emoparse.pipeline import (
    STAGE_ORDER,
    DEFAULT_ENABLED_STAGES,
    PipelineRunner,
)


def handle(args: argparse.Namespace) -> int:
    """Maneja `emoparse run`. Devuelve exit code."""
    # ── Cargar config ────────────────────────────────────────────────────────
    try:
        cfg = load_config(args.config)
    except ConfigError as e:
        logger.error(f"Config inválido: {e}")
        return 1

    # ── Cargar input ─────────────────────────────────────────────────────────
    try:
        df_input = load_discursos(args.input)
    except InputError as e:
        logger.error(f"Input inválido: {e}")
        return 1

    # ── Resolver género (T-8) ────────────────────────────────────────────────
    # Si --genre es None se aplica default. Si se especifica, se busca en el registry.
    # Fallas por id inválido o plugin ausente generan error y salida con código 1.
    try:
        if args.genre is None:
            genre = default_genre()
            logger.info(
                f"[run] Género: {genre.genre_id} ({genre.display_name}) [default]"
            )
        else:
            genre = get_genre(args.genre)
            logger.info(
                f"[run] Género: {genre.genre_id} ({genre.display_name})"
            )
    except GenreRegistryError as e:
        logger.error(f"Género inválido: {e}")
        return 1

    # ── Resolver path de la DB ───────────────────────────────────────────────
    db_path = _resolve_db_path(args.db, cfg.paths.runs_dir, args.run_id)
    logger.info(f"[run] DB: {db_path}")

    # ── Parsear stages habilitadas ───────────────────────────────────────────
    if args.stages:
        try:
            enabled = _parse_stages(args.stages)
        except ValueError as e:
            logger.error(str(e))
            return 1
    else:
        enabled = DEFAULT_ENABLED_STAGES

    # Si el género desactiva summarizer (genre.summarizer=False),
    # la stage se elimina del set habilitado. El DAG permanece válido porque
    # metadata utiliza `contenido` si no existe `resumen_global`.
    if not genre.summarizer and "summarizer" in enabled:
        enabled = tuple(s for s in enabled if s != "summarizer")
        logger.info(
            f"[run] Género '{genre.genre_id}' desactiva summarizer "
            f"(genre.summarizer=False)."
        )

    # ── KnowledgeLoader ──────────────────────────────────────────────────────
    knowledge_dir = Path(cfg.paths.knowledge_dir).expanduser().resolve()
    if not knowledge_dir.is_dir():
        logger.error(
            f"Knowledge dir no encontrado: {knowledge_dir}. "
            "Verificar `paths.knowledge_dir` en el config."
        )
        return 1
    loader = KnowledgeLoader(knowledge_dir)

    # ── Ejecutar pipeline ────────────────────────────────────────────────────
    with PipelineRunner(
        run_id=args.run_id,
        config=cfg,
        knowledge=loader,
        db_path=db_path,
        enabled_stages=enabled,
        genre=genre,  # El runner recibe el género para dispatch interno.
    ) as runner:
        runner.ingest(df_input)
        report = runner.run()

    # ── Reporte final ────────────────────────────────────────────────────────
    print()
    print(f"=== Run {args.run_id} completado ===")
    print(f"DB:    {db_path}")
    print(f"Género: {genre.genre_id} ({genre.display_name})")
    print()
    print("Stages procesadas (items ok):")
    for stage_name in STAGE_ORDER:
        if stage_name in report:
            n = report[stage_name]
            mark = "✓" if n > 0 else "·"
            print(f"  {mark} {stage_name:<25s} {n}")
        else:
            print(f"    {stage_name:<25s} (saltada)")

    return 0


def _resolve_db_path(
    db_arg: str | None,
    runs_dir: str,
    run_id: str,
) -> Path:
    """Resuelve el path de la DB.

    - Si `--db` está definido: se respeta (relativo al CWD).
    - En caso contrario: <runs_dir>/<run_id>.sqlite.
    """
    if db_arg is not None:
        return Path(db_arg).expanduser().resolve()
    return Path(runs_dir).expanduser().resolve() / f"{run_id}.sqlite"


def _parse_stages(raw: str) -> tuple[str, ...]:
    """Parsea la flag --stages: 'metadata,emotions' → ('metadata', 'emotions').

    Valida que cada stage sea conocida. Lanza ValueError con mensaje útil.
    """
    parts = [s.strip() for s in raw.split(",") if s.strip()]
    if not parts:
        raise ValueError("--stages vacío.")
    unknown = [s for s in parts if s not in STAGE_ORDER]
    if unknown:
        raise ValueError(
            f"Stages desconocidas: {unknown}. "
            f"Válidas: {', '.join(STAGE_ORDER)}"
        )
    return tuple(parts)
