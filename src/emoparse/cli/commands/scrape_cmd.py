# ══════════════════════════════════════════════════════════════════════════════
#  emoparse.cli.commands.scrape_cmd
#
#  Subcomando `emoparse scrape`: scrapea una fuente al CSV.
#
#  Flujo:
#  1) Resuelve el adapter via `get_source(--source)`.
#  2) Inicializa CsvAppender sobre --output (append idempotente por URL).
#  3) Itera URLs vía adapter.list_discursos(...) hasta agotar o --max.
#  4) Para cada URL, salta si ya está en el CSV, sino fetch + append.
#  5) Filtra por --from / --to (best-effort, después del fetch).
#
#  El comando es interruptible: Ctrl-C deja el CSV con todo lo extraído
#  hasta ahí. Re-correr el comando reanuda donde quedó (gracias al
#  dedupe por URL del CsvAppender).
# ══════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

import argparse
from datetime import date, datetime
from pathlib import Path

from loguru import logger

from emoparse.acquisition import SOURCES, CsvAppender, get_source


def register(subparsers: argparse._SubParsersAction) -> None:
    """Registra `scrape` como subcomando en el CLI principal."""
    p = subparsers.add_parser(
        "scrape",
        help="Scrapear discursos de una fuente al CSV.",
        description=(
            "Scrapea discursos de una fuente registrada. Modo append "
            "incremental: se puede interrumpir y reanudar (dedupe por URL)."
        ),
    )
    p.add_argument(
        "--source",
        required=True,
        choices=sorted(SOURCES.keys()),
        help="Fuente registrada a scrapear.",
    )
    p.add_argument(
        "--output",
        required=True,
        type=Path,
        help="CSV de salida. Se crea si no existe; append si ya existe.",
    )
    p.add_argument(
        "--max",
        type=int,
        default=None,
        help=(
            "Máximo de discursos efectivamente extraídos y escritos en esta corrida. "
            "Las URLs fallidas, omitidas o ya presentes no consumen el tope."
        ),
    )
    p.add_argument(
        "--from",
        dest="from_date",
        type=parse_date,
        default=None,
        metavar="YYYY-MM-DD",
        help="Solo discursos con fecha >= esta. Best-effort si la fuente "
        "no expone fechas en el listado.",
    )
    p.add_argument(
        "--to",
        dest="to_date",
        type=parse_date,
        default=None,
        metavar="YYYY-MM-DD",
        help="Solo discursos con fecha <= esta.",
    )
    p.add_argument(
        "--max-after-filter",
        action="store_true",
        help=argparse.SUPPRESS,
    )
    p.add_argument(
        "--section",
        action="append",
        default=None,
        metavar="SECCION",
        help=(
            "Página/12: limitar el descubrimiento a una o varias secciones RSS. "
            "Puede repetirse o recibir valores separados por coma, por ejemplo "
            "--section economia --section deportes."
        ),
    )
    p.add_argument(
        "--subtype",
        action="append",
        default=None,
        metavar="SUBTIPO",
        help=(
            "Página/12: limitar la salida a subtipos de artículo. "
            "Valores públicos: static y lbp_article. Puede repetirse o "
            "recibir valores separados por coma. Si se omite, se aceptan ambos."
        ),
    )
    p.add_argument(
        "--mode",
        choices=("auto", "http", "selenium"),
        default="auto",
        help="Cómo descargar páginas. auto = HTTP con fallback Selenium.",
    )
    p.add_argument(
        "--timeout",
        type=float,
        default=20.0,
        help="Timeout HTTP por request (segundos).",
    )
    p.set_defaults(handler=run)


def parse_date(s: str) -> date:
    """Parser argparse: 'YYYY-MM-DD' → date. Público para uso en __main__._build_parser()."""
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except ValueError as e:
        raise argparse.ArgumentTypeError(
            f"Fecha inválida '{s}'. Formato esperado: YYYY-MM-DD."
        ) from e


def _parse_multi_values(values: list[str] | None) -> tuple[str, ...]:
    """Normaliza una opción repetible/coma-separada preservando el orden."""
    if not values:
        return ()
    parsed: list[str] = []
    for raw in values:
        for part in raw.split(","):
            value = part.strip()
            if value and value not in parsed:
                parsed.append(value)
    return tuple(parsed)


def _parse_sections(values: list[str] | None) -> tuple[str, ...]:
    """Compatibilidad interna para la opción ``--section``."""
    return _parse_multi_values(values)


def _parse_subtypes(values: list[str] | None) -> tuple[str, ...]:
    """Normaliza la opción pública ``--subtype`` de Página/12."""
    return _parse_multi_values(values)


def run(args: argparse.Namespace) -> int:
    """Ejecuta el subcomando. Devuelve exit code (0 = ok)."""
    logger.info(
        f"[scrape] source={args.source} output={args.output} "
        f"max={args.max} from={args.from_date} to={args.to_date} mode={args.mode}"
    )

    # `--max` cuenta siempre registros efectivamente escritos. No se pasa el
    # tope al listado porque una URL descubierta puede fallar, quedar vacía,
    # estar ya persistida o caer fuera del rango de fechas.
    max_items_for_listing = None
    if args.max_after_filter:
        logger.debug(
            "[scrape] --max-after-filter se conserva por compatibilidad; "
            "--max ya cuenta siempre registros efectivamente extraídos."
        )

    # Filtros aplicados post-fetch; la fuente puede no exponer fechas en el listado.
    def _date_in_range(record_fecha: str) -> bool:
        """Filtra por --from / --to. Si la fecha no parsea, se incluye por defecto."""
        if not args.from_date and not args.to_date:
            return True
        try:
            d = datetime.strptime(record_fecha[:10], "%Y-%m-%d").date()
        except (ValueError, TypeError):
            logger.debug(f"[scrape] Fecha no parseable: {record_fecha!r}, incluyo igual")
            return True
        if args.from_date and d < args.from_date:
            return False
        if args.to_date and d > args.to_date:
            return False
        return True

    adapter_kwargs: dict[str, object] = {
        "mode": args.mode,
        "timeout": args.timeout,
    }
    sections = _parse_sections(getattr(args, "section", None))
    subtypes = _parse_subtypes(getattr(args, "subtype", None))
    if sections or subtypes:
        if args.source != "pagina12":
            option = "--section" if sections else "--subtype"
            logger.error(f"[scrape] {option} sólo está disponible para --source pagina12.")
            return 2
    if sections:
        adapter_kwargs["sections"] = sections
    if subtypes:
        adapter_kwargs["subtypes"] = subtypes

    n_written = 0
    n_counted = 0
    n_skipped = 0
    n_filtered = 0
    n_source_filtered = 0
    n_failed = 0

    try:
        adapter = get_source(args.source, **adapter_kwargs)
    except (ValueError, TypeError) as e:
        logger.error(f"[scrape] No se pudo construir el adapter: {e}")
        return 2

    appender = CsvAppender(args.output)

    try:
        with adapter:
            for url in adapter.list_discursos(
                max_items=max_items_for_listing,
                from_date=args.from_date,
                to_date=args.to_date,
            ):
                if appender.has_url(url):
                    n_skipped += 1
                    logger.debug(f"[scrape] Ya en CSV, skip: {url}")
                    continue

                try:
                    record = adapter.fetch_discurso(url)
                except Exception as e:
                    n_failed += 1
                    logger.exception(f"[scrape] Error fetcheando {url}: {e}")
                    continue

                if record is None:
                    n_failed += 1
                    logger.warning(f"[scrape] Sin contenido: {url}")
                    continue

                if not _date_in_range(record.fecha):
                    n_filtered += 1
                    continue

                if not adapter.accepts_record(record):
                    n_source_filtered += 1
                    logger.debug(f"[scrape] Filtrado por el adapter: {record.url}")
                    continue

                appender.append(record)
                n_written += 1
                counts = adapter.counts_toward_max(record)
                if counts:
                    n_counted += 1
                marker = "✓" if counts else "·"
                logger.info(
                    f"[scrape] {marker} escritos={n_written:4d} objetivo={n_counted:4d}  "
                    f"{record.fecha or '----------'}  {record.titulo[:80]}"
                )

                # ``--max`` cuenta el tipo principal definido por el adapter.
                # Los documentos auxiliares preservados pueden escribirse sin
                # consumir el cupo (por ejemplo, índices editoriales de Página/12).
                if args.max is not None and n_counted >= args.max:
                    break

    except KeyboardInterrupt:
        logger.warning("[scrape] Interrumpido por usuario. CSV preservado.")
    finally:
        adapter.close()

    logger.info(
        f"[scrape] DONE. escritos={n_written} objetivo={n_counted} "
        f"ya_estaban={n_skipped} fuera_de_rango={n_filtered} "
        f"filtrados_fuente={n_source_filtered} fallidos={n_failed} → {args.output}"
    )
    return 0
