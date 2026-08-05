#!/usr/bin/env python3
"""Valida las tres bases locales preparadas para el golden set v2."""

from __future__ import annotations

import argparse
from pathlib import Path

from emoparse.evaluation.corpus_validation import (
    CorpusValidationError,
    validate_golden_v2_corpora,
    write_corpus_manifest,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tuit-db", type=Path, required=True)
    parser.add_argument("--articulo-db", type=Path, required=True)
    parser.add_argument("--discurso-db", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True, help="Manifiesto JSON de salida.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        summaries = validate_golden_v2_corpora(
            {
                "tuit": args.tuit_db,
                "articulo_periodistico": args.articulo_db,
                "discurso_presidencial": args.discurso_db,
            }
        )
    except CorpusValidationError as error:
        print(f"ERROR: {error}")
        return 1

    manifest = write_corpus_manifest(summaries, args.out)
    print("Bases de origen del golden v2 aprobadas:")
    for genre, summary in summaries.items():
        extras = ""
        if summary.authors is not None:
            extras = f", autores={summary.authors}, conversaciones={summary.conversations or 0}"
        print(f"- {genre}: textos={summary.texts}, unidades={summary.units}{extras}")
    print(f"Manifiesto: {manifest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
