# ══════════════════════════════════════════════════════════════════════════════
#  emoparse.evaluation.golden
#
#  Carga del golden set y de las emociones de un run para su comparación.
#
#  Formato golden (JSONL, una unidad por línea):
#      {"codigo": "...", "unit_idx": 0,
#       "emociones": [{"experienciador": "...", "tipo_emocion": "...",
#                      "modo_existencia": "...", "foria": "..."}]}
#  `emociones: []` anota explícitamente una unidad SIN emociones (crucial
#  para medir falsos positivos). `modo_existencia` y `foria` son opcionales
#  por emoción: si faltan, esa dimensión no se evalúa en ese caso.
# ══════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any


class GoldenError(RuntimeError):
    """Golden set ilegible o malformado."""


def load_golden(path: Path | str) -> dict[tuple[str, int], list[dict[str, Any]]]:
    """Carga un golden set. Acepta un archivo .jsonl o un directorio (se
    concatenan todos sus .jsonl)."""
    p = Path(path).expanduser().resolve()
    archivos = sorted(p.glob("*.jsonl")) if p.is_dir() else [p]
    if not archivos or not all(a.is_file() for a in archivos):
        raise GoldenError(f"Golden no encontrado en {p}")

    unidades: dict[tuple[str, int], list[dict[str, Any]]] = {}
    for archivo in archivos:
        with archivo.open(encoding="utf-8") as fh:
            for lineno, line in enumerate(fh, start=1):
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError as e:
                    raise GoldenError(f"{archivo}:{lineno}: {e}") from e
                codigo = str(obj.get("codigo") or "")
                if not codigo:
                    raise GoldenError(f"{archivo}:{lineno}: falta `codigo`")
                key = (codigo, int(obj.get("unit_idx", 0)))
                emociones = obj.get("emociones")
                if not isinstance(emociones, list):
                    raise GoldenError(
                        f"{archivo}:{lineno}: `emociones` debe ser lista "
                        "(vacía para unidades sin emociones)"
                    )
                unidades[key] = [e for e in emociones if isinstance(e, dict)]
    return unidades


def load_run_emotions(
    db_path: Path | str,
    keys: set[tuple[str, int]] | None = None,
) -> dict[tuple[str, int], list[dict[str, Any]]]:
    """Emociones del run agrupadas por (codigo, unit_idx), con la foria de
    la caracterización desplegada."""
    conn = sqlite3.connect(f"file:{Path(db_path)}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute("SELECT * FROM emociones").fetchall()
    finally:
        conn.close()

    out: dict[tuple[str, int], list[dict[str, Any]]] = {}
    for row in rows:
        key = (str(row["codigo"]), int(row["frase_idx"]))
        if keys is not None and key not in keys:
            continue
        emo = dict(row)
        payload = emo.get("caracterizacion_payload")
        if isinstance(payload, str) and payload:
            try:
                emo["foria"] = json.loads(payload).get("foria")
            except json.JSONDecodeError:
                pass
        out.setdefault(key, []).append(emo)
    if keys is not None:
        for key in keys:
            out.setdefault(key, [])
    return out
