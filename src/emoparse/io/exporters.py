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


def _flat2(value: Any, prefix: str, result: dict[str, str]) -> None:
    """Aplana un dict de dos niveles a columnas con prefijo.

    Pensado para payloads cuyo primer nivel agrupa sub-objetos
    homogéneos (p. ej. la configuración actancial, donde cada
    componente es a su vez un dict con `presente`, `tipo`,
    `justificacion`, ...). El resultado son columnas
    ``<prefix>__<componente>__<campo>``. Listas y dicts más profundos
    se serializan como JSON.
    """
    if not isinstance(value, dict):
        _flat(value, prefix, result)
        return
    for comp, sub in value.items():
        sub_prefix = f"{prefix}__{comp}" if prefix else comp
        if isinstance(sub, dict):
            _flat(sub, sub_prefix, result)
        elif sub is None:
            result[sub_prefix] = ""
        elif isinstance(sub, list):
            result[sub_prefix] = json.dumps(sub, ensure_ascii=False)
        else:
            result[sub_prefix] = str(sub)


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
        record["codigo"] = str(row["codigo"] or "")
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
    has_canonicos = _has_columns(
        db, "frases",
        ("actores_canonicos_payload", "actores_canonicos_version", "actores_canonicos_error"),
    )

    canonicos_select = (
        ", actores_canonicos_payload, actores_canonicos_version, actores_canonicos_error"
        if has_canonicos else ""
    )

    rows = db.execute(
        f"""
        SELECT
            codigo, unit_idx, frase,
            actores_payload, actores_version, actores_error,
            emociones_payload, emociones_version, emociones_error,
            emociones_pass2_payload, emociones_pass2_version, emociones_pass2_error
            {canonicos_select},
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
    ]
    if has_canonicos:
        fieldnames += [
            "actores_canonicos_payload",
            "actores_canonicos_version",
            "actores_canonicos_error",
            "actores_canonicos_n_linked",
            "actores_canonicos_n_nuevos",
        ]
    fieldnames += ["created_at", "updated_at"]

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            record: dict[str, str] = {
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
            }
            if has_canonicos:
                canon_raw = row["actores_canonicos_payload"]
                record["actores_canonicos_payload"] = canon_raw or ""
                record["actores_canonicos_version"] = row["actores_canonicos_version"] or ""
                record["actores_canonicos_error"] = row["actores_canonicos_error"] or ""
                n_linked, n_nuevos = _summarize_canonicos(canon_raw)
                record["actores_canonicos_n_linked"] = str(n_linked)
                record["actores_canonicos_n_nuevos"] = str(n_nuevos)
            writer.writerow(record)

    logger.info(f"[export_frases_csv] {len(rows)} filas → {output_path}")
    return len(rows)


def _has_columns(db: Database, table: str, columns: tuple[str, ...]) -> bool:
    """True si la tabla tiene todas las columnas indicadas."""
    existing = {
        row["name"]
        for row in db.execute(f"PRAGMA table_info({table})").fetchall()
    }
    return all(c in existing for c in columns)


def _summarize_canonicos(raw: str | None) -> tuple[int, int]:
    """Cuenta linkings con canónico y entidades nuevas en un payload.

    Devuelve (n_linked, n_nuevos). Si el payload es None o malformado,
    devuelve (0, 0).
    """
    parsed = _json_or_empty(raw)
    if not isinstance(parsed, list):
        return 0, 0
    n_linked = 0
    n_nuevos = 0
    for link in parsed:
        if not isinstance(link, dict):
            continue
        if link.get("actor_canonico") is not None:
            n_linked += 1
        if link.get("es_nuevo") is True:
            n_nuevos += 1
    return n_linked, n_nuevos


# ── Export emociones ──────────────────────────────────────────────────────────

def export_emociones_csv(db: Database, output_path: Path) -> int:
    """Exporta la tabla `emociones` a CSV con caracterización flatten."""
    # Columnas agregadas en versiones posteriores. Se incluyen solo si
    # existen para no romper el export sobre DBs que aún no corrieron las
    # migraciones aditivas.
    has_tipo_conf = _has_columns(db, "emociones", ("tipo_configuracion",))
    has_canonico = _has_columns(db, "emociones", ("tipo_emocion_canonico",))
    has_actantes = _has_columns(
        db, "emociones",
        ("actantes_payload", "actantes_version", "actantes_error"),
    )

    extra_select = ""
    if has_tipo_conf:
        extra_select += ", tipo_configuracion"
    if has_canonico:
        extra_select += ", tipo_emocion_canonico"
    if has_actantes:
        extra_select += (
            ", actantes_payload, actantes_version, actantes_error"
        )

    rows = db.execute(
        f"""
        SELECT
            codigo, frase_idx, emocion_idx,
            experienciador, tipo_emocion, modo_existencia,
            deteccion_justificacion,
            caracterizacion_payload, caracterizacion_version,
            caracterizacion_error
            {extra_select},
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

        if has_tipo_conf:
            record["tipo_configuracion"] = row["tipo_configuracion"] or ""
        if has_canonico:
            record["tipo_emocion_canonico"] = row["tipo_emocion_canonico"] or ""
        if has_actantes:
            actantes_payload = _json_or_empty(row["actantes_payload"])
            _flat2(actantes_payload, "actantes", record)
            record["actantes_version"] = row["actantes_version"] or ""
            record["actantes_error"] = row["actantes_error"] or ""

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

def export_discoveries_csv(db: Database, output_path: Path) -> int:
    """Exporta la tabla `actors_kb_discoveries` con su decisión actual."""
    has_table = bool(db.execute(
        "SELECT name FROM sqlite_master "
        "WHERE type='table' AND name='actors_kb_discoveries' LIMIT 1"
    ).fetchone())

    output_path.parent.mkdir(parents=True, exist_ok=True)

    if not has_table:
        logger.warning(
            "[export_discoveries_csv] DB sin tabla actors_kb_discoveries "
            "CSV vacío."
        )
        output_path.write_text("", encoding="utf-8")
        return 0

    has_decisions = bool(db.execute(
        "SELECT name FROM sqlite_master "
        "WHERE type='table' AND name='actors_kb_decisions' LIMIT 1"
    ).fetchone())

    if has_decisions:
        rows = db.execute(
            """
            SELECT
                h.id, h.codigo, h.unit_idx, h.actor_mencionado,
                h.confianza, h.contexto, h.justificacion,
                h.discovered_at, h.reviewed,
                d.decision   AS decision_actual,
                d.status     AS decision_status,
                d.canonical_id, d.display_name, d.tipo, d.rol,
                d.origin, d.error_message, d.applied_at
            FROM actors_kb_discoveries h
            LEFT JOIN actors_kb_decisions d ON d.discovery_id = h.id
            ORDER BY h.discovered_at ASC
            """
        ).fetchall()
        fieldnames = [
            "id", "codigo", "unit_idx", "actor_mencionado",
            "confianza", "contexto", "justificacion",
            "discovered_at", "reviewed",
            "decision_actual", "decision_status",
            "canonical_id", "display_name", "tipo", "rol",
            "origin", "error_message", "applied_at",
        ]
    else:
        rows = db.execute(
            """
            SELECT
                id, codigo, unit_idx, actor_mencionado,
                confianza, contexto, justificacion,
                discovered_at, reviewed
            FROM actors_kb_discoveries
            ORDER BY discovered_at ASC
            """
        ).fetchall()
        fieldnames = [
            "id", "codigo", "unit_idx", "actor_mencionado",
            "confianza", "contexto", "justificacion",
            "discovered_at", "reviewed",
        ]

    if not rows:
        logger.warning("[export_discoveries_csv] Sin discoveries en la DB.")
        with output_path.open("w", newline="", encoding="utf-8") as f:
            csv.DictWriter(f, fieldnames=fieldnames).writeheader()
        return 0

    with output_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({k: (row[k] if row[k] is not None else "") for k in fieldnames})

    logger.info(f"[export_discoveries_csv] {len(rows)} filas → {output_path}")
    return len(rows)


def export_full_run(db: Database, output_dir: Path) -> dict[str, int]:
    """Corre los cuatro exporters y devuelve conteos."""
    output_dir.mkdir(parents=True, exist_ok=True)
    return {
        "discursos":    export_discursos_csv(db, output_dir / "discursos.csv"),
        "frases":       export_frases_csv(db, output_dir / "frases.csv"),
        "emociones":    export_emociones_csv(db, output_dir / "emociones.csv"),
        "discoveries":  export_discoveries_csv(db, output_dir / "discoveries.csv"),
    }
