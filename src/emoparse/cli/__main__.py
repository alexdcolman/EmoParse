# ══════════════════════════════════════════════════════════════════════════════
#  emoparse.cli.__main__
#
#  Entry point del CLI.
#
#  Define el parser principal, registra subcomandos y despacha la
#  ejecución al handler correspondiente.
# ══════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Callable

from loguru import logger

from emoparse.cli.commands import (
    app_cmd,
    inspect_cmd,
    judge_cmd,
    metrics_cmd,
    modalidad_cmd,
    retry_cmd,
    run_cmd,
    semas_cmd,
    stats_cmd,
    status_cmd,
    validate_cmd,
    export_cmd,
    scrape_cmd,
)


#: Handler de subcomando: recibe argparse.Namespace y devuelve exit code.
HandlerFn = Callable[[argparse.Namespace], int]


def _build_parser() -> argparse.ArgumentParser:
    """Construye el parser principal con sus subparsers."""
    parser = argparse.ArgumentParser(
        prog="emoparse",
        description=(
            "EmoParse — análisis semiótico de emociones en discursos. "
            "Orquesta el pipeline completo: ingest, agentes LLM por etapa, "
            "persistencia con resumability, y caché de respuestas LLM."
        ),
    )

    # Flags globales de logging, aplicadas antes del subcomando.
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Logging en DEBUG (más detalle).",
    )
    parser.add_argument(
        "-q", "--quiet",
        action="store_true",
        help="Logging en WARNING (menos ruido).",
    )

    sub = parser.add_subparsers(
        title="subcomandos",
        dest="command",
        # Se fuerza subcomando obligatorio para evitar ejecución vacía y
        # obtener feedback inmediato cuando se invoca `emoparse` sin args.
        required=True,
    )

    # ── run ──────────────────────────────────────────────────────────────────
    p_run = sub.add_parser(
        "run",
        help="Ejecuta el pipeline completo sobre un input.",
        description=(
            "Carga la config, ingesta los discursos del input, y ejecuta "
            "todas las stages habilitadas. Si la DB ya existe (mismo "
            "run-id), reanuda desde donde quedó."
        ),
    )
    p_run.add_argument("--config", "-c", required=True, help="Path al YAML de config.")
    p_run.add_argument("--input", "-i", required=True, help="Path al CSV/JSON de discursos.")
    p_run.add_argument("--run-id", required=True, help="Identificador único del run.")
    p_run.add_argument(
        "--db",
        help="Path al .sqlite del run. Default: <runs_dir>/<run_id>.sqlite.",
    )
    p_run.add_argument(
        "--stages",
        help=(
            "Lista comma-separated de stages a correr (subset de "
            "summarizer,metadata,enunciation,actors,emotions,emotions_pass2,"
            "explode_emotions,deixis,modalidad,normalize_emotions,characterizer,"
            "actants,judge,semas). Default: las stages por default "
            "(opt-in: emotions_pass2, deixis, modalidad, actants, judge)."
        ),
    )
    p_run.add_argument(
        "--genre",
        default=None,
        help=(
            "ID del género de discurso a aplicar. Default: "
            "'discurso_presidencial'. Los géneros disponibles dependen "
            "de los entry-points 'emoparse.genres' instalados. El "
            "género determina los roles enunciativos válidos, la unidad "
            "de chunking (frase/parrafo/documento), y opcionalmente "
            "overrides de modelos y batch_sizes."
        ),
    )
    p_run.add_argument(
        "--enunciador",
        dest="scope_enunciador",
        action="store_true",
        help=(
            "Acota la detección de emociones (ambos pases) a las del enunciador. Combinable "
            "con --enunciatarios y --actores (se unen). Si no se pasa "
            "ninguna de las tres, se analizan todos los experienciadores."
        ),
    )
    p_run.add_argument(
        "--enunciatarios",
        dest="scope_enunciatarios",
        action="store_true",
        help="Acota la detección de emociones (ambos pases) a las de los enunciatarios.",
    )
    p_run.add_argument(
        "--actores",
        dest="scope_actores",
        action="store_true",
        help=(
            "Acota la detección de emociones (ambos pases) a las de otros actores "
            "(distintos del enunciador y los enunciatarios)."
        ),
    )
    p_run.set_defaults(handler=run_cmd.handle)

    # ── status ───────────────────────────────────────────────────────────────
    p_status = sub.add_parser(
        "status",
        help="Muestra el progreso del pipeline en una DB.",
    )
    p_status.add_argument("--db", required=True, help="Path al .sqlite.")
    p_status.set_defaults(handler=status_cmd.handle)

    # ── retry ────────────────────────────────────────────────────────────────
    p_retry = sub.add_parser(
        "retry",
        help=(
            "Limpia errors / prepara reproceso. Dos modos: "
            "--stage (legacy, una stage entera) o --policy (declarativo)."
        ),
        description=(
            "Modos:\n"
            "  1) --stage <name>:  limpia todos los errors de esa stage. "
            "En el próximo `emoparse run` se reintentan.\n"
            "  2) --policy <file>: aplica un YAML de policies (target=failed/"
            "completed/all, filters declarativos sobre el payload JSON, "
            "override_model opcional). Si además se pasan --config + "
            "--input + --run-id, ejecuta el pipeline con el config "
            "overrideado por las policies."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p_retry.add_argument("--db", required=True, help="Path al .sqlite.")
    # Se valida en el handler para poder devolver un mensaje más claro
    # que el default de argparse.
    p_retry.add_argument(
        "--stage",
        help=(
            "Modo legacy: stage cuyos errors limpiar. Una de: summarizer, "
            "metadata, enunciation, actores, emociones, characterizer, "
            "actants."
        ),
    )
    p_retry.add_argument(
        "--policy",
        help=(
            "Modo policy: path al YAML de retry policies declarativas. "
            "Incompatible con --stage."
        ),
    )
    # Flags opcionales para ejecutar el pipeline luego de aplicar policies.
    p_retry.add_argument(
        "--config",
        help=(
            "(opcional, solo con --policy) Path al config.yaml. Si se pasa "
            "junto con --input y --run-id, después de aplicar las policies "
            "se ejecuta el pipeline con el config overrideado."
        ),
    )
    p_retry.add_argument(
        "--input",
        help="(opcional, solo con --policy) Path al CSV/JSON de discursos.",
    )
    p_retry.add_argument(
        "--run-id",
        dest="run_id",
        help="(opcional, solo con --policy) Identificador del run.",
    )
    p_retry.set_defaults(handler=retry_cmd.handle)

    # ── inspect ──────────────────────────────────────────────────────────────
    p_inspect = sub.add_parser(
        "inspect",
        help="Imprime los datos asociados a un discurso en la DB.",
    )
    p_inspect.add_argument("--db", required=True, help="Path al .sqlite.")
    p_inspect.add_argument(
        "--codigo",
        required=True,
        help="Código del discurso a inspeccionar.",
    )
    p_inspect.set_defaults(handler=inspect_cmd.handle)

    # ── stats ────────────────────────────────────────────────────────────────
    p_stats = sub.add_parser(
        "stats",
        help="Muestra estadísticas del cache LLM.",
    )
    p_stats.add_argument("--db", required=True, help="Path al .sqlite.")
    p_stats.set_defaults(handler=stats_cmd.handle)

    # ── metrics ──────────────────────────────────────────────────────────────
    p_metrics = sub.add_parser(
        "metrics",
        help="Muestra telemetría por stage del run (latencias, tokens, cache).",
        description=(
            "Imprime la última métrica registrada de cada stage del run. "
            "Las métricas se persisten al final de cada stage durante "
            "`emoparse run`. Si una stage corrió varias veces, se muestra "
            "la más reciente."
        ),
    )
    p_metrics.add_argument("--db", required=True, help="Path al .sqlite del run.")
    p_metrics.set_defaults(handler=metrics_cmd.handle)

    # ── judge ────────────────────────────────────────────────────────────────
    p_judge = sub.add_parser(
        "judge",
        help="Muestra los juicios del JudgeAgent (capa 3 de validación).",
        description=(
            "Read-only: imprime el resumen de juicios persistidos en la "
            "tabla `judgments`. La ejecución del judge se hace incluyéndolo "
            "en `--stages` durante `emoparse run` (es opt-in)."
        ),
    )
    p_judge.add_argument("--db", required=True, help="Path al .sqlite del run.")
    p_judge.add_argument(
        "--codigo",
        help="Mostrar solo este discurso. Default: todos.",
    )
    p_judge.add_argument(
        "--verbose",
        action="store_true",
        help="Listar también las emociones juzgadas como coherentes.",
    )
    p_judge.set_defaults(handler=judge_cmd.handle)

    # ── modalidad ────────────────────────────────────────────────────────────
    p_modalidad = sub.add_parser(
        "modalidad",
        help="Clasifica la modalidad referencial de los vínculos (NLP-only).",
        description=(
            "Clasifica, con el pre-pass NLP (spaCy) y SIN LLM, la modalidad "
            "referencial (designacion / referencia_gramatical / "
            "identificacion_inferencial) y la naturaleza del referente de cada "
            "vínculo marca→referente de una DB existente. Idempotente: solo "
            "clasifica lo que aún no tiene modalidad y no pisa lo editado a "
            "mano. La variante CON LLM (para los casos ambiguos) se corre vía "
            "`emoparse run --stages ...,modalidad`."
        ),
    )
    p_modalidad.add_argument("--db", required=True, help="Path al .sqlite del run.")
    p_modalidad.add_argument(
        "--nlp-model",
        dest="nlp_model",
        default=None,
        help=(
            "Modelo spaCy a usar (ES). Default: es_core_news_md con fallback a "
            "sm/lg. Instalá el modelo con `python -m spacy download <modelo>`."
        ),
    )
    p_modalidad.set_defaults(handler=modalidad_cmd.handle)

    # ── semas ────────────────────────────────────────────────────────────────
    p_semas = sub.add_parser(
        "semas",
        help="Mantenimiento de los semas de referentes canónicos de una DB.",
        description=(
            "Read-only por default (no ejecuta nada sin flags). Con --reset, "
            "borra TODOS los semas persistidos en `canonico_semas` (propuestos "
            "y editados a mano), sin distinguir origen. Para reasignarlos con "
            "el vocabulario vigente, correr después "
            "`emoparse run --stages ...,semas` sobre el mismo run."
        ),
    )
    p_semas.add_argument("--db", required=True, help="Path al .sqlite del run.")
    p_semas.add_argument(
        "--reset",
        action="store_true",
        help=(
            "Borra todos los semas existentes (propuestos y humanos). "
            "No hay vuelta atrás."
        ),
    )
    p_semas.set_defaults(handler=semas_cmd.handle)

    # ── export ───────────────────────────────────────────────────────────────
    p_export = sub.add_parser(
        "export",
        help="Exporta los resultados del run a CSVs (discursos, frases, emociones).",
        description=(
            "Genera tres CSVs en el directorio de salida: discursos.csv, "
            "frases.csv, emociones.csv. Los payloads de stages a nivel "
            "discurso se flatten a columnas; los de frases se preservan "
            "como JSON strings."
        ),
    )
    p_export.add_argument("--db", required=True, help="Path al .sqlite del run.")
    p_export.add_argument(
        "--output-dir",
        required=True,
        dest="output_dir",
        help="Directorio donde escribir los CSVs. Se crea si no existe.",
    )
    p_export.set_defaults(handler=export_cmd.handle)

    # ── validate ─────────────────────────────────────────────────────────────
    p_validate = sub.add_parser(
        "validate",
        help="Ejecuta validators de coherencia semiótica sobre las emociones caracterizadas.",
        description=(
            "Lee las emociones ya caracterizadas de la DB y aplica los domain "
            "validators. Las issues encontradas se persisten en 'validation_issues' "
            "y se muestran en consola. Siempre informativo (warnings), no bloquea."
        ),
    )
    p_validate.add_argument("--db", required=True, help="Path al .sqlite.")
    p_validate.add_argument(
        "--codigo",
        help="Validar solo este discurso (por código). Default: todos.",
    )
    p_validate.add_argument(
        "--verbose-issues",
        action="store_true",
        dest="verbose_issues",
        help="Mostrar detalle de cada issue aunque sean muchas.",
    )
    p_validate.add_argument(
        "--knowledge-dir",
        dest="knowledge_dir",
        help=(
            "Directorio de knowledge files. Permite cargar la ontología "
            "de emociones para activar V11_DesviacionOntologica."
        ),
    )
    p_validate.add_argument(
        "--ontology-file",
        default="emociones_ontologia.json",
        dest="ontology_file",
        help=(
            "Nombre del archivo de ontología de emociones dentro de "
            "--knowledge-dir. Default: emociones_ontologia.json."
        ),
    )
    p_validate.set_defaults(handler=validate_cmd.handle)

    # ── scrape ───────────────────────────────────────────────────────────────
    p_scrape = sub.add_parser(
        "scrape",
        help="Scrapea discursos de una fuente registrada al CSV.",
        description=(
            "Scrapea discursos de una fuente registrada. Modo append "
            "incremental: se puede interrumpir y reanudar (dedupe por URL). "
            "Requiere el extra [scraping]; para modo Selenium instalar también "
            "[scraping_selenium]."
        ),
    )
    p_scrape.add_argument(
        "--source",
        required=True,
        choices=sorted(scrape_cmd.SOURCES.keys()),
        help="Fuente a scrapear (ej. casarosada).",
    )
    p_scrape.add_argument(
        "--output",
        required=True,
        type=Path,
        help="CSV de salida. Se crea si no existe; append si ya existe.",
    )
    p_scrape.add_argument(
        "--max",
        type=int,
        default=None,
        help="Máximo de discursos a extraer en esta corrida. Default: sin tope.",
    )
    p_scrape.add_argument(
        "--from",
        dest="from_date",
        type=scrape_cmd.parse_date,
        default=None,
        metavar="YYYY-MM-DD",
        help=(
            "Solo discursos con fecha >= esta. Best-effort si la fuente "
            "no expone fechas en el listado."
        ),
    )
    p_scrape.add_argument(
        "--to",
        dest="to_date",
        type=scrape_cmd.parse_date,
        default=None,
        metavar="YYYY-MM-DD",
        help="Solo discursos con fecha <= esta.",
    )
    p_scrape.add_argument(
        "--mode",
        choices=("auto", "http", "selenium"),
        default="auto",
        help=(
            "Cómo descargar páginas. "
            "auto = HTTP con fallback Selenium (requiere [scraping_selenium]). "
            "http = solo HTTP. selenium = fuerza Selenium."
        ),
    )
    p_scrape.add_argument(
        "--timeout",
        type=float,
        default=20.0,
        help="Timeout HTTP por request en segundos. Default: 20.",
    )
    p_scrape.set_defaults(handler=scrape_cmd.run)

    # ── app ──────────────────────────────────────────────────────────────────
    app_cmd.register(sub)

    return parser


def _configure_logging(verbose: bool, quiet: bool) -> None:
    """Aplica el log level según las flags globales."""
    if verbose and quiet:
        # Si se pasan ambas flags, se prioriza verbose.
        level = "DEBUG"
    elif verbose:
        level = "DEBUG"
    elif quiet:
        level = "WARNING"
    else:
        level = "INFO"

    logger.remove()  # elimina el handler default de loguru
    logger.add(sys.stderr, level=level)


def main(argv: list[str] | None = None) -> int:
    """Entry point del CLI. Devuelve el exit code del proceso."""
    parser = _build_parser()
    args = parser.parse_args(argv)
    _configure_logging(args.verbose, args.quiet)

    handler: HandlerFn = args.handler
    try:
        return handler(args)
    except KeyboardInterrupt:
        logger.warning("[CLI] Interrumpido por el usuario.")
        return 130  # convención: SIGINT
    except Exception as e:
        # En modo verbose se muestra traceback completo; de lo contrario,
        # solo un mensaje resumido.
        if args.verbose:
            logger.exception(f"[CLI] Error: {e}")
        else:
            logger.error(f"[CLI] Error: {e}. Re-correr con -v para traceback.")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
