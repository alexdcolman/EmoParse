#!/usr/bin/env python3
"""Fusiona una descarga candidata con un corpus CSV local, sin superar el objetivo."""

from __future__ import annotations

import argparse
import csv
import os
from pathlib import Path
from tempfile import NamedTemporaryFile


class MergeError(ValueError):
    """El corpus candidato no puede fusionarse de forma segura."""


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus", type=Path, required=True)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--target", type=int, required=True)
    return parser


def merge_csv_corpus(corpus: Path, candidate: Path, target: int) -> int:
    """Conserva las filas existentes y agrega candidatas nuevas hasta `target`."""
    if target < 1:
        raise MergeError("--target debe ser mayor que cero")

    existing_rows, existing_fields = _read_csv(corpus, allow_missing=True)
    candidate_rows, candidate_fields = _read_csv(candidate, allow_missing=False)
    fieldnames = _merge_fieldnames(existing_fields, candidate_fields)
    if "url" not in fieldnames:
        raise MergeError("los CSV deben incluir la columna `url`")

    merged: list[dict[str, str]] = []
    seen: set[str] = set()
    for row in [*existing_rows, *candidate_rows]:
        key = row.get("url", "").strip() or row.get("codigo", "").strip()
        if not key or key in seen:
            continue
        seen.add(key)
        merged.append(row)
        if len(merged) >= target:
            break

    if not merged:
        raise MergeError("la adquisición no produjo filas utilizables")

    corpus.parent.mkdir(parents=True, exist_ok=True)
    _write_atomic(corpus, fieldnames, merged)
    return len(merged)


def _read_csv(
    path: Path,
    *,
    allow_missing: bool,
) -> tuple[list[dict[str, str]], list[str]]:
    if not path.exists():
        if allow_missing:
            return [], []
        raise MergeError(f"archivo no encontrado: {path}")
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        fieldnames = list(reader.fieldnames or [])
        return [dict(row) for row in reader], fieldnames


def _merge_fieldnames(first: list[str], second: list[str]) -> list[str]:
    result = list(first)
    result.extend(name for name in second if name not in result)
    return result


def _write_atomic(
    path: Path,
    fieldnames: list[str],
    rows: list[dict[str, str]],
) -> None:
    with NamedTemporaryFile(
        "w",
        encoding="utf-8-sig",
        newline="",
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
        delete=False,
    ) as handle:
        temp_path = Path(handle.name)
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({name: row.get(name, "") for name in fieldnames})
    os.replace(temp_path, path)


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        total = merge_csv_corpus(args.corpus, args.candidate, args.target)
    except MergeError as error:
        print(f"ERROR: {error}")
        return 1
    print(f"Corpus actualizado: {args.corpus} ({total} textos)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
