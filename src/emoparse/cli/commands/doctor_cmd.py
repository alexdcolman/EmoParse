"""Subcomando `doctor`: diagnóstico no destructivo de corpus tabulares."""

from __future__ import annotations

import argparse
from pathlib import Path

from loguru import logger

from emoparse.genres import GenreRegistryError, default_genre, get_genre
from emoparse.inputs.tabular_mapping import MappingError, diagnose_csv, load_mapping


def handle(args: argparse.Namespace) -> int:
    """Diagnostica un CSV sin escribir ni transformar el archivo."""
    path = Path(args.input).expanduser().resolve()
    if path.suffix.lower() != ".csv":
        logger.error("[doctor] Por ahora el diagnóstico tabular admite archivos CSV.")
        return 2

    try:
        genre = default_genre() if args.genre is None else get_genre(args.genre)
        mapping = load_mapping(args.mapping) if args.mapping else None
        report = diagnose_csv(path, genre=genre, mapping=mapping)
    except (GenreRegistryError, MappingError) as exc:
        logger.error(f"[doctor] {exc}")
        return 2

    print()
    print(f"=== Diagnóstico de corpus: {path.name} ===")
    print(f"Encoding:       {report.csv.encoding}" + (" (BOM)" if report.csv.bom else ""))
    print(f"Delimitador:    {_display_delimiter(report.csv.delimiter)}")
    print(f"Encabezado:     fila {report.csv.header_row}")
    print(f"Filas:          {report.rows}")
    print(f"Columnas:       {', '.join(report.columns)}")
    print(f"Género:         {report.genre_id}")
    print(f"Unidad:         {report.genre_unit}")
    print(f"Unidades/fila:  {report.mean_units_per_record:.2f}")
    print(f"Caracteres/u.:  {report.mean_chars_per_unit:.1f}")
    print()
    print("Mapeo propuesto:")
    for proposal in report.proposals:
        source = proposal.source or "[revisar]"
        print(f"  {proposal.target:<18} <- {source}  ({proposal.confidence}: {proposal.reason})")
    print()
    print(
        f"Filas individualmente utilizables: {report.individually_viable_rows}/{report.rows} "
        f"({report.viable_ratio:.0%})"
    )
    if report.date_parse_ratio is not None:
        print(f"Fechas parseables: {report.date_parse_ratio:.0%}")
    print(f"Filas con HTML: {report.html_rows}")

    if report.blocking:
        print("\nBloqueos para la ingesta:")
        for item in report.blocking:
            print(f"  - {item}")
    if report.warnings:
        print("\nAdvertencias:")
        for item in report.warnings:
            print(f"  - {item}")
    if report.ready:
        print("\nEstado: el diagnóstico no encontró bloqueos estructurales.")
    else:
        print("\nEstado: revisar el corpus o el mapping antes de ejecutar `emoparse run`.")
    return 0


def _display_delimiter(value: str) -> str:
    return "TAB" if value == "\t" else repr(value)


def register(subparsers: argparse._SubParsersAction) -> None:  # type: ignore[type-arg]
    """Registra `doctor`."""
    parser = subparsers.add_parser(
        "doctor",
        help="Diagnostica un CSV de terceros sin modificarlo.",
        description=(
            "Inspecciona encoding, delimitador, encabezado, columnas, identificadores, contenido, "
            "fechas, HTML y granularidad antes de adaptar un corpus tabular. No escribe el input."
        ),
    )
    parser.add_argument("--input", "-i", required=True, help="CSV a diagnosticar.")
    parser.add_argument(
        "--genre",
        default=None,
        help="Género con el que se evaluará la granularidad. Default: discurso_presidencial.",
    )
    parser.add_argument(
        "--mapping",
        default=None,
        metavar="ARCHIVO.yaml",
        help="Mapping ya editado que se quiere verificar en lugar de usar la propuesta automática.",
    )
    parser.set_defaults(handler=handle)
