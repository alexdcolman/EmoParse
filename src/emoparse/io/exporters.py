# ══════════════════════════════════════════════════════════════════════════════
#  emoparse.io.exporters
#
#  Export de datos desde DB SQLite a CSV.
# ══════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

from loguru import logger

from emoparse.storage.db import Database


def _json_or_empty(raw: str | None) -> Any:
    """Deserializa JSON o devuelve None si la columna es NULL."""
    if raw is None:
        return None
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return None


def _flat(value: Any, prefix: str, result: dict[str, str]) -> None:
    """Aplana un dict de un nivel a columnas con prefijo.

    Solo un nivel de profundidad.
    """
    if value is None:
        return
    if not isinstance(value, dict):
        result[prefix] = str(value)
        return
    for k, v in value.items():
        col = f"{prefix}__{k}" if prefix else k
        if isinstance(v, (dict, list)):
            result[col] = json.dumps(v, ensure_ascii=False)
        elif v is None:
            result[col] = ""
        else:
            result[col] = str(v)


# ── Export discursos ──────────────────────────────────────────────────────────

#: Columnas fijas de input que siempre existen (vienen del CSV de input).
_DISCURSO_INPUT_COLS = ("codigo", "contenido", "titulo", "fecha", "url")

#: Stages que operan a nivel discurso y cuyos payloads se flatten.
_DISCURSO_STAGES = ("summarizer", "metadata", "enunciation")


def export_discursos_csv(db: Database, output_path: Path) -> int:
    """Exporta la tabla `discursos` a CSV con payloads flatten."""
    rows = db.execute(
        """
        SELECT
            codigo, input,
            summarizer_payload, summarizer_error,
            metadata_payload, metadata_error,
            enunciation_payload, enunciation_error,
            created_at, updated_at
        FROM discursos
        ORDER BY codigo
        """
    ).fetchall()

    if not rows:
        logger.warning("[export_discursos_csv] No hay discursos en la DB.")
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text("", encoding="utf-8")
        return 0

    records: list[dict[str, str]] = []
    all_keys: list[str] = []
    seen_keys: set[str] = set()

    for row in rows:
        record: dict[str, str] = {}

        input_data = _json_or_empty(row["input"]) or {}
        for k in _DISCURSO_INPUT_COLS:
            record[k] = str(input_data.get(k, "") or "")
        for k, v in input_data.items():
            if k not in _DISCURSO_INPUT_COLS:
                record[f"input__{k}"] = str(v) if v is not None else ""

        for stage in _DISCURSO_STAGES:
            payload = _json_or_empty(row[f"{stage}_payload"])
            _flat(payload, stage, record)
            record[f"{stage}__error"] = str(row[f"{stage}_error"] or "")

        record["created_at"] = str(row["created_at"] or "")
        record["updated_at"] = str(row["updated_at"] or "")

        for k in record:
            if k not in seen_keys:
                seen_keys.add(k)
                all_keys.append(k)

        records.append(record)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=all_keys, extrasaction="ignore")
        writer.writeheader()
        for rec in records:
            writer.writerow({k: rec.get(k, "") for k in all_keys})

    logger.info(f"[export_discursos_csv] {len(records)} filas → {output_path}")
    return len(records)


# ── Export frases ─────────────────────────────────────────────────────────────

def export_frases_csv(db: Database, output_path: Path) -> int:
    """Exporta la tabla `frases` a CSV."""
    rows = db.execute(
        """
        SELECT
            codigo, unit_idx, frase,
            actores_payload, actores_version, actores_error,
            emociones_payload, emociones_version, emociones_error,
            emociones_pass2_payload, emociones_pass2_version, emociones_pass2_error,
            created_at, updated_at
        FROM frases
        ORDER BY codigo, unit_idx
        """
    ).fetchall()

    if not rows:
        logger.warning("[export_frases_csv] No hay frases en la DB.")
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text("", encoding="utf-8")
        return 0

    fieldnames = [
        "codigo", "unit_idx", "frase",
        "actores_payload", "actores_version", "actores_error",
        "emociones_payload", "emociones_version", "emociones_error",
        "emociones_pass2_payload", "emociones_pass2_version", "emociones_pass2_error",
        "created_at", "updated_at",
    ]

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({
                "codigo": row["codigo"],
                "unit_idx": row["unit_idx"],
                "frase": row["frase"],
                "actores_payload": row["actores_payload"] or "",
                "actores_version": row["actores_version"] or "",
                "actores_error": row["actores_error"] or "",
                "emociones_payload": row["emociones_payload"] or "",
                "emociones_version": row["emociones_version"] or "",
                "emociones_error": row["emociones_error"] or "",
                "emociones_pass2_payload": row["emociones_pass2_payload"] or "",
                "emociones_pass2_version": row["emociones_pass2_version"] or "",
                "emociones_pass2_error": row["emociones_pass2_error"] or "",
                "created_at": str(row["created_at"] or ""),
                "updated_at": str(row["updated_at"] or ""),
            })

    logger.info(f"[export_frases_csv] {len(rows)} filas → {output_path}")
    return len(rows)


# ── Export emociones ──────────────────────────────────────────────────────────

def export_emociones_csv(db: Database, output_path: Path) -> int:
    """Exporta la tabla `emociones` a CSV con caracterización flatten."""
    rows = db.execute(
        """
        SELECT
            codigo, frase_idx, emocion_idx,
            experienciador, tipo_emocion, modo_existencia,
            deteccion_justificacion,
            caracterizacion_payload, caracterizacion_version,
            caracterizacion_error,
            created_at, updated_at
        FROM emociones
        ORDER BY codigo, frase_idx, emocion_idx
        """
    ).fetchall()

    if not rows:
        logger.warning("[export_emociones_csv] No hay emociones en la DB.")
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text("", encoding="utf-8")
        return 0

    records: list[dict[str, str]] = []
    all_keys: list[str] = []
    seen_keys: set[str] = set()

    base_keys = [
        "codigo", "frase_idx", "emocion_idx",
        "experienciador", "tipo_emocion", "modo_existencia",
        "deteccion_justificacion",
    ]
    for k in base_keys:
        seen_keys.add(k)
        all_keys.append(k)

    for row in rows:
        record: dict[str, str] = {
            "codigo": row["codigo"],
            "frase_idx": str(row["frase_idx"]),
            "emocion_idx": str(row["emocion_idx"]),
            "experienciador": row["experienciador"] or "",
            "tipo_emocion": row["tipo_emocion"] or "",
            "modo_existencia": row["modo_existencia"] or "",
            "deteccion_justificacion": row["deteccion_justificacion"] or "",
        }

        payload = _json_or_empty(row["caracterizacion_payload"])
        _flat(payload, "caracterizacion", record)

        record["caracterizacion_version"] = row["caracterizacion_version"] or ""
        record["caracterizacion_error"] = row["caracterizacion_error"] or ""
        record["created_at"] = str(row["created_at"] or "")
        record["updated_at"] = str(row["updated_at"] or "")

        for k in record:
            if k not in seen_keys:
                seen_keys.add(k)
                all_keys.append(k)

        records.append(record)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=all_keys, extrasaction="ignore")
        writer.writeheader()
        for rec in records:
            writer.writerow({k: rec.get(k, "") for k in all_keys})

    logger.info(f"[export_emociones_csv] {len(records)} filas → {output_path}")
    return len(records)


# ── Export full run ───────────────────────────────────────────────────────────

def export_full_run(db: Database, output_dir: Path) -> dict[str, int]:
    """Corre los tres exporters y devuelve conteos."""
    output_dir.mkdir(parents=True, exist_ok=True)
    return {
        "discursos": export_discursos_csv(db, output_dir / "discursos.csv"),
        "frases":    export_frases_csv(db, output_dir / "frases.csv"),
        "emociones": export_emociones_csv(db, output_dir / "emociones.csv"),
    }
