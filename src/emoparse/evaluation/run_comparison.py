# ══════════════════════════════════════════════════════════════════════════════
#  emoparse.evaluation.run_comparison
#
#  Lectura y comparación post-hoc de runs independientes del mismo corpus.
# ══════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

import hashlib
import itertools
import json
import re
import sqlite3
import unicodedata
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from emoparse.evaluation.agreement import krippendorff_alpha
from emoparse.genres.presentation import GenrePresentation, presentation_from_config

REFERENCE_MATCHES: tuple[str, ...] = (
    "identico",
    "mismo_canonico",
    "solapamiento_parcial",
    "distinto",
    "valor_ausente",
)

_ROLE_PREFIXES = (
    "enunciador",
    "enunciatario",
    "actor",
    "auditorio",
    "destinatario",
    "prodestinatario",
    "paradestinatario",
    "contradestinatario",
)
_TOKEN_RE = re.compile(r"[\w@]+", re.UNICODE)


@dataclass(frozen=True, slots=True)
class RunOverview:
    """Metadata necesaria para presentar y comparar un run."""

    path: Path
    run_id: str
    genre: str | None
    genre_source: str | None
    status: str | None
    versions: dict[str, str | None]
    notes: str
    configured_models: dict[str, str]
    observed_models: dict[str, tuple[str, ...]]
    mixed_stages: dict[str, tuple[str, ...]]
    latest_reports: dict[str, dict[str, Any]]
    corpus_signature: str
    units: int
    emotions: int


@dataclass(frozen=True, slots=True)
class RunComparison:
    """Resultado agregado de comparar dos o más runs."""

    run_names: tuple[str, ...]
    common_units: int
    same_corpus: bool
    corpus_signatures: dict[str, str]
    agreement: tuple[dict[str, Any], ...]
    reference_matches: tuple[dict[str, Any], ...]
    contract_violations: tuple[dict[str, Any], ...]


def load_run_overview(db_path: Path | str) -> RunOverview:
    """Lee metadata, routing observado y último reporte de un run."""
    path = Path(db_path).expanduser().resolve()
    with _connect_ro(path) as connection:
        run_row = _first_row(connection, "runs")
        config = _json_object(run_row.get("config") if run_row else None)
        presentation = presentation_from_config(config)
        genre, genre_source = _resolve_genre(connection, config, presentation)
        run_id = str((run_row or {}).get("run_id") or path.stem)
        configured = _configured_models(config)
        observed = _observed_models(connection, run_id)
        mixed = {stage: aliases for stage, aliases in observed.items() if len(aliases) > 1}
        reports = _latest_reports(connection, run_id)
        units = _count(connection, "frases")
        emotions = _count(connection, "emociones")
        signature = _corpus_signature(connection)
        versions = {
            "knowledge": _optional_text((run_row or {}).get("knowledge_version")),
            "prompt": _optional_text((run_row or {}).get("prompt_version")),
            "ontology": _optional_text((run_row or {}).get("ontology_version")),
            "schema": _optional_text((run_row or {}).get("schema_version")),
        }
        return RunOverview(
            path=path,
            run_id=run_id,
            genre=genre,
            genre_source=genre_source,
            status=_optional_text((run_row or {}).get("status")),
            versions=versions,
            notes=str((run_row or {}).get("notes") or ""),
            configured_models=configured,
            observed_models=observed,
            mixed_stages=mixed,
            latest_reports=reports,
            corpus_signature=signature,
            units=units,
            emotions=emotions,
        )


def compare_runs(db_paths: list[Path] | tuple[Path, ...]) -> RunComparison:
    """Compara acuerdo, referencias y obediencia al contrato entre runs."""
    paths = [Path(path).expanduser().resolve() for path in db_paths]
    if len(paths) < 2:
        raise ValueError("La comparación requiere al menos dos runs.")

    names = _unique_names(paths)
    unit_maps: dict[str, dict[tuple[str, int], str]] = {}
    emotion_maps: dict[str, dict[tuple[str, int], dict[int, dict[str, Any]]]] = {}
    signatures: dict[str, str] = {}
    for name, path in zip(names, paths, strict=True):
        with _connect_ro(path) as connection:
            unit_maps[name] = _load_units(connection)
            emotion_maps[name] = _load_emotions(connection)
            signatures[name] = _signature_for_units(unit_maps[name])

    common = set.intersection(*(set(units) for units in unit_maps.values()))
    common_units = sorted(common)
    max_slot = _max_slot(emotion_maps)
    agreement = _agreement_rows(names, common_units, emotion_maps, max_slot)
    references = _reference_rows(names, common_units, emotion_maps, max_slot)
    violations = _contract_violation_rows(names, emotion_maps)
    nonempty_signatures = {signature for signature in signatures.values() if signature}
    same_corpus = len(nonempty_signatures) == 1 and all(
        set(units) == set(next(iter(unit_maps.values()))) for units in unit_maps.values()
    )
    return RunComparison(
        run_names=tuple(names),
        common_units=len(common_units),
        same_corpus=same_corpus,
        corpus_signatures=signatures,
        agreement=tuple(agreement),
        reference_matches=tuple(references),
        contract_violations=tuple(violations),
    )


def classify_reference(
    left: str | None,
    right: str | None,
    *,
    left_canonical: str | None = None,
    right_canonical: str | None = None,
) -> str:
    """Clasifica el grado de coincidencia entre dos denominaciones."""
    left_surface = _surface_norm(left)
    right_surface = _surface_norm(right)
    if not left_surface or not right_surface:
        return "valor_ausente"
    if left_surface == right_surface:
        return "identico"

    left_canon = _canonical_norm(left_canonical) or _canonical_norm(left)
    right_canon = _canonical_norm(right_canonical) or _canonical_norm(right)
    if left_canon and right_canon and left_canon == right_canon:
        return "mismo_canonico"

    left_tokens = _tokens(left)
    right_tokens = _tokens(right)
    if left_tokens & right_tokens:
        return "solapamiento_parcial"
    return "distinto"


def is_role_label(value: str | None) -> bool:
    """True si el valor nombra una posición analítica y no un referente."""
    slug = _canonical_norm(value)
    if not slug:
        return False
    parts = slug.split("_")
    while parts and parts[0] in {"el", "la", "los", "las", "un", "una"}:
        parts.pop(0)
    normalized = "_".join(parts)
    return any(
        normalized == prefix or normalized.startswith(prefix + "_") for prefix in _ROLE_PREFIXES
    )


def _agreement_rows(
    names: list[str],
    units: list[tuple[str, int]],
    emotions: dict[str, dict[tuple[str, int], dict[int, dict[str, Any]]]],
    max_slot: int,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    presence_matrix = [
        ["si" if emotions[name].get(unit) else "no" for unit in units] for name in names
    ]
    rows.append(
        {
            "dimension": "hay_emocion",
            "alpha": krippendorff_alpha(presence_matrix, metric="nominal"),
            "items": len(units),
        }
    )
    dimensions = ("tipo", "experienciador", "fuente", "modo_existencia", "foria")
    positions = [(unit, slot) for unit in units for slot in range(max_slot + 1)]
    for dimension in dimensions:
        matrix = [
            [
                _emotion_value(emotions[name].get(unit, {}).get(slot), dimension)
                for unit, slot in positions
            ]
            for name in names
        ]
        rows.append(
            {
                "dimension": dimension,
                "alpha": krippendorff_alpha(matrix, metric="nominal"),
                "items": len(positions),
            }
        )
    return rows


def _reference_rows(
    names: list[str],
    units: list[tuple[str, int]],
    emotions: dict[str, dict[tuple[str, int], dict[int, dict[str, Any]]]],
    max_slot: int,
) -> list[dict[str, Any]]:
    counts: dict[tuple[str, str, str, str], int] = {}
    for left_name, right_name in itertools.combinations(names, 2):
        for unit in units:
            for slot in range(max_slot + 1):
                left_row = emotions[left_name].get(unit, {}).get(slot)
                right_row = emotions[right_name].get(unit, {}).get(slot)
                if left_row is None and right_row is None:
                    continue
                for field in ("experienciador", "fuente"):
                    left_raw, left_canon = _reference_values(left_row, field)
                    right_raw, right_canon = _reference_values(right_row, field)
                    grade = classify_reference(
                        left_raw,
                        right_raw,
                        left_canonical=left_canon,
                        right_canonical=right_canon,
                    )
                    key = (left_name, right_name, field, grade)
                    counts[key] = counts.get(key, 0) + 1
    return [
        {
            "run_a": left,
            "run_b": right,
            "dimension": field,
            "grado": grade,
            "n": count,
        }
        for (left, right, field, grade), count in sorted(counts.items())
    ]


def _contract_violation_rows(
    names: list[str],
    emotions: dict[str, dict[tuple[str, int], dict[int, dict[str, Any]]]],
) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for name in names:
        counts = {"experienciador": 0, "fuente": 0}
        examples: dict[str, set[str]] = {"experienciador": set(), "fuente": set()}
        for slots in emotions[name].values():
            for row in slots.values():
                for field in counts:
                    raw, canonical = _reference_values(row, field)
                    for value in (canonical, raw):
                        if is_role_label(value):
                            counts[field] += 1
                            examples[field].add(str(value))
                            break
        for field in counts:
            output.append(
                {
                    "run": name,
                    "dimension": field,
                    "violaciones": counts[field],
                    "ejemplos": ", ".join(sorted(examples[field])[:5]),
                }
            )
    return output


def _emotion_value(row: dict[str, Any] | None, dimension: str) -> str | None:
    if row is None:
        return None
    if dimension == "tipo":
        return _surface_norm(row.get("tipo_emocion_canonico") or row.get("tipo_emocion")) or None
    if dimension == "experienciador":
        raw, canonical = _reference_values(row, dimension)
        return _canonical_norm(canonical or raw) or None
    if dimension == "fuente":
        raw, canonical = _reference_values(row, dimension)
        return _canonical_norm(canonical or raw) or None
    if dimension == "modo_existencia":
        return _surface_norm(row.get("modo_existencia")) or None
    if dimension == "foria":
        payload = _json_object(row.get("caracterizacion_payload"))
        return _surface_norm(payload.get("foria")) or None
    raise ValueError(f"Dimensión desconocida: {dimension}")


def _reference_values(
    row: dict[str, Any] | None,
    field: str,
) -> tuple[str | None, str | None]:
    if row is None:
        return None, None
    if field == "experienciador":
        raw = row.get("experienciador")
        canonical = row.get("experienciador_canonico")
    elif field == "fuente":
        raw = row.get("fuente_inferencia") or row.get("fuente_marca")
        canonical = row.get("fuente_canonico")
    else:
        raise ValueError(f"Campo referencial desconocido: {field}")
    return _optional_text(raw), _optional_text(canonical)


@contextmanager
def _connect_ro(path: Path) -> Iterator[sqlite3.Connection]:
    connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    try:
        yield connection
    finally:
        connection.close()


def _table_exists(connection: sqlite3.Connection, table: str) -> bool:
    return (
        connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name = ?", (table,)
        ).fetchone()
        is not None
    )


def _columns(connection: sqlite3.Connection, table: str) -> set[str]:
    if not _table_exists(connection, table):
        return set()
    return {str(row["name"]) for row in connection.execute(f"PRAGMA table_info({table})")}


def _first_row(connection: sqlite3.Connection, table: str) -> dict[str, Any] | None:
    if not _table_exists(connection, table):
        return None
    row = connection.execute(f"SELECT * FROM {table} LIMIT 1").fetchone()
    return dict(row) if row is not None else None


def _count(connection: sqlite3.Connection, table: str) -> int:
    if not _table_exists(connection, table):
        return 0
    return int(connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])


def _resolve_genre(
    connection: sqlite3.Connection,
    config: dict[str, Any],
    presentation: GenrePresentation | None,
) -> tuple[str | None, str | None]:
    """Resuelve el género y conserva si proviene de un snapshot o de compatibilidad.

    Los runs creados antes de persistir ``_emoparse.genre`` no pueden exponer el
    género de forma directa. Para mantenerlos comparables se usan, en orden,
    marcas legacy de configuración y rasgos estructurales inequívocos del corpus.
    El fallback presidencial refleja el único género histórico de los runs
    clásicos anteriores al sistema de plugins y siempre se presenta como inferido.
    """
    if presentation is not None:
        return str(presentation.genre_id), "snapshot"

    configured = _genre_from_legacy_config(config)
    if configured:
        return configured, "config_legacy"

    if _table_has_rows(connection, "posts"):
        return "tuit", "estructura_posts"

    if _has_tuit_input_metadata(connection):
        return "tuit", "metadata_input_tuit"

    if _has_article_input_metadata(connection):
        return "articulo_periodistico", "metadata_input"

    if _table_has_rows(connection, "discursos"):
        return "discurso_presidencial", "fallback_historico"
    return None, None


def _genre_from_legacy_config(config: dict[str, Any]) -> str | None:
    candidates: list[Any] = [
        config.get("genre_id"),
        config.get("genre"),
        config.get("genero"),
    ]
    pipeline = config.get("pipeline")
    if isinstance(pipeline, dict):
        candidates.extend([pipeline.get("genre_id"), pipeline.get("genre"), pipeline.get("genero")])
    runtime = config.get("_emoparse")
    if isinstance(runtime, dict):
        raw = runtime.get("genre")
        if isinstance(raw, dict):
            candidates.append(raw.get("genre_id"))
        else:
            candidates.append(raw)

    for candidate in candidates:
        normalized = _normalize_genre_id(candidate)
        if normalized:
            return normalized
    return None


def _normalize_genre_id(value: Any) -> str | None:
    if isinstance(value, dict):
        value = value.get("genre_id") or value.get("id")
    raw = _canonical_norm(value)
    aliases = {
        "tuit": "tuit",
        "tweet": "tuit",
        "post": "tuit",
        "post_red_social": "tuit",
        "articulo": "articulo_periodistico",
        "articulo_periodistico": "articulo_periodistico",
        "discurso": "discurso_presidencial",
        "discurso_presidencial": "discurso_presidencial",
        "presidencial": "discurso_presidencial",
    }
    return aliases.get(raw)


def _table_has_rows(connection: sqlite3.Connection, table: str) -> bool:
    if not _table_exists(connection, table):
        return False
    return connection.execute(f"SELECT 1 FROM {table} LIMIT 1").fetchone() is not None


def _has_tuit_input_metadata(connection: sqlite3.Connection) -> bool:
    return _input_has_any_fields(
        connection,
        {"autor_handle", "autor_display", "tipo_post", "conversacion_id"},
    )


def _has_article_input_metadata(connection: sqlite3.Connection) -> bool:
    return _input_has_any_fields(
        connection,
        {"medio", "seccion", "volanta", "subtitulo", "autoria", "agencia", "epigrafe"},
    )


def _input_has_any_fields(connection: sqlite3.Connection, fields: set[str]) -> bool:
    if not _table_exists(connection, "discursos") or "input" not in _columns(
        connection, "discursos"
    ):
        return False
    rows = connection.execute("SELECT input FROM discursos LIMIT 50").fetchall()
    return any(fields & set(_json_object(row["input"])) for row in rows)


def _configured_models(config: dict[str, Any]) -> dict[str, str]:
    pipeline = config.get("pipeline")
    stages = pipeline.get("stages") if isinstance(pipeline, dict) else None
    if not isinstance(stages, dict):
        return {}
    return {str(stage): str(alias) for stage, alias in stages.items() if alias}


def _observed_models(
    connection: sqlite3.Connection,
    run_id: str,
) -> dict[str, tuple[str, ...]]:
    if "model_alias" not in _columns(connection, "run_metrics"):
        return {}
    rows = connection.execute(
        """
        SELECT stage_name, model_alias
        FROM run_metrics
        WHERE run_id = ? AND model_alias IS NOT NULL AND TRIM(model_alias) <> ''
        GROUP BY stage_name, model_alias
        ORDER BY stage_name, model_alias
        """,
        (run_id,),
    ).fetchall()
    grouped: dict[str, list[str]] = {}
    for row in rows:
        grouped.setdefault(str(row["stage_name"]), []).append(str(row["model_alias"]))
    return {stage: tuple(aliases) for stage, aliases in grouped.items()}


def _latest_reports(
    connection: sqlite3.Connection,
    run_id: str,
) -> dict[str, dict[str, Any]]:
    if not _table_exists(connection, "eval_reports"):
        return {}
    rows = connection.execute(
        """
        SELECT report_id, run_id, golden_version, recorded_at, payload
        FROM eval_reports
        WHERE run_id = ?
        ORDER BY recorded_at DESC, report_id DESC
        """,
        (run_id,),
    ).fetchall()
    latest: dict[str, dict[str, Any]] = {}
    for row in rows:
        output = dict(row)
        payload = _json_object(output.get("payload"))
        report_type = str(payload.get("report_type") or "golden")
        if report_type in latest:
            continue
        output["payload"] = payload
        latest[report_type] = output
    return latest


def _load_units(connection: sqlite3.Connection) -> dict[tuple[str, int], str]:
    if not _table_exists(connection, "frases"):
        return {}
    columns = _columns(connection, "frases")
    text_expr = "frase" if "frase" in columns else "''"
    rows = connection.execute(
        f"SELECT codigo, unit_idx, {text_expr} AS frase FROM frases ORDER BY codigo, unit_idx"
    ).fetchall()
    return {(str(row["codigo"]), int(row["unit_idx"])): str(row["frase"] or "") for row in rows}


def _load_emotions(
    connection: sqlite3.Connection,
) -> dict[tuple[str, int], dict[int, dict[str, Any]]]:
    if not _table_exists(connection, "emociones"):
        return {}
    rows = connection.execute(
        "SELECT * FROM emociones ORDER BY codigo, frase_idx, emocion_idx"
    ).fetchall()
    output: dict[tuple[str, int], dict[int, dict[str, Any]]] = {}
    for row in rows:
        item = dict(row)
        key = (str(item.get("codigo")), int(item.get("frase_idx") or 0))
        slot = int(item.get("emocion_idx") or 0)
        output.setdefault(key, {})[slot] = item
    return output


def _corpus_signature(connection: sqlite3.Connection) -> str:
    return _signature_for_units(_load_units(connection))


def _signature_for_units(units: dict[tuple[str, int], str]) -> str:
    if not units:
        return ""
    digest = hashlib.sha256()
    for (codigo, unit_idx), text in sorted(units.items()):
        digest.update(codigo.encode("utf-8"))
        digest.update(b"\0")
        digest.update(str(unit_idx).encode("ascii"))
        digest.update(b"\0")
        digest.update(text.encode("utf-8"))
        digest.update(b"\n")
    return digest.hexdigest()


def _max_slot(
    emotion_maps: dict[str, dict[tuple[str, int], dict[int, dict[str, Any]]]],
) -> int:
    slots = [slot for run in emotion_maps.values() for unit in run.values() for slot in unit]
    return max(slots, default=0)


def _unique_names(paths: list[Path]) -> list[str]:
    counts: dict[str, int] = {}
    names: list[str] = []
    for path in paths:
        base = path.stem
        counts[base] = counts.get(base, 0) + 1
        names.append(base if counts[base] == 1 else f"{base}-{counts[base]}")
    return names


def _json_object(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if not value:
        return {}
    try:
        parsed = json.loads(str(value))
    except (json.JSONDecodeError, TypeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _optional_text(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None


def _surface_norm(value: Any) -> str:
    text = unicodedata.normalize("NFKC", str(value or "")).casefold().strip()
    return " ".join(text.split())


def _canonical_norm(value: Any) -> str:
    text = _surface_norm(value)
    if not text:
        return ""
    normalized = unicodedata.normalize("NFKD", text)
    ascii_text = "".join(char for char in normalized if not unicodedata.combining(char))
    tokens = _TOKEN_RE.findall(ascii_text)
    return "_".join(token.strip("_").lower() for token in tokens if token.strip("_"))


def _tokens(value: Any) -> set[str]:
    canonical = _canonical_norm(value)
    return {token for token in canonical.split("_") if len(token) > 1}
