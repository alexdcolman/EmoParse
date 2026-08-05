"""Validación de las bases de origen del golden set v2."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from emoparse.evaluation.golden import load_run_genre

EXPECTED_GENRES: tuple[str, ...] = (
    "tuit",
    "articulo_periodistico",
    "discurso_presidencial",
)

MIN_UNITS_BY_GENRE: dict[str, int] = {
    "tuit": 200,
    "articulo_periodistico": 80,
    "discurso_presidencial": 200,
}


class CorpusValidationError(ValueError):
    """La base preparada no cumple el contrato del golden v2."""


@dataclass(frozen=True, slots=True)
class PreparedCorpusSummary:
    """Resumen verificable de una base preparada sin stages."""

    db_path: str
    run_id: str
    genre: str
    texts: int
    units: int
    authors: int | None
    conversations: int | None
    analytical_outputs: int
    sha256: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def summarize_prepared_corpus(db_path: Path | str) -> PreparedCorpusSummary:
    """Lee una DB en modo solo lectura y resume su cobertura."""
    path = Path(db_path).expanduser().resolve()
    if not path.is_file():
        raise CorpusValidationError(f"base no encontrada: {path}")

    genre = load_run_genre(path)
    if genre is None:
        raise CorpusValidationError(f"{path}: no conserva el género en runs.config")

    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        run_row = conn.execute("SELECT run_id FROM runs LIMIT 1").fetchone()
        if run_row is None:
            raise CorpusValidationError(f"{path}: no contiene una fila en runs")
        texts = _count(conn, "SELECT COUNT(*) FROM discursos")
        units = _count(conn, "SELECT COUNT(*) FROM frases")
        analytical_outputs = _count_analytical_outputs(conn)
        authors = None
        conversations = None
        if genre == "tuit":
            authors = _count(
                conn,
                "SELECT COUNT(DISTINCT autor_handle) FROM posts "
                "WHERE es_repost_puro = 0 AND TRIM(autor_handle) <> ''",
            )
            conversations = _count(
                conn,
                "SELECT COUNT(DISTINCT conversacion_id) FROM posts "
                "WHERE es_repost_puro = 0 AND TRIM(conversacion_id) <> ''",
            )
    finally:
        conn.close()

    return PreparedCorpusSummary(
        db_path=str(path),
        run_id=str(run_row["run_id"]),
        genre=genre,
        texts=texts,
        units=units,
        authors=authors,
        conversations=conversations,
        analytical_outputs=analytical_outputs,
        sha256=_sha256(path),
    )


def validate_golden_v2_corpus(
    summary: PreparedCorpusSummary,
    *,
    expected_genre: str,
) -> None:
    """Exige cobertura suficiente y ausencia de salidas analíticas."""
    errors: list[str] = []
    if summary.genre != expected_genre:
        errors.append(f"género {summary.genre!r}; se esperaba {expected_genre!r}")
    if summary.analytical_outputs:
        errors.append(
            f"contiene {summary.analytical_outputs} salidas analíticas; "
            "la base de origen debe estar preparada sin stages"
        )
    minimum_units = MIN_UNITS_BY_GENRE.get(expected_genre)
    if minimum_units is None:
        errors.append(f"género esperado sin umbral definido: {expected_genre!r}")
    elif summary.units < minimum_units:
        errors.append(
            f"solo contiene {summary.units} unidades; "
            f"se requieren al menos {minimum_units} para {expected_genre}"
        )

    if expected_genre == "tuit":
        if summary.texts != summary.units:
            errors.append(
                f"tiene {summary.texts} posts analizables y {summary.units} unidades; "
                "en tuit deben coincidir"
            )
        if (summary.authors or 0) < 15:
            errors.append(f"solo contiene {summary.authors or 0} autores; se requieren al menos 15")
    elif not 15 <= summary.texts <= 30:
        errors.append(
            f"contiene {summary.texts} textos; para {expected_genre} se requieren entre 15 y 30"
        )

    if errors:
        detail = "; ".join(errors)
        raise CorpusValidationError(f"{summary.db_path}: {detail}")


def validate_golden_v2_corpora(
    db_by_genre: dict[str, Path | str],
) -> dict[str, PreparedCorpusSummary]:
    """Valida las tres bases y devuelve sus resúmenes."""
    missing = [genre for genre in EXPECTED_GENRES if genre not in db_by_genre]
    extras = sorted(set(db_by_genre) - set(EXPECTED_GENRES))
    if missing or extras:
        raise CorpusValidationError(
            f"mapa de géneros inválido; faltan={missing or 'ninguno'}, sobran={extras or 'ninguno'}"
        )

    summaries: dict[str, PreparedCorpusSummary] = {}
    for genre in EXPECTED_GENRES:
        summary = summarize_prepared_corpus(db_by_genre[genre])
        validate_golden_v2_corpus(summary, expected_genre=genre)
        summaries[genre] = summary
    return summaries


def write_corpus_manifest(
    summaries: dict[str, PreparedCorpusSummary],
    output: Path | str,
) -> Path:
    """Escribe un manifiesto local de la preparación aprobada."""
    path = Path(output).expanduser().resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema": 1,
        "purpose": "golden_v2_source_runs",
        "created_at": datetime.now(UTC).isoformat(),
        "corpora": {genre: summary.to_dict() for genre, summary in summaries.items()},
    }
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return path


def _count(conn: sqlite3.Connection, query: str) -> int:
    row = conn.execute(query).fetchone()
    return int(row[0]) if row is not None else 0


def _count_analytical_outputs(conn: sqlite3.Connection) -> int:
    discourse = _count(
        conn,
        "SELECT COUNT(*) FROM discursos WHERE "
        "summarizer_payload IS NOT NULL OR metadata_payload IS NOT NULL "
        "OR enunciation_payload IS NOT NULL",
    )
    phrases = _count(
        conn,
        "SELECT COUNT(*) FROM frases WHERE actores_payload IS NOT NULL "
        "OR emociones_payload IS NOT NULL OR emociones_pass2_payload IS NOT NULL",
    )
    analysis_tables = (
        "run_metrics",
        "llm_cache",
        "validation_issues",
        "emociones",
        "judgments",
        "menciones",
        "mencion_funcion",
        "mencion_canonico",
        "canonico_semas",
        "tecno_entidades",
        "hashtags",
        "aristas",
        "red_metricas",
    )
    table_rows = sum(_count(conn, f"SELECT COUNT(*) FROM {table}") for table in analysis_tables)
    return discourse + phrases + table_rows


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
