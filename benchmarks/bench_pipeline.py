#!/usr/bin/env python3
# ══════════════════════════════════════════════════════════════════════════════
#  benchmarks/bench_pipeline.py
#
#  Harness reproducible para comparar configuraciones de backend.
#
#  Corre el mismo corpus y las mismas stages con dos o más configs (p. ej.
#  in-process vs llama-server, server con y sin --model-draft, parallel 1
#  vs 4) y tabula las métricas persistidas de cada run en un markdown.
#
#  Uso:
#      python benchmarks/bench_pipeline.py \
#          --input data/corpus.jsonl --genre tuit \
#          --stages technoparse,actors,emotions \
#          --config-a config_inprocess.yaml --label-a in-process \
#          --config-b config_server.yaml --label-b llama-server-p4 \
#          --out benchmarks/resultado.md
#
#  Cada variante corre en una DB propia y SIN cache compartido, así el
#  segundo run no se beneficia del primero. Repetir con --runs N para
#  promediar (el sampling es determinista con seed fija, pero la latencia
#  del sistema no).
# ══════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

import argparse
import sqlite3
import subprocess
import sys
import time
from pathlib import Path


def main() -> int:
    args = _parse_args()
    variantes = [("a", args.config_a, args.label_a)]
    if args.config_b:
        variantes.append(("b", args.config_b, args.label_b))
    if args.config_c:
        variantes.append(("c", args.config_c, args.label_c))

    resultados: list[dict] = []
    for corrida in range(args.runs):
        for key, config, label in variantes:
            run_id = f"bench_{key}_{int(time.time())}_{corrida}"
            db_path = Path(args.workdir) / f"{run_id}.sqlite"
            cmd = [
                sys.executable, "-m", "emoparse", "run",
                "--run-id", run_id,
                "--config", config,
                "--input", args.input,
                "--genre", args.genre,
                "--stages", args.stages,
                "--db", str(db_path),
            ]
            print(f"→ [{label}] corrida {corrida + 1}/{args.runs}: {' '.join(cmd)}")
            t0 = time.perf_counter()
            proc = subprocess.run(cmd)
            wall = time.perf_counter() - t0
            if proc.returncode != 0:
                print(f"  ✗ falló (exit {proc.returncode}); se omite de la tabla.")
                continue
            for stage_row in _read_metrics(db_path):
                resultados.append({"variante": label, "corrida": corrida,
                                   "wall_s": wall, **stage_row})

    md = _to_markdown(resultados)
    print(md)
    if args.out:
        Path(args.out).write_text(md, encoding="utf-8")
        print(f"Guardado en {args.out}")
    return 0


def _read_metrics(db_path: Path) -> list[dict]:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            "SELECT stage_name, n_items_ok, n_items_failed, total_latency_ms, "
            "p50_latency_ms, total_prompt_tokens, total_completion_tokens, "
            "cache_hits, cache_misses FROM run_metrics"
        ).fetchall()
    finally:
        conn.close()
    return [dict(r) for r in rows]


def _to_markdown(rows: list[dict]) -> str:
    if not rows:
        return "(sin resultados)\n"
    lineas = [
        "| variante | stage | items | total_s | p50_ms | prompt_tok | compl_tok | tok/s | hits |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for r in sorted(rows, key=lambda x: (x["stage_name"], x["variante"], x["corrida"])):
        total_s = (r["total_latency_ms"] or 0) / 1000.0
        toks = r["total_completion_tokens"] or 0
        tok_s = f"{toks / total_s:.1f}" if total_s > 0 and toks else "-"
        lineas.append(
            f"| {r['variante']} | {r['stage_name']} | {r['n_items_ok']} "
            f"| {total_s:.1f} | {r['p50_latency_ms'] or 0:.0f} "
            f"| {r['total_prompt_tokens']} | {toks} | {tok_s} "
            f"| {r['cache_hits']} |"
        )
    return "\n".join(lineas) + "\n"


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--input", required=True)
    p.add_argument("--genre", default="tuit")
    p.add_argument("--stages", default="technoparse,actors,emotions")
    p.add_argument("--config-a", required=True)
    p.add_argument("--label-a", default="variante_a")
    p.add_argument("--config-b", default=None)
    p.add_argument("--label-b", default="variante_b")
    p.add_argument("--config-c", default=None)
    p.add_argument("--label-c", default="variante_c")
    p.add_argument("--runs", type=int, default=1)
    p.add_argument("--workdir", default="benchmarks/runs")
    p.add_argument("--out", default=None)
    return p.parse_args()


if __name__ == "__main__":
    Path("benchmarks/runs").mkdir(parents=True, exist_ok=True)
    raise SystemExit(main())
