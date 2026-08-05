"""Contexto intradocumental determinista para campañas de anotación.

El contexto se deriva de la SQLite preparada sin LLM y de la muestra ciega.
No modifica ninguna base ni incorpora outputs analíticos del pipeline.
"""

from __future__ import annotations

import csv
import hashlib
import json
import sqlite3
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

_SUPPORTED_GENRES = {"articulo_periodistico", "discurso_presidencial"}

_ARTICLE_METADATA = (
    ("titulo", "Título"),
    ("fecha", "Fecha"),
    ("medio", "Medio"),
    ("seccion", "Sección"),
    ("volanta", "Volanta"),
    ("subtitulo", "Subtítulo"),
    ("autoria", "Autoría"),
    ("agencia", "Agencia"),
    ("epigrafe", "Epígrafe"),
    ("idioma", "Idioma"),
    ("fuente", "Fuente"),
    ("url", "URL"),
)

_DISCOURSE_METADATA = (
    ("titulo", "Título"),
    ("fecha", "Fecha"),
    ("fuente", "Fuente"),
    ("url", "URL"),
)


@dataclass(frozen=True, slots=True)
class DocumentContextResult:
    genre: str
    units: int
    units_with_context: int
    context_items: int
    metadata_items: int
    previous_items: int
    next_items: int
    database_sha256: str
    sample_sha256: str
    snapshot_sha256: str


def build_document_context_snapshot(
    *,
    db_path: Path,
    sample_csv: Path,
    snapshot_jsonl: Path,
    manifest_json: Path,
    genre: str,
    previous_units: int,
    next_units: int,
) -> DocumentContextResult:
    """Construye contexto editorial y unidades vecinas para una muestra ciega."""
    if genre not in _SUPPORTED_GENRES:
        raise ValueError(f"género no soportado: {genre}")
    if previous_units < 0 or next_units < 0:
        raise ValueError("las ventanas de contexto no pueden ser negativas")
    if not db_path.is_file():
        raise ValueError(f"no existe la base: {db_path}")
    if not sample_csv.is_file():
        raise ValueError(f"no existe la muestra: {sample_csv}")
    if snapshot_jsonl.exists() or manifest_json.exists():
        raise ValueError("la salida ya existe; no se sobrescribió")

    samples = _load_samples(sample_csv, genre=genre)
    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row
    try:
        _validate_database_genre(connection, expected=genre)
        inputs = _load_inputs(connection, {sample["codigo"] for sample in samples})
        units = _load_units(connection, {sample["codigo"] for sample in samples})
    finally:
        connection.close()

    records: list[dict[str, Any]] = []
    metadata_items = 0
    previous_items = 0
    next_items = 0
    context_items = 0

    for sample in samples:
        codigo = sample["codigo"]
        unit_idx = sample["unit_idx"]
        key = (codigo, unit_idx)
        stored_text = units.get(key)
        if stored_text is None:
            raise ValueError(f"la base no contiene {codigo}[{unit_idx}]")
        if stored_text != sample["texto"]:
            raise ValueError(
                f"el texto de la muestra no coincide con la base en {codigo}[{unit_idx}]"
            )
        input_payload = inputs.get(codigo)
        if input_payload is None:
            raise ValueError(f"la base no contiene input para {codigo}")

        contexts: list[dict[str, Any]] = []
        metadata_text = _render_metadata(genre, input_payload)
        if metadata_text:
            contexts.append(
                _context_item(
                    relation="document_metadata",
                    depth=None,
                    codigo=codigo,
                    unit_idx=None,
                    text=metadata_text,
                    date=_text(input_payload.get("fecha")),
                    url=_text(input_payload.get("url")),
                )
            )
            metadata_items += 1

        for distance in range(previous_units, 0, -1):
            target_idx = unit_idx - distance
            target_text = units.get((codigo, target_idx))
            if target_text is None:
                continue
            contexts.append(
                _context_item(
                    relation="previous_unit",
                    depth=distance,
                    codigo=codigo,
                    unit_idx=target_idx,
                    text=target_text,
                )
            )
            previous_items += 1

        for distance in range(1, next_units + 1):
            target_idx = unit_idx + distance
            target_text = units.get((codigo, target_idx))
            if target_text is None:
                continue
            contexts.append(
                _context_item(
                    relation="next_unit",
                    depth=distance,
                    codigo=codigo,
                    unit_idx=target_idx,
                    text=target_text,
                )
            )
            next_items += 1

        context_items += len(contexts)
        records.append(
            {
                "codigo": codigo,
                "unit_idx": unit_idx,
                "genero": genre,
                "contexts": contexts,
            }
        )

    snapshot_jsonl.parent.mkdir(parents=True, exist_ok=True)
    snapshot_jsonl.write_text(
        "".join(json.dumps(record, ensure_ascii=False) + "\n" for record in records),
        encoding="utf-8",
    )
    result = DocumentContextResult(
        genre=genre,
        units=len(records),
        units_with_context=sum(bool(record["contexts"]) for record in records),
        context_items=context_items,
        metadata_items=metadata_items,
        previous_items=previous_items,
        next_items=next_items,
        database_sha256=_sha256(db_path),
        sample_sha256=_sha256(sample_csv),
        snapshot_sha256=_sha256(snapshot_jsonl),
    )
    manifest_json.parent.mkdir(parents=True, exist_ok=True)
    manifest_json.write_text(
        json.dumps(
            {
                "schema": 1,
                "purpose": "golden_v2_intradocumental_annotation_context",
                "policy": {
                    "genre": genre,
                    "previous_units": previous_units,
                    "next_units": next_units,
                    "llm_outputs_included": False,
                    "network_access": False,
                },
                "result": asdict(result),
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return result


def _load_samples(path: Path, *, genre: str) -> list[dict[str, Any]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        required = {"genero", "codigo", "unit_idx", "texto"}
        missing = required - set(reader.fieldnames or ())
        if missing:
            raise ValueError(f"la muestra carece de columnas: {', '.join(sorted(missing))}")
        rows: list[dict[str, Any]] = []
        seen: set[tuple[str, int]] = set()
        for line_number, row in enumerate(reader, start=2):
            row_genre = _text(row.get("genero"))
            if row_genre != genre:
                raise ValueError(
                    f"{path}:{line_number}: género {row_genre!r}; se esperaba {genre!r}"
                )
            codigo = _text(row.get("codigo"))
            texto = _text(row.get("texto"))
            try:
                unit_idx = int(_text(row.get("unit_idx")))
            except ValueError as exc:
                raise ValueError(f"{path}:{line_number}: unit_idx inválido") from exc
            key = (codigo, unit_idx)
            if not codigo or not texto or key in seen:
                raise ValueError(f"{path}:{line_number}: unidad vacía o duplicada")
            seen.add(key)
            rows.append({"codigo": codigo, "unit_idx": unit_idx, "texto": texto})
    if not rows:
        raise ValueError(f"{path}: muestra vacía")
    return rows


def _validate_database_genre(connection: sqlite3.Connection, *, expected: str) -> None:
    row = connection.execute("SELECT config FROM runs LIMIT 1").fetchone()
    if row is None or not row["config"]:
        raise ValueError("la base no conserva configuración del run")
    try:
        config = json.loads(str(row["config"]))
        actual = config["_emoparse"]["genre"]["genre_id"]
    except (KeyError, TypeError, json.JSONDecodeError) as exc:
        raise ValueError("la base no conserva el snapshot de género") from exc
    if actual != expected:
        raise ValueError(f"la base declara género {actual!r}; se esperaba {expected!r}")


def _load_inputs(
    connection: sqlite3.Connection,
    codes: set[str],
) -> dict[str, dict[str, Any]]:
    placeholders = ",".join("?" for _ in codes)
    rows = connection.execute(
        f"SELECT codigo, input FROM discursos WHERE codigo IN ({placeholders})",
        sorted(codes),
    ).fetchall()
    result: dict[str, dict[str, Any]] = {}
    for row in rows:
        value = json.loads(str(row["input"]))
        if not isinstance(value, dict):
            raise ValueError(f"input inválido para {row['codigo']}")
        result[str(row["codigo"])] = value
    return result


def _load_units(
    connection: sqlite3.Connection,
    codes: set[str],
) -> dict[tuple[str, int], str]:
    placeholders = ",".join("?" for _ in codes)
    rows = connection.execute(
        f"SELECT codigo, unit_idx, frase FROM frases WHERE codigo IN ({placeholders})",
        sorted(codes),
    ).fetchall()
    return {(str(row["codigo"]), int(row["unit_idx"])): str(row["frase"]) for row in rows}


def _render_metadata(genre: str, payload: dict[str, Any]) -> str:
    fields = _ARTICLE_METADATA if genre == "articulo_periodistico" else _DISCOURSE_METADATA
    lines: list[str] = []
    for field, label in fields:
        value = _format_value(payload.get(field))
        if value:
            lines.append(f"{label}: {value}")
    return "\n".join(lines)


def _format_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        raw = value.strip()
        if not raw:
            return ""
        if raw.startswith("["):
            try:
                parsed = json.loads(raw)
            except json.JSONDecodeError:
                return raw
            if isinstance(parsed, list):
                return "; ".join(_text(item) for item in parsed if _text(item))
        return raw
    if isinstance(value, (list, tuple, set)):
        return "; ".join(_text(item) for item in value if _text(item))
    return _text(value)


def _context_item(
    *,
    relation: str,
    depth: int | None,
    codigo: str,
    unit_idx: int | None,
    text: str,
    date: str = "",
    url: str = "",
) -> dict[str, Any]:
    target_id = f"{codigo}#metadata" if unit_idx is None else f"{codigo}#unit-{unit_idx}"
    return {
        "relation": relation,
        "depth": depth,
        "target_id": target_id,
        "status": "resolved",
        "source": "document",
        "target": {
            "id": target_id,
            "autor_handle": "",
            "autor_display": "",
            "texto": text,
            "fecha": date,
            "url": url,
        },
    }


def _text(value: Any) -> str:
    return "" if value is None else str(value).strip()


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


__all__ = ["DocumentContextResult", "build_document_context_snapshot"]
