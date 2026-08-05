#!/usr/bin/env python3
"""Genera el contexto intradocumental de artículos y discursos del golden v2."""

from __future__ import annotations

import argparse
import shutil
import tempfile
from pathlib import Path

from emoparse.evaluation.document_context import build_document_context_snapshot


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Construye instantáneas de metadata y unidades vecinas para las campañas "
            "periodística y presidencial, sin red ni LLM."
        )
    )
    parser.add_argument(
        "--article-db",
        type=Path,
        default=Path("runs/golden_v2/articulo_periodistico.sqlite"),
    )
    parser.add_argument(
        "--article-sample",
        type=Path,
        default=Path("evals/golden/v2/articulo_periodistico_pasada1.csv"),
    )
    parser.add_argument(
        "--discourse-db",
        type=Path,
        default=Path("runs/golden_v2/discurso_presidencial.sqlite"),
    )
    parser.add_argument(
        "--discourse-sample",
        type=Path,
        default=Path("evals/golden/v2/discurso_presidencial_pasada1.csv"),
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=Path("data/golden_v2/context"),
    )
    return parser


def main() -> None:
    args = build_parser().parse_args()
    output = args.out_dir
    output.mkdir(parents=True, exist_ok=True)
    expected = (
        output / "articulo_annotation_context.jsonl",
        output / "articulo_context_manifest.json",
        output / "discurso_annotation_context.jsonl",
        output / "discurso_context_manifest.json",
    )
    existing = [path for path in expected if path.exists()]
    if existing:
        names = ", ".join(str(path) for path in existing)
        raise SystemExit(f"ERROR: ya existen salidas intradocumentales: {names}")

    temporary = Path(tempfile.mkdtemp(prefix=".intradocumental_", dir=output))
    try:
        article = build_document_context_snapshot(
            db_path=args.article_db,
            sample_csv=args.article_sample,
            snapshot_jsonl=temporary / "articulo_annotation_context.jsonl",
            manifest_json=temporary / "articulo_context_manifest.json",
            genre="articulo_periodistico",
            previous_units=1,
            next_units=1,
        )
        discourse = build_document_context_snapshot(
            db_path=args.discourse_db,
            sample_csv=args.discourse_sample,
            snapshot_jsonl=temporary / "discurso_annotation_context.jsonl",
            manifest_json=temporary / "discurso_context_manifest.json",
            genre="discurso_presidencial",
            previous_units=2,
            next_units=1,
        )
        for source in temporary.iterdir():
            source.replace(output / source.name)
    except Exception:
        shutil.rmtree(temporary, ignore_errors=True)
        raise
    else:
        temporary.rmdir()

    print("Contexto intradocumental del golden v2 preparado.")
    print(
        "Artículo periodístico: "
        f"unidades={article.units}, bloques={article.context_items}, "
        f"SHA-256={article.snapshot_sha256}"
    )
    print(
        "Discurso presidencial: "
        f"unidades={discourse.units}, bloques={discourse.context_items}, "
        f"SHA-256={discourse.snapshot_sha256}"
    )
    print(f"Directorio: {output.resolve()}")


if __name__ == "__main__":
    main()
