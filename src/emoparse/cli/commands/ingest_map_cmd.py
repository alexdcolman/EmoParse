"""Subcomando `ingest-map`: propone un mapping YAML revisable para un CSV."""

from __future__ import annotations

import argparse
from pathlib import Path

from loguru import logger

from emoparse.genres import GenreRegistryError, default_genre, get_genre
from emoparse.inputs.tabular_mapping import MappingError, diagnose_csv, render_mapping_yaml

COMMAND_NAME = "ingest-map"


def handle(args: argparse.Namespace) -> int:
    """Propone y escribe un mapping sin modificar el corpus de origen."""
    source = Path(args.input).expanduser().resolve()
    output = Path(args.out).expanduser().resolve()
    if source.suffix.lower() != ".csv":
        logger.error("[ingest-map] Por ahora el mapeo tabular admite archivos CSV.")
        return 2
    if output.exists() and not args.overwrite:
        logger.error(
            f"[ingest-map] El destino ya existe: {output}. "
            "Usá --overwrite sólo si querés reemplazarlo."
        )
        return 2

    try:
        genre = default_genre() if args.genre is None else get_genre(args.genre)
        report = diagnose_csv(source, genre=genre)
    except (GenreRegistryError, MappingError) as exc:
        logger.error(f"[ingest-map] {exc}")
        return 2

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(render_mapping_yaml(report), encoding="utf-8")

    unresolved = [proposal.target for proposal in report.proposals if proposal.source is None]
    print(f"Mapping escrito en: {output}")
    if unresolved:
        print("Revisar antes de usarlo; quedaron sin resolver: " + ", ".join(unresolved))
    else:
        print("Revisar el YAML antes de usarlo; la propuesta no se aplica automáticamente.")
    print(f"Después: emoparse doctor --input {source} --mapping {output}")
    return 0


def register(subparsers: argparse._SubParsersAction) -> None:  # type: ignore[type-arg]
    """Registra `ingest-map`."""
    parser = subparsers.add_parser(
        "ingest-map",
        help="Propone un mapping YAML editable para un CSV de terceros.",
        description=(
            "Detecta el formato y propone correspondencias de columnas. Escribe un YAML revisable; "
            "nunca transforma ni reescribe el corpus de origen."
        ),
    )
    parser.add_argument("--input", "-i", required=True, help="CSV de origen.")
    parser.add_argument("--out", required=True, help="YAML de mapping a escribir.")
    parser.add_argument(
        "--genre",
        default=None,
        help="Género para incluir, cuando corresponda, su metadata propia en la propuesta.",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Permite reemplazar el archivo --out si ya existe.",
    )
    parser.set_defaults(handler=handle)
