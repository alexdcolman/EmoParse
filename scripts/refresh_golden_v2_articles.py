#!/usr/bin/env python3
"""Reextrae y reemplaza de forma transaccional el corpus periodístico del golden v2."""

from __future__ import annotations

import argparse
import csv
import os
import shutil
import subprocess
import sys
from collections.abc import Iterable
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Protocol

from emoparse.acquisition.sources.pagina12 import Pagina12Adapter
from emoparse.evaluation.corpus_validation import (
    CorpusValidationError,
    summarize_prepared_corpus,
    validate_golden_v2_corpus,
)


class RefreshError(RuntimeError):
    """La reparación no pudo producir un corpus periodístico válido."""


class ArticleRecord(Protocol):
    def to_dict(self) -> dict[str, object]: ...


class ArticleAdapter(Protocol):
    def fetch_discurso(self, url: str) -> ArticleRecord | None: ...

    def list_discursos(self, *, max_items: int | None = None) -> Iterable[str]: ...


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=Path("config.yaml"))
    parser.add_argument(
        "--corpus",
        type=Path,
        default=Path("data/golden_v2/source/articulo_periodistico.csv"),
    )
    parser.add_argument(
        "--db",
        type=Path,
        default=Path("runs/golden_v2/articulo_periodistico.sqlite"),
    )
    parser.add_argument("--run-id", default="golden_v2_articulo_periodistico")
    parser.add_argument("--min-units", type=int, default=80)
    parser.add_argument("--max-documents", type=int, default=30)
    parser.add_argument("--discovery-limit", type=int, default=60)
    parser.add_argument("--emoparse-bin", default="emoparse")
    return parser


def paragraph_count(row: dict[str, str], *, min_chars: int = 30) -> int:
    """Estima las unidades por párrafo; la SQLite preparada se valida después."""
    text = row.get("contenido", "")
    if not text or not text.strip():
        return 0
    paragraphs = [part.strip() for part in text.split("\n\n") if part.strip()]
    if not paragraphs:
        return 1
    filtered = [part for part in paragraphs if len(part) >= min_chars]
    return len(filtered) if filtered else 1


def coverage(rows: Iterable[dict[str, str]]) -> tuple[int, int]:
    material = list(rows)
    return len(material), sum(paragraph_count(row) for row in material)


def refresh_rows(
    original_rows: list[dict[str, str]],
    *,
    adapter: ArticleAdapter,
    min_units: int,
    max_documents: int,
    discovery_limit: int,
) -> list[dict[str, str]]:
    """Reextrae URLs conocidas y agrega notas nuevas solo si faltan unidades."""
    if min_units < 1:
        raise RefreshError("--min-units debe ser mayor que cero")
    if max_documents < 15 or max_documents > 30:
        raise RefreshError("--max-documents debe estar entre 15 y 30")

    refreshed: list[dict[str, str]] = []
    seen: set[str] = set()

    def add_url(url: str) -> None:
        normalized = url.strip()
        if not normalized or normalized in seen or len(refreshed) >= max_documents:
            return
        seen.add(normalized)
        try:
            record = adapter.fetch_discurso(normalized)
        except Exception as error:
            print(
                f"ADVERTENCIA: no se pudo reextraer {normalized}: {error}",
                file=sys.stderr,
            )
            return
        if record is None:
            return
        refreshed.append(
            {key: "" if value is None else str(value) for key, value in record.to_dict().items()}
        )

    for row in original_rows:
        add_url(row.get("url", ""))

    documents, units = coverage(refreshed)
    if documents >= 15 and units >= min_units:
        return refreshed

    for url in adapter.list_discursos(max_items=discovery_limit):
        add_url(url)
        documents, units = coverage(refreshed)
        if documents >= 15 and units >= min_units:
            return refreshed
        if len(refreshed) >= max_documents:
            break

    documents, units = coverage(refreshed)
    raise RefreshError(
        "Página/12 no alcanzó la cobertura requerida después de la reextracción: "
        f"textos={documents}, unidades={units}, mínimo={min_units}, "
        f"máximo_textos={max_documents}"
    )


def read_csv(path: Path) -> list[dict[str, str]]:
    if not path.is_file():
        raise RefreshError(f"corpus no encontrado: {path}")
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return [dict(row) for row in csv.DictReader(handle)]


def write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    if not rows:
        raise RefreshError("no hay artículos para escribir")
    fields: list[str] = []
    for row in rows:
        fields.extend(key for key in row if key not in fields)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def run(command: list[str], cwd: Path) -> None:
    print("+ " + " ".join(command), flush=True)
    subprocess.run(command, cwd=cwd, check=True)


def replace_with_backup(
    *,
    project: Path,
    corpus: Path,
    db: Path,
    new_corpus: Path,
    new_db: Path,
) -> Path:
    """Reemplaza corpus y DB; restaura ambos si falla cualquier operación."""
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup = project / ".build" / "golden_v2" / f"article_refresh_{stamp}"
    backup.mkdir(parents=True, exist_ok=False)

    originals = [corpus, db, Path(f"{db}-wal"), Path(f"{db}-shm")]
    existed = {path: path.exists() for path in originals}
    for path in originals:
        if path.exists():
            shutil.copy2(path, backup / path.name)

    staged_corpus = corpus.with_suffix(corpus.suffix + ".refresh")
    staged_db = db.with_suffix(db.suffix + ".refresh")
    shutil.copy2(new_corpus, staged_corpus)
    shutil.copy2(new_db, staged_db)

    try:
        os.replace(staged_corpus, corpus)
        os.replace(staged_db, db)
        for sidecar in originals[2:]:
            sidecar.unlink(missing_ok=True)
    except Exception:
        staged_corpus.unlink(missing_ok=True)
        staged_db.unlink(missing_ok=True)
        for path in originals:
            saved = backup / path.name
            if existed[path] and saved.exists():
                shutil.copy2(saved, path)
            elif not existed[path]:
                path.unlink(missing_ok=True)
        raise
    return backup


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    project = Path.cwd().resolve()
    corpus = args.corpus.expanduser().resolve()
    db = args.db.expanduser().resolve()
    config = args.config.expanduser().resolve()

    if not config.is_file():
        print(f"ERROR: config no encontrado: {config}", file=sys.stderr)
        return 1

    try:
        original_rows = read_csv(corpus)
        old_documents, old_units = coverage(original_rows)
        print(f"Corpus actual: textos={old_documents}, párrafos_estimados={old_units}")

        with TemporaryDirectory(prefix="golden_v2_articles_") as temp_name:
            temp = Path(temp_name)
            new_corpus = temp / "articulo_periodistico.csv"
            new_db = temp / "articulo_periodistico.sqlite"

            adapter = Pagina12Adapter(mode="http")
            try:
                rows = refresh_rows(
                    original_rows,
                    adapter=adapter,
                    min_units=args.min_units,
                    max_documents=args.max_documents,
                    discovery_limit=args.discovery_limit,
                )
            finally:
                adapter.close()

            documents, estimated_units = coverage(rows)
            print(f"Corpus reextraído: textos={documents}, párrafos_estimados={estimated_units}")
            write_csv(new_corpus, rows)

            run(
                [
                    args.emoparse_bin,
                    "run",
                    "--config",
                    str(config),
                    "--input",
                    str(new_corpus),
                    "--genre",
                    "articulo_periodistico",
                    "--run-id",
                    args.run_id,
                    "--db",
                    str(new_db),
                    "--prepare-only",
                ],
                project,
            )

            summary = summarize_prepared_corpus(new_db)
            validate_golden_v2_corpus(
                summary,
                expected_genre="articulo_periodistico",
            )
            backup = replace_with_backup(
                project=project,
                corpus=corpus,
                db=db,
                new_corpus=new_corpus,
                new_db=new_db,
            )
    except (
        CorpusValidationError,
        OSError,
        RefreshError,
        subprocess.CalledProcessError,
    ) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1

    print("Corpus periodístico reparado sin ejecutar LLM.")
    print(f"Textos:   {summary.texts}")
    print(f"Unidades: {summary.units}")
    print(f"Corpus:   {corpus}")
    print(f"DB:       {db}")
    print(f"Respaldo: {backup}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
