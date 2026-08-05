# ══════════════════════════════════════════════════════════════════════════════
#  emoparse.cli.commands.eval_cmd
#
#  Subcomando `emoparse eval`: muestreo ciego, acuerdo y golden sets.
# ══════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

import argparse
import hashlib
import re
import sqlite3
from pathlib import Path
from typing import Any

import pandas as pd
from loguru import logger

from emoparse.evaluation.agreement import krippendorff_alpha
from emoparse.evaluation.annotations import (
    ANNOTATION_DECISION_COLUMNS,
    EMOTION_SLOTS,
    AnnotationError,
    coder_id,
    freeze_annotations,
    make_reannotation_sample,
    validate_annotation_decisions,
    write_golden_jsonl,
)
from emoparse.evaluation.golden import (
    GoldenDataset,
    GoldenError,
    load_golden_dataset,
    load_run_emotions,
    load_run_genre,
)
from emoparse.evaluation.matching import DIMENSIONES, MatchReport, match_units
from emoparse.evaluation.sampling import make_annotation_sample
from emoparse.storage.db import Database
from emoparse.storage.eval_reports import EvalReportsRepository
from emoparse.storage.runs import RunsRepository

_AGREEMENT_DIMENSIONS: tuple[tuple[str, str, str], ...] = (
    ("hay_emocion", "hay_emocion", "nominal"),
    ("tipo", "tipo", "nominal"),
    ("experienciador", "experienciador", "nominal"),
    ("fuente", "fuente", "nominal"),
    ("modo_existencia", "modo_existencia", "nominal"),
    ("foria", "foria", "nominal"),
)


def register(subparsers: argparse._SubParsersAction) -> None:
    """Registra `eval` como subcomando en el CLI principal."""
    parser = subparsers.add_parser(
        "eval",
        help="Evaluación de validez: muestras, acuerdo, golden sets y controles.",
        description="Evaluación humana y regresión semántica del análisis emocional.",
    )
    parser.add_argument(
        "--db",
        type=Path,
        action="append",
        default=None,
        help=(
            "DB del run. Puede repetirse con --golden --por-genero; los otros modos "
            "requieren una sola."
        ),
    )
    parser.add_argument(
        "--golden", type=Path, default=None, help="Golden set (.jsonl o directorio de .jsonl)."
    )
    parser.add_argument(
        "--por-genero",
        action="store_true",
        help="Separa el reporte del golden por género y admite un --db por género.",
    )
    parser.add_argument(
        "--persist-report",
        action="store_true",
        help=(
            "Persiste el reporte estructurado en la tabla eval_reports de cada run. "
            "Disponible para --golden y --control."
        ),
    )
    parser.add_argument(
        "--golden-version",
        default=None,
        help="Versión legible del golden persistido; se infiere de una ruta como golden/v2.",
    )
    parser.add_argument(
        "--make-sample", action="store_true", help="Exporta planilla de anotación a ciegas (--out)."
    )
    parser.add_argument(
        "--make-retest",
        type=Path,
        default=None,
        help="Extrae una segunda pasada ciega desde una planilla completa (--out).",
    )
    parser.add_argument(
        "--freeze-sample",
        type=Path,
        default=None,
        help="Congela una planilla completa como golden JSONL v2 (--out).",
    )
    parser.add_argument(
        "--n", type=int, default=200, help="Tamaño de la muestra (200 por defecto)."
    )
    parser.add_argument("--seed", type=int, default=42, help="Seed del muestreo reproducible.")
    parser.add_argument(
        "--min-textos",
        type=int,
        default=1,
        help="Cantidad mínima de textos distintos exigida al crear la muestra.",
    )
    parser.add_argument(
        "--max-por-texto",
        type=int,
        default=None,
        help="Máximo de unidades tomadas de un mismo texto.",
    )
    parser.add_argument(
        "--genero",
        default=None,
        help="Género explícito para runs antiguos o para congelar una planilla sin metadata.",
    )
    parser.add_argument(
        "--anotador",
        default=None,
        help="Sobrescribe `anotador` en todas las filas al congelar el golden.",
    )
    parser.add_argument(
        "--pasada",
        type=int,
        default=None,
        help="Sobrescribe `pasada` en todas las filas al congelar el golden.",
    )
    parser.add_argument(
        "--fecha",
        default=None,
        help="Sobrescribe `fecha_anotacion` (AAAA-MM-DD) al congelar el golden.",
    )
    parser.add_argument(
        "--agreement",
        type=Path,
        default=None,
        help=("CSV concatenado con `anotador`, `pasada`, `id_muestra` y columnas de anotación."),
    )
    parser.add_argument(
        "--control",
        action="store_true",
        help="Reporta la tasa de detección del run sobre un corpus de control.",
    )
    parser.add_argument(
        "--out", type=Path, default=None, help="Archivo de salida (.md, .csv o .jsonl)."
    )
    parser.set_defaults(handler=run)


def run(args: argparse.Namespace) -> int:
    """Ejecuta el subcomando. Devuelve exit code (0 = ok)."""
    if args.make_sample:
        return _make_sample(args)
    if args.make_retest is not None:
        return _make_retest(args)
    if args.freeze_sample is not None:
        return _freeze_sample(args)
    if args.agreement is not None:
        return _agreement(args)
    if args.golden is not None:
        return _golden(args)
    if args.control:
        return _control(args)
    logger.error(
        "[eval] Indicá un modo: --golden, --make-sample, --make-retest, "
        "--freeze-sample, --agreement o --control."
    )
    return 1


def _golden(args: argparse.Namespace) -> int:
    db_paths = _db_paths(args)
    if not db_paths:
        logger.error("[eval] --golden requiere al menos un --db.")
        return 1
    try:
        dataset = load_golden_dataset(args.golden)
    except GoldenError as exc:
        logger.error(f"[eval] {exc}")
        return 1

    if args.por_genero:
        return _golden_by_genre(dataset, db_paths, args)
    if len(db_paths) != 1:
        logger.error("[eval] Varios --db requieren --por-genero.")
        return 1
    if len(dataset.genres_present()) > 1:
        logger.error(
            "[eval] El golden contiene varios géneros; repetí --db por género y usá --por-genero."
        )
        return 1

    db_path = db_paths[0]
    declared_genres = dataset.genres_present()
    try:
        run_genre = load_run_genre(db_path)
        predictions = load_run_emotions(db_path, keys=set(dataset.units))
    except sqlite3.Error as exc:
        logger.error(f"[eval] No se pudo leer {db_path}: {exc}")
        return 1
    if declared_genres and run_genre and declared_genres[0] != run_genre:
        logger.error(
            f"[eval] El golden declara `{declared_genres[0]}` pero el run es `{run_genre}`."
        )
        return 1
    report = match_units(dataset.units, predictions)
    markdown = _golden_markdown(report, title=db_path.name)
    if getattr(args, "persist_report", False):
        try:
            _persist_golden_report(
                db_path=db_path,
                golden_path=args.golden,
                explicit_version=getattr(args, "golden_version", None),
                genre=run_genre or (declared_genres[0] if declared_genres else None),
                report=report,
            )
        except (OSError, RuntimeError, sqlite3.Error) as exc:
            logger.error(f"[eval] No se pudo persistir el reporte: {exc}")
            return 1
    _emit_markdown(markdown, args.out)
    return 0


def _golden_by_genre(
    dataset: GoldenDataset,
    db_paths: list[Path],
    args: argparse.Namespace,
) -> int:
    reports: dict[str, tuple[Path, MatchReport]] = {}
    for db_path in db_paths:
        try:
            genre = load_run_genre(db_path)
        except sqlite3.Error as exc:
            logger.error(f"[eval] No se pudo leer {db_path}: {exc}")
            return 1
        if not genre:
            logger.error(
                f"[eval] {db_path}: el run no conserva género; --por-genero requiere esa metadata."
            )
            return 1
        if genre in reports:
            logger.error(f"[eval] Se recibió más de un --db para el género `{genre}`.")
            return 1
        units = dataset.units_for_genre(genre)
        if not units:
            logger.error(f"[eval] El golden no contiene unidades del género `{genre}`.")
            return 1
        try:
            predictions = load_run_emotions(db_path, keys=set(units))
        except sqlite3.Error as exc:
            logger.error(f"[eval] No se pudo leer {db_path}: {exc}")
            return 1
        reports[genre] = (db_path, match_units(units, predictions))

    missing = sorted(set(dataset.genres_present()) - set(reports))
    if missing:
        logger.error("[eval] Faltan DB para los géneros del golden: " + ", ".join(missing))
        return 1
    if any(genre is None for genre in dataset.genres.values()):
        logger.error("[eval] --por-genero requiere `genero` en todas las unidades del golden.")
        return 1

    total = MatchReport()
    for _, report in reports.values():
        total.merge(report)
    markdown = _golden_markdown(total, title="comparación multigénero", genre_reports=reports)
    if getattr(args, "persist_report", False):
        try:
            for genre, (db_path, report) in reports.items():
                _persist_golden_report(
                    db_path=db_path,
                    golden_path=args.golden,
                    explicit_version=getattr(args, "golden_version", None),
                    genre=genre,
                    report=report,
                    aggregate=total,
                )
        except (OSError, RuntimeError, sqlite3.Error) as exc:
            logger.error(f"[eval] No se pudo persistir el reporte: {exc}")
            return 1
    _emit_markdown(markdown, args.out)
    return 0


def _golden_markdown(
    report: MatchReport,
    *,
    title: str,
    genre_reports: dict[str, tuple[Path, MatchReport]] | None = None,
) -> str:
    lines = [f"# Evaluación contra golden — {title}", ""]
    if genre_reports:
        lines += _report_section(report, heading="## Resultado agregado")
        for genre in sorted(genre_reports):
            db_path, genre_report = genre_reports[genre]
            lines += ["", f"## Género: `{genre}`", "", f"Run: `{db_path.name}`", ""]
            lines += _report_section(genre_report, heading=None)
    else:
        lines += _report_section(report, heading=None)
    return "\n".join(lines).rstrip() + "\n"


def _report_section(report: MatchReport, heading: str | None) -> list[str]:
    lines: list[str] = []
    if heading:
        lines += [heading, ""]
    lines += [
        f"Unidades evaluadas: {report.unidades}",
        "",
        "### Detección de emociones",
        "",
        "| métrica | valor |",
        "|---|---|",
        f"| TP / FP / FN | {report.tp} / {report.fp} / {report.fn} |",
        f"| Precisión | {_fmt(report.precision)} |",
        f"| Recall | {_fmt(report.recall)} |",
        f"| F1 | {_fmt(report.f1)} |",
        "",
        "### Accuracy por dimensión (sobre pares emparejados)",
        "",
        "| dimensión | correctas / evaluadas | accuracy |",
        "|---|---|---|",
    ]
    for dimension in DIMENSIONES:
        evaluated = report.dim_evaluadas.get(dimension, 0)
        correct = report.dim_correctas.get(dimension, 0)
        lines.append(
            f"| {dimension} | {correct} / {evaluated} | {_fmt(report.dim_accuracy(dimension))} |"
        )
    if report.desacuerdos:
        lines += ["", "### Desacuerdos (muestra)", ""]
        for disagreement in report.desacuerdos[:30]:
            lines.append(
                f"- `{disagreement['codigo']}`[{disagreement['unit_idx']}] "
                f"{disagreement['dimension']}: golden={disagreement['golden']!r} "
                f"vs pred={disagreement['prediccion']!r}"
            )
    return lines


def _make_sample(args: argparse.Namespace) -> int:
    db_path = _single_db(args, "--make-sample")
    if db_path is None or args.out is None:
        if args.out is None:
            logger.error("[eval] --make-sample requiere --out (.csv).")
        return 1
    try:
        frame = make_annotation_sample(
            db_path,
            n=args.n,
            seed=args.seed,
            min_texts=args.min_textos,
            max_per_text=args.max_por_texto,
            genre_override=args.genero,
        )
    except (ValueError, OSError, sqlite3.Error) as exc:
        logger.error(f"[eval] No se pudo crear la muestra: {exc}")
        return 1
    args.out.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(args.out, index=False, encoding="utf-8")
    logger.info(
        f"[eval] Planilla ciega de {len(frame)} unidades → {args.out}. "
        "Consigna: evals/manual_anotacion.md."
    )
    return 0


def _make_retest(args: argparse.Namespace) -> int:
    if args.out is None:
        logger.error("[eval] --make-retest requiere --out (.csv).")
        return 1
    try:
        frame = make_reannotation_sample(args.make_retest, n=args.n, seed=args.seed)
    except AnnotationError as exc:
        logger.error(f"[eval] {exc}")
        return 1
    args.out.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(args.out, index=False, encoding="utf-8")
    logger.info(f"[eval] Segunda pasada ciega de {len(frame)} unidades → {args.out}")
    return 0


def _freeze_sample(args: argparse.Namespace) -> int:
    if args.out is None:
        logger.error("[eval] --freeze-sample requiere --out (.jsonl).")
        return 1
    try:
        records = freeze_annotations(
            args.freeze_sample,
            annotator=args.anotador,
            pass_number=args.pasada,
            annotation_date=args.fecha,
            genre_override=args.genero,
        )
        write_golden_jsonl(records, args.out)
    except AnnotationError as exc:
        logger.error(f"[eval] {exc}")
        return 1
    logger.info(f"[eval] Golden congelado: {len(records)} unidades → {args.out}")
    return 0


def _agreement(args: argparse.Namespace) -> int:
    try:
        frame = pd.read_csv(args.agreement, dtype=str, keep_default_na=False)
    except (OSError, pd.errors.ParserError) as exc:
        logger.error(f"[eval] CSV de acuerdo ilegible: {exc}")
        return 1
    required = {"anotador", "pasada", "id_muestra", *ANNOTATION_DECISION_COLUMNS}
    missing = sorted(required - set(frame.columns))
    if missing:
        logger.error("[eval] Faltan columnas para acuerdo: " + ", ".join(missing))
        return 1
    try:
        validate_annotation_decisions(frame)
    except AnnotationError as exc:
        logger.error(f"[eval] Planilla de acuerdo inválida: {exc}")
        return 1

    rows = frame.to_dict(orient="records")
    for row in rows:
        row["_coder"] = coder_id(row)
    if any(not str(row.get("anotador") or "").strip() for row in rows):
        logger.error("[eval] `anotador` no puede quedar vacío.")
        return 1
    if any(not str(row.get("pasada") or "").strip() for row in rows):
        logger.error("[eval] `pasada` no puede quedar vacía.")
        return 1
    if any(not str(row.get("id_muestra") or "").strip() for row in rows):
        logger.error("[eval] `id_muestra` no puede quedar vacío.")
        return 1
    duplicate = frame.assign(_coder=[row["_coder"] for row in rows]).duplicated(
        subset=["_coder", "id_muestra"]
    )
    if duplicate.any():
        logger.error("[eval] Hay unidades duplicadas para un mismo anotador/pasada.")
        return 1

    coders = sorted({str(row["_coder"]) for row in rows})
    units = sorted({str(row.get("id_muestra") or "") for row in rows if row.get("id_muestra")})
    if len(coders) < 2:
        logger.error("[eval] El acuerdo requiere al menos dos anotadores o pasadas.")
        return 1
    index = {(str(row["_coder"]), str(row["id_muestra"])): row for row in rows}

    lines = [
        "# Acuerdo de anotación (alpha de Krippendorff)",
        "",
        f"Codificadores: {len(coders)} ({', '.join(coders)}) — Unidades: {len(units)}",
        "",
        "| dimensión | métrica | alpha |",
        "|---|---|---|",
    ]
    for label, suffix, metric in _AGREEMENT_DIMENSIONS:
        matrix = _agreement_matrix(index, coders, units, suffix)
        alpha = krippendorff_alpha(matrix, metric=metric)  # type: ignore[arg-type]
        value = f"{alpha:.3f}" if alpha is not None else "insuf. datos"
        lines.append(f"| {label} | {metric} | {value} |")

    markdown = "\n".join(lines) + "\n"
    _emit_markdown(markdown, args.out)
    return 0


def _agreement_matrix(
    index: dict[tuple[str, str], dict[str, Any]],
    coders: list[str],
    units: list[str],
    suffix: str,
) -> list[list[Any]]:
    if suffix == "hay_emocion":
        return [
            [_agreement_value(index.get((coder, unit)), "hay_emocion") for unit in units]
            for coder in coders
        ]
    items = [(unit, slot) for unit in units for slot in range(1, EMOTION_SLOTS + 1)]
    return [
        [
            _agreement_value(index.get((coder, unit)), f"emocion_{slot}_{suffix}")
            for unit, slot in items
        ]
        for coder in coders
    ]


def _agreement_value(row: dict[str, Any] | None, column: str) -> str | None:
    if row is None:
        return None
    value = " ".join(str(row.get(column) or "").strip().lower().split())
    if column == "hay_emocion":
        value = {"sí": "si", "s": "si", "1": "si", "n": "no", "0": "no"}.get(value, value)
    return value or None


def _control(args: argparse.Namespace) -> int:
    db_path = _single_db(args, "--control")
    if db_path is None:
        return 1
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        unit_count = conn.execute("SELECT COUNT(*) FROM frases").fetchone()[0]
        emotion_count = conn.execute("SELECT COUNT(*) FROM emociones").fetchone()[0]
        with_emotion = conn.execute(
            "SELECT COUNT(DISTINCT codigo || '|' || frase_idx) FROM emociones"
        ).fetchone()[0]
    finally:
        conn.close()
    rate = with_emotion / unit_count if unit_count else 0.0
    print(
        f"Unidades: {unit_count} | Emociones detectadas: {emotion_count} | "
        f"Unidades con ≥1 emoción: {with_emotion} ({rate:.1%})"
    )
    print(
        "Sobre un corpus de control sin carga emocional, esta tasa estima la "
        "sobre-detección: cada emoción encontrada es un falso positivo probable."
    )
    if getattr(args, "persist_report", False):
        payload = {
            "report_type": "control",
            "metrics": {
                "unidades": int(unit_count),
                "emociones_detectadas": int(emotion_count),
                "unidades_con_emocion": int(with_emotion),
                "tasa_deteccion": rate,
            },
        }
        try:
            _persist_report(db_path, golden_version="control", payload=payload)
        except (OSError, RuntimeError, sqlite3.Error) as exc:
            logger.error(f"[eval] No se pudo persistir el reporte de control: {exc}")
            return 1
    return 0


def _persist_golden_report(
    *,
    db_path: Path,
    golden_path: Path,
    explicit_version: str | None,
    genre: str | None,
    report: MatchReport,
    aggregate: MatchReport | None = None,
) -> None:
    version = _resolve_golden_version(golden_path, explicit_version)
    payload: dict[str, Any] = {
        "report_type": "golden",
        "golden_version": version,
        "golden_sha256": _golden_digest(golden_path),
        "genre": genre,
        "metrics": _match_report_payload(report),
    }
    if aggregate is not None:
        payload["aggregate_metrics"] = _match_report_payload(aggregate)
    _persist_report(db_path, golden_version=version, payload=payload)


def _persist_report(
    db_path: Path,
    *,
    golden_version: str,
    payload: dict[str, Any],
) -> None:
    db = Database(db_path)
    runs = RunsRepository(db)
    try:
        runs.ensure_migrations()
        run = runs.get_run()
        if run is None:
            raise RuntimeError(f"{db_path}: la base no contiene metadata de run.")
        report_id = EvalReportsRepository(db).insert(
            run_id=run.run_id,
            golden_version=golden_version,
            payload=payload,
        )
    finally:
        db.close_thread_connection()
    logger.info(f"[eval] Reporte estructurado #{report_id} persistido en {db_path}")


def _match_report_payload(report: MatchReport) -> dict[str, Any]:
    return {
        "unidades": report.unidades,
        "tp": report.tp,
        "fp": report.fp,
        "fn": report.fn,
        "precision": report.precision,
        "recall": report.recall,
        "f1": report.f1,
        "dimensiones": {
            dimension: {
                "correctas": report.dim_correctas.get(dimension, 0),
                "evaluadas": report.dim_evaluadas.get(dimension, 0),
                "accuracy": report.dim_accuracy(dimension),
            }
            for dimension in DIMENSIONES
        },
        "desacuerdos": report.desacuerdos[:200],
    }


def _resolve_golden_version(path: Path, explicit: str | None) -> str:
    if explicit and explicit.strip():
        return explicit.strip()
    resolved = Path(path).expanduser().resolve()
    for part in reversed(resolved.parts):
        if re.fullmatch(r"v\d+(?:\.\d+)*", part, flags=re.IGNORECASE):
            return part
    return f"sha256:{_golden_digest(resolved)[:12]}"


def _golden_digest(path: Path) -> str:
    resolved = Path(path).expanduser().resolve()
    files = sorted(resolved.glob("*.jsonl")) if resolved.is_dir() else [resolved]
    digest = hashlib.sha256()
    for file in files:
        digest.update(file.name.encode("utf-8"))
        digest.update(b"\0")
        digest.update(file.read_bytes())
        digest.update(b"\n")
    return digest.hexdigest()


def _db_paths(args: argparse.Namespace) -> list[Path]:
    raw = getattr(args, "db", None)
    if raw is None:
        return []
    if isinstance(raw, Path):
        return [raw]
    return [Path(path) for path in raw]


def _single_db(args: argparse.Namespace, mode: str) -> Path | None:
    paths = _db_paths(args)
    if len(paths) != 1:
        logger.error(f"[eval] {mode} requiere exactamente un --db.")
        return None
    return paths[0]


def _emit_markdown(markdown: str, output: Path | None) -> None:
    print(markdown)
    if output is not None:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(markdown, encoding="utf-8")
        logger.info(f"[eval] Reporte guardado en {output}")


def _fmt(value: float | None) -> str:
    return f"{value:.3f}" if value is not None else "-"
