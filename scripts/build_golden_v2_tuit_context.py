#!/usr/bin/env python3
"""Adquiere el contexto saliente del corpus de tuits del golden v2."""

from __future__ import annotations

import argparse
import shutil
import tempfile
from pathlib import Path

from emoparse.acquisition.context_satellite import build_context_satellite
from emoparse.acquisition.sources.bluesky import BlueskyAdapter


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Construye el satélite contextual local del golden v2 sin ejecutar "
            "stages ni modificar la base origen."
        )
    )
    parser.add_argument(
        "--source",
        type=Path,
        default=Path("data/golden_v2/source/tuit.jsonl"),
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=Path("data/golden_v2/context"),
    )
    parser.add_argument("--max-parent-depth", type=int, default=5)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    output = args.out_dir
    if output.exists():
        raise SystemExit(f"ERROR: ya existe {output}; no se sobrescribió")
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(
        tempfile.mkdtemp(
            prefix=f".{output.name}_",
            dir=output.parent,
        )
    )

    adapter = BlueskyAdapter()
    try:
        result = build_context_satellite(
            source_jsonl=args.source,
            satellite_jsonl=temporary / "tuit_satellite.jsonl",
            links_jsonl=temporary / "tuit_context_links.jsonl",
            snapshot_jsonl=temporary / "tuit_annotation_context.jsonl",
            manifest_json=temporary / "manifest.json",
            fetch_posts=adapter.fetch_posts,
            max_parent_depth=args.max_parent_depth,
        )
        temporary.replace(output)
    except Exception:
        shutil.rmtree(temporary, ignore_errors=True)
        raise

    print("Satélite contextual del golden v2 preparado.")
    print(f"Corpus origen:          {result.origin_posts} posts")
    print(f"Unidades con contexto:  {result.origins_with_context}")
    print(f"Posts satélite:         {result.satellite_posts}")
    print(f"Vínculos:               {result.links}")
    print(f"Vínculos no resolubles: {result.unresolved_links}")
    print(f"Directorio:             {output.resolve()}")


if __name__ == "__main__":
    main()
