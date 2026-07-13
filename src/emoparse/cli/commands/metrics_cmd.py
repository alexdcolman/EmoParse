# ══════════════════════════════════════════════════════════════════════════════
#  emoparse.cli.commands.metrics_cmd
#
#  Subcomando `metrics`: imprime métricas persistidas por stage.
#
#  Lee la tabla `run_metrics` y muestra la última ejecución registrada
#  para cada stage de un run. Incluye cantidades procesadas, latencias,
#  uso de tokens y estadísticas de cache.
# ══════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

import argparse
from pathlib import Path

from loguru import logger

from emoparse.storage.db import Database
from emoparse.storage.metrics import MetricsRepository


def handle(args: argparse.Namespace) -> int:
    db_path = Path(args.db).expanduser().resolve()
    if not db_path.is_file():
        logger.error(f"DB no encontrada: {db_path}")
        return 1

    db = Database(db_path)

    # Obtiene el run_id desde `runs` (una DB corresponde a un único run).
    row = db.execute("SELECT run_id FROM runs LIMIT 1").fetchone()
    if row is None:
        logger.error("No hay run registrado en esta DB.")
        return 1
    run_id = row["run_id"]

    repo = MetricsRepository(db)
    rows = repo.list_latest_per_stage(run_id)

    print()
    print(f"=== Run metrics: {db_path.name} (run_id={run_id}) ===")
    print()

    if not rows:
        print("(sin métricas registradas — ¿el run no terminó ninguna stage?)")
        return 0

    # Anchos fijos para mantener la tabla legible en terminal estándar.
    headers = [
        ("stage", 18),
        ("ok", 6),
        ("failed", 7),
        ("total_ms", 11),
        ("p50_ms", 9),
        ("p99_ms", 9),
        ("prompt_tok", 11),
        ("compl_tok", 10),
        ("tok/s", 8),
        ("hits", 6),
        ("misses", 7),
    ]
    header_line = " ".join(f"{h:>{w}}" for h, w in headers)
    print(header_line)
    print("-" * len(header_line))

    for r in rows:
        cells = [
            (r["stage_name"], 18, "left"),
            (str(r["n_items_ok"]), 6, "right"),
            (str(r["n_items_failed"]), 7, "right"),
            (_fmt_ms(r["total_latency_ms"]), 11, "right"),
            (_fmt_ms(r["p50_latency_ms"]), 9, "right"),
            (_fmt_ms(r["p99_latency_ms"]), 9, "right"),
            (str(r["total_prompt_tokens"]), 11, "right"),
            (str(r["total_completion_tokens"]), 10, "right"),
            (_fmt_tok_s(r["total_completion_tokens"], r["total_latency_ms"]), 8, "right"),
            (str(r["cache_hits"]), 6, "right"),
            (str(r["cache_misses"]), 7, "right"),
        ]
        line_parts = []
        for value, width, align in cells:
            if align == "left":
                line_parts.append(f"{value:<{width}}")
            else:
                line_parts.append(f"{value:>{width}}")
        print(" ".join(line_parts))

    print()
    return 0


def _fmt_tok_s(tokens: int | None, total_ms: float | None) -> str:
    """Throughput de decode (tokens de completion por segundo). '-' si no aplica.

    Es la métrica sensible a las optimizaciones de backend (speculative
    decoding, KV cuantizado); el prefill se lee comparando prompt_tok
    contra total_ms entre corridas.
    """
    if not tokens or not total_ms or total_ms <= 0:
        return "-"
    return f"{tokens / (total_ms / 1000.0):.1f}"


def _fmt_ms(v: float | None) -> str:
    """Formatea milisegundos. None → '-'."""
    if v is None:
        return "-"
    if v >= 1000:
        return f"{v/1000:.1f}s"
    return f"{v:.1f}"
