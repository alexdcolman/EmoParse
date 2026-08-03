#!/usr/bin/env python3
"""Prepara y verifica el smoke test multigénero VAL-01.

El script no ejecuta modelos. Construye corpus mínimos y una configuración
aislada; después de los tres ``emoparse run`` inspecciona bases y exportaciones
y escribe un reporte reproducible.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import sqlite3
import sys
import unicodedata
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

DEFAULT_WORKSPACE = Path(".build/val01")


@dataclass(frozen=True, slots=True)
class RunSpec:
    key: str
    genre_id: str
    expected_discursos: int
    expected_stages: tuple[str, ...]


RUN_SPECS: tuple[RunSpec, ...] = (
    RunSpec(
        key="articulo",
        genre_id="articulo_periodistico",
        expected_discursos=1,
        expected_stages=(
            "summarizer",
            "metadata",
            "enunciation",
            "emotions",
            "explode_emotions",
            "normalize_emotions",
            "characterizer",
        ),
    ),
    RunSpec(
        key="discurso",
        genre_id="discurso_presidencial",
        expected_discursos=1,
        expected_stages=(
            "summarizer",
            "metadata",
            "enunciation",
            "emotions",
            "explode_emotions",
            "normalize_emotions",
            "characterizer",
        ),
    ),
    RunSpec(
        key="posts",
        genre_id="tuit",
        expected_discursos=5,
        expected_stages=(
            "technoparse",
            "emoji_affect",
            "metadata",
            "enunciation",
            "emotions",
            "explode_emotions",
            "normalize_emotions",
            "characterizer",
        ),
    ),
)


class Val01Error(RuntimeError):
    """Error recuperable de preparación o verificación de VAL-01."""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_csv_rows(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as stream:
            reader = csv.DictReader(stream)
            if reader.fieldnames is None:
                raise Val01Error(f"CSV sin encabezado: {path}")
            return list(reader.fieldnames), [dict(row) for row in reader]
    except OSError as exc:
        raise Val01Error(f"No pude leer {path}: {exc}") from exc


def _write_csv(path: Path, fieldnames: Iterable[str], rows: Iterable[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    names = list(fieldnames)
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=names, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({name: row.get(name, "") for name in names})


def _normalize_inline(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _clip_sentences(text: str, limit: int) -> str:
    clean = _normalize_inline(text)
    if not clean:
        return ""
    parts = re.split(r"(?<=[.!?])\s+(?=[A-ZÁÉÍÓÚÜÑ¿¡])", clean)
    selected = parts[:limit]
    clipped = " ".join(selected).strip()
    if len(clipped) < 500 and len(parts) > limit:
        for part in parts[limit:]:
            selected.append(part)
            clipped = " ".join(selected).strip()
            if len(clipped) >= 500:
                break
    return clipped[:3500].rstrip()


def _clip_paragraphs(text: str, limit: int) -> str:
    paragraphs = [
        _normalize_inline(part) for part in re.split(r"\n\s*\n", text) if _normalize_inline(part)
    ]
    if len(paragraphs) < 2:
        sentences = re.split(
            r"(?<=[.!?])\s+(?=[A-ZÁÉÍÓÚÜÑ¿¡])",
            _normalize_inline(text),
        )
        paragraphs = [
            " ".join(sentences[index : index + 2]).strip()
            for index in range(0, len(sentences), 2)
            if " ".join(sentences[index : index + 2]).strip()
        ]
    selected = paragraphs[:limit]
    while len("\n\n".join(selected)) < 600 and len(selected) < len(paragraphs):
        selected.append(paragraphs[len(selected)])
    return "\n\n".join(selected)[:4500].rstrip()


def _fold(text: str) -> str:
    normalized = unicodedata.normalize("NFKD", text.casefold())
    return "".join(character for character in normalized if not unicodedata.combining(character))


def _is_pagina12_row(row: dict[str, str]) -> bool:
    source = _fold(str(row.get("fuente") or row.get("medio") or "")).replace("/", "")
    url = _fold(str(row.get("url") or ""))
    return "pagina12" in source or "pagina12.com.ar" in url


def find_article_csv(data_dir: Path) -> Path | None:
    """Devuelve el primer CSV con al menos una fila de Página/12."""
    for path in sorted(data_dir.rglob("*.csv")):
        try:
            _, rows = _read_csv_rows(path)
        except Val01Error:
            continue
        if any(_is_pagina12_row(row) and str(row.get("contenido") or "").strip() for row in rows):
            return path
    return None


def _select_row(rows: list[dict[str, str]], *, label: str, predicate: Any = None) -> dict[str, str]:
    for row in rows:
        if predicate is not None and not predicate(row):
            continue
        if str(row.get("contenido") or "").strip():
            return dict(row)
    raise Val01Error(f"No encontré una fila utilizable en el corpus de {label}.")


def _prepare_config(config_path: Path, output: Path, model_alias: str, workspace: Path) -> None:
    try:
        raw = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise Val01Error(f"No pude leer {config_path}: {exc}") from exc
    except yaml.YAMLError as exc:
        raise Val01Error(f"YAML inválido en {config_path}: {exc}") from exc
    if not isinstance(raw, dict):
        raise Val01Error(f"El config debe ser un mapping YAML: {config_path}")

    models = raw.get("models")
    if not isinstance(models, dict) or model_alias not in models:
        available = ", ".join(sorted(models)) if isinstance(models, dict) else "ninguno"
        raise Val01Error(
            f"El alias '{model_alias}' no existe en {config_path}. Disponibles: {available}"
        )

    pipeline = raw.setdefault("pipeline", {})
    if not isinstance(pipeline, dict):
        raise Val01Error("pipeline debe ser un mapping en el config.")
    stages = pipeline.setdefault("stages", {})
    if not isinstance(stages, dict):
        raise Val01Error("pipeline.stages debe ser un mapping en el config.")
    for stage in tuple(stages):
        stages[stage] = model_alias
    pipeline["cache_enabled"] = True
    pipeline["parallel"] = 1

    paths = raw.setdefault("paths", {})
    if not isinstance(paths, dict):
        raise Val01Error("paths debe ser un mapping en el config.")
    paths["runs_dir"] = str((workspace / "runs").resolve())

    raw["notes"] = (
        "VAL-01: smoke test multigénero con un artículo, un discurso y cinco posts. "
        f"Modelo único: {model_alias}."
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        yaml.safe_dump(raw, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )


def _prepare_article(source: Path, output: Path, paragraphs: int) -> str:
    fields, rows = _read_csv_rows(source)
    row = _select_row(rows, label="artículo", predicate=_is_pagina12_row)
    row["contenido"] = _clip_paragraphs(str(row["contenido"]), paragraphs)
    if len(row["contenido"]) < 200:
        raise Val01Error("El artículo preparado quedó demasiado corto.")
    original_code = str(row.get("codigo") or "pagina12")
    row["codigo"] = f"{original_code}_val01"
    _write_csv(output, fields, [row])
    return row["codigo"]


def _prepare_discourse(source: Path, output: Path, sentences: int) -> str:
    fields, rows = _read_csv_rows(source)
    row = _select_row(rows, label="discurso")
    row["contenido"] = _clip_sentences(str(row["contenido"]), sentences)
    if len(row["contenido"]) < 200:
        raise Val01Error("El discurso preparado quedó demasiado corto.")
    original_code = str(row.get("codigo") or "discurso")
    row["codigo"] = f"{original_code}_val01"
    _write_csv(output, fields, [row])
    return row["codigo"]


def _prepare_posts(source: Path, output: Path, count: int) -> list[str]:
    selected: list[dict[str, Any]] = []
    try:
        with source.open("r", encoding="utf-8") as stream:
            for line_number, line in enumerate(stream, start=1):
                if not line.strip():
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise Val01Error(
                        f"JSONL inválido en {source}, línea {line_number}: {exc}"
                    ) from exc
                if isinstance(row, dict) and str(row.get("texto") or "").strip():
                    selected.append(row)
                if len(selected) >= count:
                    break
    except OSError as exc:
        raise Val01Error(f"No pude leer {source}: {exc}") from exc

    if len(selected) < count:
        raise Val01Error(f"{source} contiene {len(selected)} posts utilizables; necesito {count}.")
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8") as stream:
        for row in selected:
            stream.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")
    return [str(row.get("id") or "") for row in selected]


def prepare(args: argparse.Namespace) -> int:
    workspace = args.workspace.resolve()
    input_dir = workspace / "inputs"
    run_dir = workspace / "runs"
    export_dir = workspace / "exports"
    for path in (input_dir, run_dir, export_dir):
        path.mkdir(parents=True, exist_ok=True)

    config_out = workspace / "config.val01.yaml"
    article_out = input_dir / "articulo.csv"
    discourse_out = input_dir / "discurso.csv"
    posts_out = input_dir / "posts.jsonl"

    _prepare_config(args.config.resolve(), config_out, args.model_alias, workspace)
    article_code = _prepare_article(
        args.article_source.resolve(), article_out, args.article_paragraphs
    )
    discourse_code = _prepare_discourse(
        args.discourse_source.resolve(), discourse_out, args.discourse_sentences
    )
    post_ids = _prepare_posts(args.posts_source.resolve(), posts_out, args.posts)

    manifest = {
        "val01_version": 1,
        "generated_at": datetime.now(UTC).isoformat(),
        "model_alias": args.model_alias,
        "config_source": str(args.config.resolve()),
        "sources": {
            "articulo": {
                "path": str(args.article_source.resolve()),
                "sha256": _sha256(args.article_source.resolve()),
            },
            "discurso": {
                "path": str(args.discourse_source.resolve()),
                "sha256": _sha256(args.discourse_source.resolve()),
            },
            "posts": {
                "path": str(args.posts_source.resolve()),
                "sha256": _sha256(args.posts_source.resolve()),
            },
        },
        "prepared": {
            "articulo": {
                "path": str(article_out),
                "codigo": article_code,
                "sha256": _sha256(article_out),
            },
            "discurso": {
                "path": str(discourse_out),
                "codigo": discourse_code,
                "sha256": _sha256(discourse_out),
            },
            "posts": {"path": str(posts_out), "ids": post_ids, "sha256": _sha256(posts_out)},
        },
    }
    manifest_path = workspace / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"VAL-01 preparado en: {workspace}")
    print(f"Modelo: {args.model_alias}")
    print(f"Artículo:  {article_code}")
    print(f"Discurso:  {discourse_code}")
    print(f"Posts:     {len(post_ids)}")
    print(f"Manifest:  {manifest_path}")
    return 0


def _table_exists(connection: sqlite3.Connection, table: str) -> bool:
    row = connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
    ).fetchone()
    return row is not None


def _count_csv(path: Path) -> int:
    if not path.is_file():
        raise Val01Error(f"Exportación ausente: {path}")
    with path.open("r", encoding="utf-8-sig", newline="") as stream:
        return sum(1 for _ in csv.DictReader(stream))


def _latest_metrics(connection: sqlite3.Connection) -> dict[str, sqlite3.Row]:
    rows = connection.execute(
        """
        SELECT m.*
        FROM run_metrics AS m
        JOIN (
            SELECT stage_name, MAX(recorded_at) AS recorded_at
            FROM run_metrics
            GROUP BY stage_name
        ) AS latest
          ON latest.stage_name = m.stage_name
         AND latest.recorded_at = m.recorded_at
        """
    ).fetchall()
    return {str(row["stage_name"]): row for row in rows}


def _count_errors(connection: sqlite3.Connection) -> int:
    checks = (
        ("discursos", ("summarizer_error", "metadata_error", "enunciation_error")),
        ("frases", ("actores_error", "emociones_error", "emociones_pass2_error")),
        ("emociones", ("caracterizacion_error", "actantes_error")),
        ("judgments", ("judge_error",)),
    )
    total = 0
    for table, columns in checks:
        if not _table_exists(connection, table):
            continue
        available = {
            str(row[1]) for row in connection.execute(f"PRAGMA table_info({table})").fetchall()
        }
        selected = [column for column in columns if column in available]
        if not selected:
            continue
        where = " OR ".join(
            f"({column} IS NOT NULL AND TRIM({column}) <> '')" for column in selected
        )
        total += int(
            connection.execute(f"SELECT COUNT(*) FROM {table} WHERE {where}").fetchone()[0]
        )
    return total


def _inspect_run(
    workspace: Path, spec: RunSpec, model_alias: str
) -> tuple[list[str], list[str], dict[str, Any]]:
    errors: list[str] = []
    warnings: list[str] = []
    details: dict[str, Any] = {}
    db_path = workspace / "runs" / f"{spec.key}.sqlite"
    export_dir = workspace / "exports" / spec.key
    if not db_path.is_file():
        return [f"{spec.key}: falta {db_path}"], warnings, details

    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row
    try:
        run_row = connection.execute("SELECT * FROM runs LIMIT 1").fetchone()
        if run_row is None:
            errors.append(f"{spec.key}: la DB no contiene una fila en runs")
        else:
            details["run_id"] = run_row["run_id"]
            details["status"] = run_row["status"]
            if run_row["status"] != "completed":
                errors.append(f"{spec.key}: run.status={run_row['status']!r}")
            try:
                config = json.loads(run_row["config"] or "{}")
            except json.JSONDecodeError:
                config = {}
                errors.append(f"{spec.key}: runs.config no es JSON válido")
            genre_id = (
                config.get("_emoparse", {}).get("genre", {}).get("genre_id")
                if isinstance(config, dict)
                else None
            )
            details["genre_id"] = genre_id
            if genre_id != spec.genre_id:
                errors.append(
                    f"{spec.key}: género persistido {genre_id!r}; esperaba {spec.genre_id!r}"
                )

        discourse_count = int(connection.execute("SELECT COUNT(*) FROM discursos").fetchone()[0])
        phrase_count = int(connection.execute("SELECT COUNT(*) FROM frases").fetchone()[0])
        emotion_count = int(connection.execute("SELECT COUNT(*) FROM emociones").fetchone()[0])
        details.update(
            discursos=discourse_count,
            unidades=phrase_count,
            emociones=emotion_count,
        )
        if discourse_count != spec.expected_discursos:
            errors.append(
                f"{spec.key}: {discourse_count} discursos/posts persistidos; "
                f"esperaba {spec.expected_discursos}"
            )
        if phrase_count == 0:
            errors.append(f"{spec.key}: no se persistieron unidades textuales")
        if emotion_count == 0:
            warnings.append(
                f"{spec.key}: no se detectaron emociones; revisar manualmente la salida"
            )

        error_count = _count_errors(connection)
        details["filas_con_error"] = error_count
        if error_count:
            errors.append(f"{spec.key}: hay {error_count} filas con errores persistidos")

        metrics = _latest_metrics(connection)
        details["stages"] = sorted(metrics)
        for stage in spec.expected_stages:
            row = metrics.get(stage)
            if row is None:
                errors.append(f"{spec.key}: falta métrica de la stage {stage}")
                continue
            if int(row["n_items_failed"] or 0) != 0:
                errors.append(f"{spec.key}: {stage} registró {int(row['n_items_failed'])} fallos")
        for stage in ("metadata", "enunciation", "emotions"):
            row = metrics.get(stage)
            if row is not None and int(row["n_items_ok"] or 0) == 0:
                errors.append(f"{spec.key}: {stage} no completó ningún ítem")
        if spec.genre_id != "tuit":
            row = metrics.get("summarizer")
            if row is not None and int(row["n_items_ok"] or 0) == 0:
                errors.append(f"{spec.key}: summarizer no completó ningún ítem")

        aliases = []
        if _table_exists(connection, "llm_cache"):
            aliases = [
                str(row[0])
                for row in connection.execute(
                    "SELECT DISTINCT model_alias FROM llm_cache ORDER BY model_alias"
                ).fetchall()
                if row[0]
            ]
        details["model_aliases"] = aliases
        foreign_aliases = [alias for alias in aliases if alias != model_alias]
        if foreign_aliases:
            errors.append(
                f"{spec.key}: aparecen modelos ajenos al smoke: {', '.join(foreign_aliases)}"
            )
        if not aliases:
            warnings.append(f"{spec.key}: llm_cache no registra alias de modelo")
    finally:
        connection.close()

    try:
        export_counts = {
            name: _count_csv(export_dir / name)
            for name in (
                "discursos.csv",
                "metadata_genero.csv",
                "frases.csv",
                "emociones.csv",
            )
        }
        details["exports"] = export_counts
        if export_counts["discursos.csv"] != spec.expected_discursos:
            errors.append(
                f"{spec.key}: discursos.csv tiene {export_counts['discursos.csv']} filas; "
                f"esperaba {spec.expected_discursos}"
            )
        if export_counts["frases.csv"] == 0:
            errors.append(f"{spec.key}: frases.csv quedó vacío")
        if spec.genre_id == "articulo_periodistico" and export_counts["metadata_genero.csv"] != 8:
            errors.append(
                f"{spec.key}: metadata_genero.csv tiene "
                f"{export_counts['metadata_genero.csv']} filas; esperaba 8"
            )
    except Val01Error as exc:
        errors.append(str(exc))

    return errors, warnings, details


def inspect_workspace(workspace: Path) -> tuple[bool, str]:
    manifest_path = workspace / "manifest.json"
    if not manifest_path.is_file():
        raise Val01Error(f"Falta el manifest: {manifest_path}")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise Val01Error(f"No pude leer {manifest_path}: {exc}") from exc
    model_alias = str(manifest.get("model_alias") or "")
    if not model_alias:
        raise Val01Error("manifest.json no declara model_alias.")

    all_errors: list[str] = []
    all_warnings: list[str] = []
    run_details: dict[str, Any] = {}
    for spec in RUN_SPECS:
        errors, warnings, details = _inspect_run(workspace, spec, model_alias)
        all_errors.extend(errors)
        all_warnings.extend(warnings)
        run_details[spec.key] = details

    lines = [
        "# Reporte VAL-01 · smoke test multigénero",
        "",
        f"- Fecha de verificación: {datetime.now(UTC).isoformat()}",
        f"- Modelo: `{model_alias}`",
        f"- Estado: **{'APROBADO' if not all_errors else 'FALLIDO'}**",
        "",
        "## Runs",
        "",
        "| Corpus | Género | Estado | Discursos/posts | Unidades | Emociones | Errores |",
        "|---|---|---:|---:|---:|---:|---:|",
    ]
    for spec in RUN_SPECS:
        details = run_details.get(spec.key, {})
        lines.append(
            "| {key} | {genre} | {status} | {discursos} | {unidades} | {emociones} | {errors} |".format(
                key=spec.key,
                genre=details.get("genre_id", "—"),
                status=details.get("status", "—"),
                discursos=details.get("discursos", "—"),
                unidades=details.get("unidades", "—"),
                emociones=details.get("emociones", "—"),
                errors=details.get("filas_con_error", "—"),
            )
        )

    lines.extend(["", "## Exportaciones", ""])
    for spec in RUN_SPECS:
        exports = run_details.get(spec.key, {}).get("exports", {})
        rendered = ", ".join(f"{name}: {count}" for name, count in exports.items()) or "ausentes"
        lines.append(f"- **{spec.key}**: {rendered}")

    lines.extend(["", "## Modelos observados", ""])
    for spec in RUN_SPECS:
        aliases = run_details.get(spec.key, {}).get("model_aliases", [])
        lines.append(f"- **{spec.key}**: {', '.join(aliases) if aliases else 'sin registro'}")

    lines.extend(["", "## Errores", ""])
    lines.extend(f"- {error}" for error in all_errors)
    if not all_errors:
        lines.append("- Ninguno.")
    lines.extend(["", "## Advertencias", ""])
    lines.extend(f"- {warning}" for warning in all_warnings)
    if not all_warnings:
        lines.append("- Ninguna.")

    report = "\n".join(lines) + "\n"
    return not all_errors, report


def check(args: argparse.Namespace) -> int:
    workspace = args.workspace.resolve()
    ok, report = inspect_workspace(workspace)
    report_path = workspace / "REPORTE_VAL01.md"
    report_path.write_text(report, encoding="utf-8")
    print(report)
    print(f"Reporte guardado en: {report_path}")
    return 0 if ok else 1


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    find_parser = subparsers.add_parser(
        "find-article",
        help="Busca bajo data/ un CSV existente con una fila de Página/12.",
    )
    find_parser.add_argument("--data-dir", type=Path, default=Path("data"))

    prepare_parser = subparsers.add_parser(
        "prepare",
        help="Genera config, corpus mínimos y manifest de VAL-01.",
    )
    prepare_parser.add_argument("--config", type=Path, default=Path("config.yaml"))
    prepare_parser.add_argument("--model-alias", required=True)
    prepare_parser.add_argument("--article-source", type=Path, required=True)
    prepare_parser.add_argument(
        "--discourse-source", type=Path, default=Path("data/casarosada_3.csv")
    )
    prepare_parser.add_argument("--posts-source", type=Path, default=Path("data/bluesky_4.jsonl"))
    prepare_parser.add_argument("--workspace", type=Path, default=DEFAULT_WORKSPACE)
    prepare_parser.add_argument("--article-paragraphs", type=int, default=4)
    prepare_parser.add_argument("--discourse-sentences", type=int, default=6)
    prepare_parser.add_argument("--posts", type=int, default=5)

    check_parser = subparsers.add_parser(
        "check",
        help="Verifica las tres DB, exportaciones y escribe REPORTE_VAL01.md.",
    )
    check_parser.add_argument("--workspace", type=Path, default=DEFAULT_WORKSPACE)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "find-article":
            path = find_article_csv(args.data_dir.resolve())
            if path is None:
                return 1
            print(path)
            return 0
        if args.command == "prepare":
            if args.posts < 1:
                raise Val01Error("--posts debe ser mayor que cero.")
            if args.article_paragraphs < 1 or args.discourse_sentences < 1:
                raise Val01Error("Los límites de texto deben ser mayores que cero.")
            return prepare(args)
        if args.command == "check":
            return check(args)
    except Val01Error as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    parser.error(f"Comando no implementado: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
