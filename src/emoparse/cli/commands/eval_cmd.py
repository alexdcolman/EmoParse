# ══════════════════════════════════════════════════════════════════════════════
#  emoparse.cli.commands.eval_cmd
#
#  Subcomando `emoparse eval`: evaluación de validez del análisis.
#
#  Cuatro modos (mutuamente compatibles con --out para persistir el reporte):
#
#  --golden <archivo|dir>   Regresión contra un golden set: precisión/recall/
#                           F1 de detección + accuracy por dimensión sobre
#                           pares emparejados. Correrlo tras cada cambio de
#                           prompt u ontología convierte la edición en un
#                           experimento medible.
#  --make-sample            Exporta una planilla de anotación A CIEGAS
#                           (muestra estratificada, sin salidas del modelo)
#                           para el protocolo multi-anotador.
#  --agreement <csv>        Alpha de Krippendorff por dimensión sobre las
#                           planillas completadas por los anotadores
#                           (concatenadas en un CSV con columna `anotador`).
#  --control                Tasa de detección sobre el run actual: pensado
#                           para corpus de control sin carga emocional
#                           (data/ejemplos/control_neutro.csv), donde toda
#                           detección es un falso positivo probable.
# ══════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path

import pandas as pd
from loguru import logger

from emoparse.evaluation.agreement import krippendorff_alpha
from emoparse.evaluation.golden import GoldenError, load_golden, load_run_emotions
from emoparse.evaluation.matching import build_alias_map, match_units
from emoparse.evaluation.sampling import make_annotation_sample

#: Dimensiones de la planilla → métrica de alpha.
_AGREEMENT_DIMENSIONS: dict[str, str] = {
    "hay_emocion": "nominal",
    "emocion_1_tipo": "nominal",
    "emocion_1_experienciador": "nominal",
    "emocion_1_foria": "nominal",
}


def add_subparser(subparsers: argparse._SubParsersAction) -> argparse.ArgumentParser:
    """Registra `eval` como subcomando en el CLI principal."""
    p = subparsers.add_parser(
        "eval",
        help="Evaluación de validez: golden set, acuerdo inter-anotador, "
             "controles.",
        description="Evaluación de validez del análisis emocional.",
    )
    p.add_argument("--db", type=Path, default=None,
                   help="DB del run a evaluar (para --golden, --make-sample, "
                        "--control).")
    p.add_argument("--golden", type=Path, default=None,
                   help="Golden set (.jsonl o directorio de .jsonl).")
    p.add_argument("--ontology", type=Path,
                   default=Path("knowledge/emociones_ontologia.json"),
                   help="Ontología para canonicalizar tipos al comparar.")
    p.add_argument("--make-sample", action="store_true",
                   help="Exporta planilla de anotación a ciegas (--out).")
    p.add_argument("--n", type=int, default=300,
                   help="Tamaño de la muestra de anotación.")
    p.add_argument("--seed", type=int, default=42,
                   help="Seed del muestreo (reproducibilidad).")
    p.add_argument("--agreement", type=Path, default=None,
                   help="CSV con las planillas completadas (columna "
                        "`anotador` + columnas de anotación).")
    p.add_argument("--control", action="store_true",
                   help="Reporta la tasa de detección del run (corpus de "
                        "control → tasa esperada ≈ 0).")
    p.add_argument("--out", type=Path, default=None,
                   help="Archivo de salida (reporte .md o planilla .csv).")
    p.set_defaults(handler=run)
    return p


def run(args: argparse.Namespace) -> int:
    """Ejecuta el subcomando. Devuelve exit code (0 = ok)."""
    if args.make_sample:
        return _make_sample(args)
    if args.agreement is not None:
        return _agreement(args)
    if args.golden is not None:
        return _golden(args)
    if args.control:
        return _control(args)
    logger.error(
        "[eval] Indicá un modo: --golden, --make-sample, --agreement o "
        "--control."
    )
    return 1


# ══════════════════════════════════════════════════════════════════════════════
#  Modos
# ══════════════════════════════════════════════════════════════════════════════

def _golden(args: argparse.Namespace) -> int:
    if args.db is None:
        logger.error("[eval] --golden requiere --db.")
        return 1
    try:
        golden = load_golden(args.golden)
    except GoldenError as e:
        logger.error(f"[eval] {e}")
        return 1
    try:
        ontologia = json.loads(args.ontology.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        logger.error(f"[eval] Ontología ilegible ({args.ontology}): {e}")
        return 1

    preds = load_run_emotions(args.db, keys=set(golden))
    report = match_units(golden, preds, build_alias_map(ontologia))

    md = _golden_markdown(report, args)
    print(md)
    if args.out:
        args.out.write_text(md, encoding="utf-8")
        logger.info(f"[eval] Reporte guardado en {args.out}")
    return 0


def _golden_markdown(report, args: argparse.Namespace) -> str:
    def fmt(v):
        return f"{v:.3f}" if v is not None else "-"

    lineas = [
        f"# Evaluación contra golden — {Path(args.db).name}",
        "",
        f"Unidades evaluadas: {report.unidades}",
        "",
        "## Detección de emociones",
        "",
        "| métrica | valor |", "|---|---|",
        f"| TP / FP / FN | {report.tp} / {report.fp} / {report.fn} |",
        f"| Precisión | {fmt(report.precision)} |",
        f"| Recall | {fmt(report.recall)} |",
        f"| F1 | {fmt(report.f1)} |",
        "",
        "## Accuracy por dimensión (sobre pares emparejados)",
        "",
        "| dimensión | correctas / evaluadas | accuracy |", "|---|---|---|",
    ]
    for dim in ("tipo", "experienciador", "modo_existencia", "foria"):
        n = report.dim_evaluadas.get(dim, 0)
        ok = report.dim_correctas.get(dim, 0)
        lineas.append(f"| {dim} | {ok} / {n} | {fmt(report.dim_accuracy(dim))} |")
    if report.desacuerdos:
        lineas += ["", "## Desacuerdos (muestra)", ""]
        for d in report.desacuerdos[:30]:
            lineas.append(
                f"- `{d['codigo']}`[{d['unit_idx']}] {d['dimension']}: "
                f"golden={d['golden']!r} vs pred={d['prediccion']!r}"
            )
    return "\n".join(lineas) + "\n"


def _make_sample(args: argparse.Namespace) -> int:
    if args.db is None or args.out is None:
        logger.error("[eval] --make-sample requiere --db y --out (.csv).")
        return 1
    df = make_annotation_sample(args.db, n=args.n, seed=args.seed)
    df.to_csv(args.out, index=False, encoding="utf-8")
    logger.info(
        f"[eval] Planilla de {len(df)} unidades → {args.out}. "
        "Distribuir UNA COPIA POR ANOTADOR (anotación independiente, a "
        "ciegas); consigna en evals/manual_anotacion.md."
    )
    return 0


def _agreement(args: argparse.Namespace) -> int:
    try:
        df = pd.read_csv(args.agreement, dtype=str)
    except (OSError, pd.errors.ParserError) as e:
        logger.error(f"[eval] CSV de acuerdo ilegible: {e}")
        return 1
    if "anotador" not in df.columns or "id_muestra" not in df.columns:
        logger.error(
            "[eval] El CSV debe concatenar las planillas con columnas "
            "`anotador` e `id_muestra`."
        )
        return 1

    anotadores = sorted(df["anotador"].dropna().unique())
    unidades = sorted(df["id_muestra"].dropna().unique())
    lineas = [
        "# Acuerdo inter-anotador (alpha de Krippendorff)",
        "",
        f"Anotadores: {len(anotadores)} ({', '.join(anotadores)}) — "
        f"Unidades: {len(unidades)}",
        "",
        "| dimensión | métrica | alpha |", "|---|---|---|",
    ]
    indexed = df.set_index(["anotador", "id_muestra"])
    for columna, metric in _AGREEMENT_DIMENSIONS.items():
        if columna not in df.columns:
            continue
        matriz = [
            [
                indexed[columna].get((a, u)) if (a, u) in indexed.index else None
                for u in unidades
            ]
            for a in anotadores
        ]
        alpha = krippendorff_alpha(matriz, metric=metric)  # type: ignore[arg-type]
        valor = f"{alpha:.3f}" if alpha is not None else "insuf. datos"
        lineas.append(f"| {columna} | {metric} | {valor} |")

    md = "\n".join(lineas) + "\n"
    print(md)
    if args.out:
        args.out.write_text(md, encoding="utf-8")
    return 0


def _control(args: argparse.Namespace) -> int:
    if args.db is None:
        logger.error("[eval] --control requiere --db.")
        return 1
    conn = sqlite3.connect(f"file:{args.db}?mode=ro", uri=True)
    try:
        n_unidades = conn.execute("SELECT COUNT(*) FROM frases").fetchone()[0]
        n_emociones = conn.execute("SELECT COUNT(*) FROM emociones").fetchone()[0]
        n_con = conn.execute(
            "SELECT COUNT(DISTINCT codigo || '|' || frase_idx) FROM emociones"
        ).fetchone()[0]
    finally:
        conn.close()
    tasa = n_con / n_unidades if n_unidades else 0.0
    print(
        f"Unidades: {n_unidades} | Emociones detectadas: {n_emociones} | "
        f"Unidades con ≥1 emoción: {n_con} ({tasa:.1%})"
    )
    print(
        "Sobre un corpus de control sin carga emocional, esta tasa estima "
        "la sobre-detección: cada emoción encontrada es un falso positivo "
        "probable que conviene inspeccionar."
    )
    return 0
