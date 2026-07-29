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

import pandas as pd
from loguru import logger

from emoparse.config import ConfigError, load_config
from emoparse.genres import (
    GenreRegistryError,
    default_genre,
    get_genre,
)
from emoparse.inputs import InputError, load_discursos
from emoparse.inputs.posts_loader import (
    PostsBundle,
    load_posts,
    posts_to_discursos,
)
from emoparse.knowledge import KnowledgeLoader
from emoparse.pipeline import (
    STAGE_ORDER,
    DEFAULT_ENABLED_STAGES,
    PipelineRunner,
)
from emoparse.pipeline.thread_builder import build_threads


def handle(args: argparse.Namespace) -> int:
    """Maneja `emoparse run`. Devuelve exit code."""
    try:
        cfg = load_config(args.config)
    except ConfigError as e:
        logger.error(f"Config inválido: {e}")
        return 1

    try:
        df_input, posts_bundle = _load_input(args.input)
    except InputError as e:
        logger.error(f"Input inválido: {e}")
        return 1

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

    db_path = _resolve_db_path(args.db, cfg.paths.runs_dir, args.run_id)
    accion = _resolver_db_existente(db_path, args)
    if accion == "cancelar":
        logger.info("[run] Cancelado por el usuario (DB existente).")
        return 1
    if accion == "sobrescribir":
        _borrar_db(db_path)
        logger.info(f"[run] DB existente eliminada: {db_path}")
    logger.info(f"[run] DB: {db_path}")

    if args.stages:
        try:
            enabled = _parse_stages(args.stages)
        except ValueError as e:
            logger.error(str(e))
            return 1
    else:
        enabled = DEFAULT_ENABLED_STAGES

    if genre.stages_invalidas:
        pedidas_invalidas = [s for s in enabled if s in genre.stages_invalidas]
        if pedidas_invalidas:
            logger.error(
                f"[run] Stage(s) inválida(s) para el género "
                f"'{genre.genre_id}': {', '.join(pedidas_invalidas)}. "
                f"No aplican a este género; sacalas de --stages."
            )
            return 1

    if not genre.summarizer and "summarizer" in enabled:
        enabled = tuple(s for s in enabled if s != "summarizer")
        logger.info(
            f"[run] Género '{genre.genre_id}' desactiva summarizer "
            f"(genre.summarizer=False)."
        )

    if genre.technoparse and not args.stages:
        # Solo sobre los defaults: un --stages explícito se respeta tal cual.
        # emoji_affect degrada a léxico-only si no tiene modelo asignado.
        agregar = tuple(
            s for s in ("technoparse", "emoji_affect") if s not in enabled
        )
        if agregar:
            enabled = (*agregar, *enabled)
            logger.info(
                f"[run] Género '{genre.genre_id}' habilita "
                f"{', '.join(agregar)} (genre.technoparse=True)."
            )

    emotion_scope = _collect_emotion_scope(args)
    if emotion_scope is not None:
        logger.info(
            f"[run] Alcance de detección de emociones: "
            f"{', '.join(emotion_scope)} (aplica a emotions y emotions_pass2)."
        )

    knowledge_dir = Path(cfg.paths.knowledge_dir).expanduser().resolve()
    if not knowledge_dir.is_dir():
        logger.error(
            f"Knowledge dir no encontrado: {knowledge_dir}. "
            "Verificar `paths.knowledge_dir` en el config."
        )
        return 1
    loader = KnowledgeLoader(knowledge_dir)

    with PipelineRunner(
        run_id=args.run_id,
        config=cfg,
        knowledge=loader,
        db_path=db_path,
        enabled_stages=enabled,
        genre=genre,
        emotion_scope=emotion_scope,
        embed_context=bool(getattr(args, "embed", False)),
    ) as runner:
        runner.ingest(df_input)
        if posts_bundle is not None:
            runner.ingest_posts(posts_bundle)
        report = runner.run()

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


def _resolver_db_existente(db_path: Path, args: argparse.Namespace) -> str:
    """Decide qué hacer si la DB del run ya existe.

    Devuelve 'nueva' (no existe), 'reanudar', 'sobrescribir' o 'cancelar'.
    Con flags explícitas (--overwrite-db / --resume) no pregunta; sin flags,
    pregunta por consola si hay TTY, y sin TTY falla con instrucciones
    (evita el pisado silencioso de corpus distintos sobre el mismo archivo).
    """
    if not db_path.exists():
        return "nueva"
    if getattr(args, "overwrite_db", False):
        return "sobrescribir"
    if getattr(args, "resume", False):
        return "reanudar"
    import sys
    if not sys.stdin.isatty():
        logger.error(
            f"La DB ya existe: {db_path}. Elegí explícitamente: --resume "
            "para reanudar ese run, u --overwrite-db para empezar de cero "
            "(elimina la DB)."
        )
        return "cancelar"
    print(f"\nLa DB del run ya existe: {db_path}")
    print("  [r] reanudar (seguir desde donde quedó; corpus debe ser el mismo)")
    print("  [s] sobrescribir (eliminar la DB y empezar de cero)")
    print("  [c] cancelar")
    while True:
        eleccion = input("¿Qué hacés? [r/s/c]: ").strip().lower()
        if eleccion in ("r", "reanudar"):
            return "reanudar"
        if eleccion in ("s", "sobrescribir"):
            confirmar = input(
                f"Se elimina {db_path.name} y todo su análisis. ¿Seguro? [s/N]: "
            ).strip().lower()
            if confirmar in ("s", "si", "sí", "y", "yes"):
                return "sobrescribir"
        elif eleccion in ("c", "cancelar", ""):
            return "cancelar"


def _borrar_db(db_path: Path) -> None:
    """Elimina la DB y sus archivos satélite de SQLite (-wal, -shm)."""
    for sufijo in ("", "-wal", "-shm"):
        f = Path(str(db_path) + sufijo)
        if f.exists():
            f.unlink()


def _load_input(
    input_arg: str,
) -> tuple[pd.DataFrame, PostsBundle | None]:
    """Carga el input según su extensión.

    - `.csv` / `.json`: corpus de discursos clásico → (df_discursos, None).
    - `.jsonl`: corpus de posts → reconstruye el árbol conversacional y
      deriva el DF de discursos que consume el pipeline (un post analizable
      por discurso; los reposts puros quedan solo en el bundle).
    """
    if Path(input_arg).suffix.lower() != ".jsonl":
        return load_discursos(input_arg), None

    bundle = load_posts(input_arg)
    df_posts, df_hilos = build_threads(bundle.posts)
    bundle = PostsBundle(posts=df_posts, autores=bundle.autores, hilos=df_hilos)
    df_input = posts_to_discursos(df_posts)
    n_hilos = int((df_hilos["n_posts"] > 1).sum()) if not df_hilos.empty else 0
    logger.info(
        f"[run] Corpus de posts: {len(df_posts)} posts → "
        f"{len(df_input)} analizables, {len(df_hilos)} conversaciones "
        f"({n_hilos} hilos con más de un post)."
    )
    return df_input, bundle


def _collect_emotion_scope(args: argparse.Namespace) -> tuple[str, ...] | None:
    """Reúne las flags de alcance en una tupla, o None si no se pasó ninguna.

    None significa "analizar emociones de todos los experienciadores"
    (comportamiento por defecto). Una tupla restringe el pase 1 a esas
    clases de experienciador.
    """
    scope: list[str] = []
    if getattr(args, "scope_enunciador", False):
        scope.append("enunciador")
    if getattr(args, "scope_enunciatarios", False):
        scope.append("enunciatarios")
    if getattr(args, "scope_actores", False):
        scope.append("actores")
    return tuple(scope) if scope else None


def _resolve_db_path(
    db_arg: str | None,
    runs_dir: str,
    run_id: str,
) -> Path:
    """Resuelve el path de la DB."""
    if db_arg is not None:
        return Path(db_arg).expanduser().resolve()
    return Path(runs_dir).expanduser().resolve() / f"{run_id}.sqlite"


def _parse_stages(raw: str) -> tuple[str, ...]:
    """Parsea la flag --stages: 'metadata,emotions' → ('metadata', 'emotions')."""
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
