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
import sys
from datetime import date, datetime
from pathlib import Path

from loguru import logger

from emoparse.scraping import CsvAppender, get_source, SOURCES


def add_subparser(subparsers: argparse._SubParsersAction) -> argparse.ArgumentParser:
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
        help="Fuente a scrapear (ej. casarosada).",
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
        help="Máximo de discursos a extraer en esta corrida. None = sin tope.",
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
    return p


def parse_date(s: str) -> date:
    """Parser argparse: 'YYYY-MM-DD' → date. Público para uso en __main__._build_parser()."""
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except ValueError as e:
        raise argparse.ArgumentTypeError(
            f"Fecha inválida '{s}'. Formato esperado: YYYY-MM-DD."
        ) from e


def run(args: argparse.Namespace) -> int:
    """Ejecuta el subcomando. Devuelve exit code (0 = ok)."""
    logger.info(
        f"[scrape] source={args.source} output={args.output} "
        f"max={args.max} from={args.from_date} to={args.to_date} mode={args.mode}"
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

    n_extracted = 0
    n_skipped = 0
    n_filtered = 0
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
                max_items=args.max,
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

                appender.append(record)
                n_extracted += 1
                logger.info(
                    f"[scrape] ✓ {n_extracted:4d}  {record.fecha or '----------'}  "
                    f"{record.titulo[:80]}"
                )

                # Respeto al --max independiente del listado: si devuelve más de lo
                # requerido, se detiene.
                if args.max is not None and n_extracted >= args.max:
                    break

    except KeyboardInterrupt:
        logger.warning("[scrape] Interrumpido por usuario. CSV preservado.")
    finally:
        adapter.close()

    logger.info(
        f"[scrape] DONE. extraídos={n_extracted} ya_estaban={n_skipped} "
        f"fuera_de_rango={n_filtered} fallidos={n_failed} "
        f"→ {args.output}"
    )
    return 0
