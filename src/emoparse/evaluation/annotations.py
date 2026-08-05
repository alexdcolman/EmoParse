# ══════════════════════════════════════════════════════════════════════════════
#  emoparse.evaluation.annotations
#
#  Contrato de las planillas humanas y congelamiento del golden set.
# ══════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

import json
import random
from datetime import date
from pathlib import Path
from typing import Any

import pandas as pd

EMOTION_SLOTS = 3
EMOTION_FIELDS: tuple[str, ...] = (
    "experienciador",
    "tipo",
    "fuente",
    "modo_existencia",
    "foria",
)
ANNOTATION_METADATA_COLUMNS: tuple[str, ...] = (
    "anotador",
    "pasada",
    "fecha_anotacion",
)
BASE_SAMPLE_COLUMNS: tuple[str, ...] = (
    "id_muestra",
    "genero",
    "codigo",
    "unit_idx",
    "contexto",
    "texto",
)

_VALID_HAY_EMOCION = {
    "si": "si",
    "sí": "si",
    "s": "si",
    "1": "si",
    "no": "no",
    "n": "no",
    "0": "no",
}
_VALID_FORIA = {"euforico", "disforico", "aforico", "ambiforico", "indeterminado"}
_VALID_MODO = {"realizada", "potencial", "actual", "virtual"}


class AnnotationError(RuntimeError):
    """Planilla de anotación ilegible o incompleta."""


def annotation_columns() -> tuple[str, ...]:
    """Columnas que completa el anotador, en orden estable."""
    columns: list[str] = [*ANNOTATION_METADATA_COLUMNS, "hay_emocion"]
    for slot in range(1, EMOTION_SLOTS + 1):
        columns.extend(f"emocion_{slot}_{field}" for field in EMOTION_FIELDS)
    columns.append("dudas_comentarios")
    return tuple(columns)


ANNOTATION_COLUMNS = annotation_columns()
ANNOTATION_DECISION_COLUMNS: tuple[str, ...] = (
    "hay_emocion",
    *(
        f"emocion_{slot}_{field}"
        for slot in range(1, EMOTION_SLOTS + 1)
        for field in EMOTION_FIELDS
    ),
)


def validate_annotation_decisions(df: pd.DataFrame) -> None:
    """Valida presencia y coherencia de todas las decisiones humanas."""
    _require_columns(df, ANNOTATION_DECISION_COLUMNS)
    for row_number, row in enumerate(df.to_dict(orient="records"), start=2):
        hay = _normalizar_hay(_cell(row, "hay_emocion"), row_number)
        emotions = _row_emotions(row, row_number)
        if hay == "no" and emotions:
            raise AnnotationError(
                f"fila {row_number}: `hay_emocion=no` pero hay emociones completadas"
            )
        if hay == "si" and not emotions:
            raise AnnotationError(
                f"fila {row_number}: `hay_emocion=si` requiere al menos `emocion_1_*`"
            )


def freeze_annotations(
    csv_path: Path | str,
    *,
    annotator: str | None = None,
    pass_number: int | None = None,
    annotation_date: str | None = None,
    genre_override: str | None = None,
) -> list[dict[str, Any]]:
    """Convierte una planilla completa en registros JSONL del golden v2."""
    df = _read_csv(csv_path)
    _require_columns(df, (*BASE_SAMPLE_COLUMNS, *ANNOTATION_COLUMNS))
    validate_annotation_decisions(df)
    if annotation_date is not None:
        _validate_iso_date(annotation_date)
    if pass_number is not None and pass_number < 1:
        raise AnnotationError("`pasada` debe ser un entero mayor o igual que 1")
    if annotator is not None and not annotator.strip():
        raise AnnotationError("`anotador` no puede quedar vacío")

    records: list[dict[str, Any]] = []
    seen: set[tuple[str, int]] = set()
    seen_sample_ids: set[str] = set()
    for row_number, row in enumerate(df.to_dict(orient="records"), start=2):
        sample_id = _required_cell(row, "id_muestra", row_number)
        if sample_id in seen_sample_ids:
            raise AnnotationError(f"fila {row_number}: `id_muestra` duplicado `{sample_id}`")
        seen_sample_ids.add(sample_id)

        codigo = _required_cell(row, "codigo", row_number)
        unit_idx = _int_cell(row, "unit_idx", row_number, minimum=0)
        texto = _required_cell(row, "texto", row_number)
        key = (codigo, unit_idx)
        if key in seen:
            raise AnnotationError(f"fila {row_number}: unidad duplicada `{codigo}`[{unit_idx}]")
        seen.add(key)

        genre = (genre_override or _cell(row, "genero")).strip()
        if not genre:
            raise AnnotationError(
                f"fila {row_number}: falta `genero`; usá --genero para una base antigua"
            )

        row_annotator = (annotator or _cell(row, "anotador")).strip()
        if not row_annotator:
            raise AnnotationError(
                f"fila {row_number}: falta `anotador`; completalo o usá --anotador"
            )
        row_pass = (
            pass_number
            if pass_number is not None
            else _int_cell(row, "pasada", row_number, minimum=1)
        )
        row_date = annotation_date or _cell(row, "fecha_anotacion")
        if not row_date:
            raise AnnotationError(
                f"fila {row_number}: falta `fecha_anotacion`; completala o usá --fecha"
            )
        _validate_iso_date(row_date, row_number=row_number)

        hay = _normalizar_hay(_cell(row, "hay_emocion"), row_number)
        emociones = _row_emotions(row, row_number)

        records.append(
            {
                "id_muestra": sample_id,
                "codigo": codigo,
                "unit_idx": unit_idx,
                "genero": genre,
                "anotadores": [row_annotator],
                "fecha": row_date,
                "pasadas": [row_pass],
                "texto": texto,
                "contexto": _cell(row, "contexto"),
                "emociones": emociones,
                "dudas_comentarios": _cell(row, "dudas_comentarios"),
            }
        )
    return records


def write_golden_jsonl(records: list[dict[str, Any]], output_path: Path | str) -> None:
    """Escribe registros de golden como JSONL UTF-8, en orden recibido."""
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as file:
        for record in records:
            file.write(json.dumps(record, ensure_ascii=False, sort_keys=False) + "\n")


def make_reannotation_sample(
    csv_path: Path | str,
    *,
    n: int = 30,
    seed: int = 42,
) -> pd.DataFrame:
    """Extrae una segunda pasada ciega y borra todas las respuestas previas."""
    if n < 1:
        raise AnnotationError("`n` debe ser mayor o igual que 1")
    df = _read_csv(csv_path)
    _require_columns(df, (*BASE_SAMPLE_COLUMNS, *ANNOTATION_COLUMNS))
    completed = df[df["hay_emocion"].astype(str).str.strip() != ""].copy()
    if len(completed) != len(df):
        pending = len(df) - len(completed)
        raise AnnotationError(
            f"la planilla todavía tiene {pending} unidades sin completar en `hay_emocion`"
        )
    if len(completed) < n:
        raise AnnotationError(
            f"la planilla tiene {len(completed)} unidades anotadas y se pidieron {n}"
        )
    validate_annotation_decisions(completed)

    indices = list(completed.index)
    rng = random.Random(seed)
    selected_indices = rng.sample(indices, n)
    result = completed.loc[selected_indices].copy()
    result = result.sample(frac=1, random_state=seed).reset_index(drop=True)

    for column in ANNOTATION_COLUMNS:
        result[column] = ""
    result["pasada"] = "2"
    return result


def coder_id(row: dict[str, Any]) -> str:
    """Identificador de codificador: anotador y pasada forman juicios distintos."""
    annotator = _cell(row, "anotador")
    pass_number = _cell(row, "pasada")
    if not annotator:
        return ""
    return f"{annotator}/pasada-{pass_number}" if pass_number else annotator


def _read_csv(path: Path | str) -> pd.DataFrame:
    try:
        return pd.read_csv(path, dtype=str, keep_default_na=False)
    except (OSError, pd.errors.ParserError) as exc:
        raise AnnotationError(f"CSV de anotación ilegible: {exc}") from exc


def _require_columns(df: pd.DataFrame, columns: tuple[str, ...]) -> None:
    missing = [column for column in columns if column not in df.columns]
    if missing:
        raise AnnotationError(f"faltan columnas requeridas: {', '.join(missing)}")


def _row_emotions(row: dict[str, Any], row_number: int) -> list[dict[str, str]]:
    emotions: list[dict[str, str]] = []
    empty_slot_seen = False
    for slot in range(1, EMOTION_SLOTS + 1):
        values = {field: _cell(row, f"emocion_{slot}_{field}") for field in EMOTION_FIELDS}
        if not any(values.values()):
            empty_slot_seen = True
            continue
        if empty_slot_seen:
            raise AnnotationError(
                f"fila {row_number}: los slots de emoción deben completarse sin huecos"
            )
        missing = [field for field, value in values.items() if not value]
        if missing:
            raise AnnotationError(f"fila {row_number}, emoción {slot}: faltan {', '.join(missing)}")

        foria = values["foria"].lower()
        modo = values["modo_existencia"].lower()
        if foria not in _VALID_FORIA:
            raise AnnotationError(
                f"fila {row_number}, emoción {slot}: foria inválida `{values['foria']}`"
            )
        if modo not in _VALID_MODO:
            raise AnnotationError(
                f"fila {row_number}, emoción {slot}: modo inválido `{values['modo_existencia']}`"
            )

        emotions.append(
            {
                "experienciador": values["experienciador"],
                "tipo_emocion": values["tipo"],
                "fuente": values["fuente"],
                "modo_existencia": modo,
                "foria": foria,
            }
        )
    return emotions


def _normalizar_hay(value: str, row_number: int) -> str:
    normalized = _VALID_HAY_EMOCION.get(value.strip().lower())
    if normalized is None:
        raise AnnotationError(
            f"fila {row_number}: `hay_emocion` debe ser `si` o `no`, no `{value}`"
        )
    return normalized


def _cell(row: dict[str, Any], column: str) -> str:
    value = row.get(column, "")
    return "" if value is None else str(value).strip()


def _required_cell(row: dict[str, Any], column: str, row_number: int) -> str:
    value = _cell(row, column)
    if not value:
        raise AnnotationError(f"fila {row_number}: `{column}` no puede quedar vacío")
    return value


def _int_cell(
    row: dict[str, Any],
    column: str,
    row_number: int,
    *,
    minimum: int | None = None,
) -> int:
    raw = _cell(row, column)
    try:
        value = int(raw)
    except ValueError as exc:
        raise AnnotationError(f"fila {row_number}: `{column}` inválido: `{raw}`") from exc
    if minimum is not None and value < minimum:
        raise AnnotationError(f"fila {row_number}: `{column}` debe ser mayor o igual que {minimum}")
    return value


def _validate_iso_date(value: str, *, row_number: int | None = None) -> None:
    try:
        date.fromisoformat(value)
    except ValueError as exc:
        prefix = f"fila {row_number}: " if row_number is not None else ""
        raise AnnotationError(f"{prefix}`fecha` debe usar formato AAAA-MM-DD") from exc
