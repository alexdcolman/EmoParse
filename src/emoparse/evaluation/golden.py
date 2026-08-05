# ══════════════════════════════════════════════════════════════════════════════
#  emoparse.evaluation.golden
#
#  Carga del golden set y de las emociones de uno o más runs.
# ══════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from emoparse.genres.presentation import presentation_from_config


class GoldenError(RuntimeError):
    """Golden set ilegible o malformado."""


@dataclass(frozen=True, slots=True)
class GoldenDataset:
    """Unidades del golden y género declarado para cada una."""

    units: dict[tuple[str, int], list[dict[str, Any]]]
    genres: dict[tuple[str, int], str | None]

    def genres_present(self) -> tuple[str, ...]:
        return tuple(sorted({genre for genre in self.genres.values() if genre}))

    def units_for_genre(self, genre: str) -> dict[tuple[str, int], list[dict[str, Any]]]:
        return {key: value for key, value in self.units.items() if self.genres.get(key) == genre}


def load_golden(path: Path | str) -> dict[tuple[str, int], list[dict[str, Any]]]:
    """Carga las emociones del golden preservando la API histórica."""
    return load_golden_dataset(path).units


def load_golden_dataset(path: Path | str) -> GoldenDataset:
    """Carga JSONL y conserva la metadata de género por unidad."""
    resolved = Path(path).expanduser().resolve()
    files = sorted(resolved.glob("*.jsonl")) if resolved.is_dir() else [resolved]
    if not files or not all(file.is_file() for file in files):
        raise GoldenError(f"Golden no encontrado en {resolved}")

    units: dict[tuple[str, int], list[dict[str, Any]]] = {}
    genres: dict[tuple[str, int], str | None] = {}
    for file in files:
        with file.open(encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, start=1):
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise GoldenError(f"{file}:{line_number}: {exc}") from exc
                if not isinstance(obj, dict):
                    raise GoldenError(f"{file}:{line_number}: cada línea debe ser un objeto JSON")

                codigo = str(obj.get("codigo") or "").strip()
                if not codigo:
                    raise GoldenError(f"{file}:{line_number}: falta `codigo`")
                try:
                    unit_idx = int(obj.get("unit_idx", 0))
                except (TypeError, ValueError) as exc:
                    raise GoldenError(f"{file}:{line_number}: `unit_idx` inválido") from exc
                key = (codigo, unit_idx)
                if key in units:
                    raise GoldenError(
                        f"{file}:{line_number}: unidad duplicada `{codigo}`[{unit_idx}]"
                    )

                emotions = obj.get("emociones")
                if not isinstance(emotions, list):
                    raise GoldenError(
                        f"{file}:{line_number}: `emociones` debe ser lista "
                        "(vacía para unidades sin emociones)"
                    )
                units[key] = [emotion for emotion in emotions if isinstance(emotion, dict)]
                genre_raw = obj.get("genero")
                genre = str(genre_raw).strip() if genre_raw is not None else ""
                genres[key] = genre or None
    return GoldenDataset(units=units, genres=genres)


def load_run_genre(db_path: Path | str) -> str | None:
    """Recupera el género persistido en ``runs.config``."""
    conn = sqlite3.connect(f"file:{Path(db_path)}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute("SELECT config FROM runs LIMIT 1").fetchone()
    except sqlite3.OperationalError:
        return None
    finally:
        conn.close()
    if row is None or not row["config"]:
        return None
    try:
        config = json.loads(str(row["config"]))
    except json.JSONDecodeError:
        return None
    presentation = presentation_from_config(config)
    return presentation.genre_id if presentation is not None else None


def load_run_emotions(
    db_path: Path | str,
    keys: set[tuple[str, int]] | None = None,
) -> dict[tuple[str, int], list[dict[str, Any]]]:
    """Emociones del run agrupadas por ``(codigo, unit_idx)``."""
    conn = sqlite3.connect(f"file:{Path(db_path)}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute("SELECT * FROM emociones").fetchall()
    finally:
        conn.close()

    output: dict[tuple[str, int], list[dict[str, Any]]] = {}
    for row in rows:
        key = (str(row["codigo"]), int(row["frase_idx"]))
        if keys is not None and key not in keys:
            continue
        emotion = dict(row)
        payload = emotion.get("caracterizacion_payload")
        if isinstance(payload, str) and payload:
            try:
                emotion["foria"] = json.loads(payload).get("foria")
            except json.JSONDecodeError:
                pass
        output.setdefault(key, []).append(emotion)
    if keys is not None:
        for key in keys:
            output.setdefault(key, [])
    return output
