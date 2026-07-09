# ══════════════════════════════════════════════════════════════════════════════
#  emoparse.app.data
#
#  Capa de acceso a datos para la UI Streamlit.
#
#  Expone funciones puras que reciben un `db_path` y devuelven
#  DataFrames listos para visualización.
#
#  Convenciones:
#  - acceso exclusivamente read-only sobre SQLite
#  - cada función abre y cierra su propia conexión
#  - siempre devuelve DataFrames (incluso vacíos)
#  - los payloads JSON se expanden aquí para evitar que la UI
#    trabaje con strings JSON crudos
# ══════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd
from loguru import logger

#: Import side-effect: registra adaptadores/converters SQLite para
#: datetime en formato ISO 8601. Esto asegura compatibilidad con
#: `detect_types=PARSE_DECLTYPES` al leer timestamps persistidos por
#: la capa de storage.
import emoparse.storage.db  # noqa: F401  (side-effect import)

#: Importado desde el runner para mantener una única fuente de verdad
#: sobre el orden y definición de stages.
from emoparse.pipeline.runner import STAGE_ORDER


# ══════════════════════════════════════════════════════════════════════════════
#  Tipos públicos
# ══════════════════════════════════════════════════════════════════════════════

@dataclass(frozen=True, slots=True)
class RunInfo:
    """Metadata mínima de un run para listado en sidebar.

    `path` es la ruta absoluta del archivo SQLite.
    `name` corresponde al nombre visible del run.
    `n_discursos` y `n_frases` permiten mostrar tamaño estimado sin
    necesidad de abrir la vista completa.
    """
    path: Path
    name: str
    run_id: str | None
    started_at: datetime | None
    status: str | None  # 'running' | 'completed' | 'failed' | None
    n_discursos: int
    n_frases: int


@dataclass(frozen=True, slots=True)
class StageStatus:
    """Estado agregado de una stage dentro de un run.

    `failed_codigos` contiene los identificadores concretos utilizados
    por la UI para mostrar qué discursos presentan fallos.
    """
    stage: str
    pending: int
    failed: int
    completed: int
    failed_codigos: list[str]


# ══════════════════════════════════════════════════════════════════════════════
#  Stages — agrupadas por nivel de granularidad
#
#  La granularidad del schema determina cómo se calcula el estado de
#  cada stage: por discurso, por frase o por emoción individual.
# ══════════════════════════════════════════════════════════════════════════════

#: Stages que persisten en la tabla `discursos` (1 row = 1 discurso).
_DISCURSO_STAGES: frozenset[str] = frozenset({"summarizer", "metadata", "enunciation"})

#: Stages que persisten en la tabla `frases` (1 row = 1 frase).
#: `emotions_pass2` también vive aquí, en columnas `emociones_pass2_*`.
_FRASE_STAGES: frozenset[str] = frozenset({"actors", "emotions", "emotions_pass2"})

#: Stage no-LLM que materializa la tabla `emociones` a partir del
#: payload de emociones detectadas en `frases`.
_EXPLODE_STAGE: str = "explode_emotions"

#: Stage que escribe en la tabla `emociones`. Su completitud se mide a
#: nivel emoción (1 row = 1 emoción individual).
_EMOCION_STAGES: frozenset[str] = frozenset({"characterizer"})

#: Mapping stage → columna persistida en `frases`.
#: Se mantiene explícito para evitar reflection dinámica sobre schema.
_FRASE_STAGE_COL: dict[str, str] = {
    "actors": "actores",
    "emotions": "emociones",
    "emotions_pass2": "emociones_pass2",
}


# ══════════════════════════════════════════════════════════════════════════════
#  Conexión read-only
# ══════════════════════════════════════════════════════════════════════════════

@contextmanager
def _ro_connect(db_path: Path) -> Iterator[sqlite3.Connection]:
    """Abre una conexión SQLite en modo read-only.

    El modo URI con `mode=ro` impide operaciones de escritura y refuerza
    el contrato de solo lectura de esta capa.
    """
    uri = f"file:{db_path}?mode=ro"
    conn = sqlite3.connect(uri, uri=True, detect_types=sqlite3.PARSE_DECLTYPES)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()


# ══════════════════════════════════════════════════════════════════════════════
#  Listado de runs
# ══════════════════════════════════════════════════════════════════════════════

def list_runs(runs_dir: Path) -> list[RunInfo]:
    """Devuelve los runs disponibles en `runs_dir`, ordenados por fecha.

    Si un archivo `.sqlite` no puede inspeccionarse correctamente, se
    incluye igualmente con metadata vacía y `status=None`.
    """
    runs_dir = Path(runs_dir)
    if not runs_dir.exists():
        return []

    out: list[RunInfo] = []
    for sqlite_path in sorted(runs_dir.glob("*.sqlite")):
        out.append(_inspect_run(sqlite_path))

    # Ordenar por fecha descendente; los runs sin timestamp quedan al final.
    out.sort(
        key=lambda r: (r.started_at is None, -(r.started_at.timestamp() if r.started_at else 0))
    )
    return out


def _inspect_run(sqlite_path: Path) -> RunInfo:
    """Inspecciona un archivo SQLite y extrae metadata mínima del run.

    Es tolerante a errores de lectura y devuelve metadata vacía si la
    inspección falla.
    """
    name = sqlite_path.stem
    try:
        with _ro_connect(sqlite_path) as conn:
            run_row = conn.execute(
                "SELECT run_id, started_at, status FROM runs LIMIT 1"
            ).fetchone()
            n_d = conn.execute("SELECT COUNT(*) AS n FROM discursos").fetchone()["n"]
            n_f = conn.execute("SELECT COUNT(*) AS n FROM frases").fetchone()["n"]
        if run_row is None:
            return RunInfo(
                path=sqlite_path, name=name,
                run_id=None, started_at=None, status=None,
                n_discursos=n_d, n_frases=n_f,
            )
        return RunInfo(
            path=sqlite_path,
            name=name,
            run_id=run_row["run_id"],
            started_at=run_row["started_at"],
            status=run_row["status"],
            n_discursos=n_d,
            n_frases=n_f,
        )
    except sqlite3.Error as e:
        logger.warning(f"[app.data] No se pudo inspeccionar {sqlite_path}: {e}")
        return RunInfo(
            path=sqlite_path, name=name,
            run_id=None, started_at=None, status=None,
            n_discursos=0, n_frases=0,
        )


# ══════════════════════════════════════════════════════════════════════════════
#  Stats por run
# ══════════════════════════════════════════════════════════════════════════════

def get_run_stats(db_path: Path) -> dict[str, Any]:
    """Devuelve el resumen de metadata general de un run.

    Se utiliza para renderizar el header informativo del sidebar.
    """
    with _ro_connect(db_path) as conn:
        run_row = conn.execute(
            "SELECT run_id, started_at, finished_at, status, "
            "knowledge_version, prompt_version, ontology_version, schema_version, notes "
            "FROM runs LIMIT 1"
        ).fetchone()
        n_d = conn.execute("SELECT COUNT(*) AS n FROM discursos").fetchone()["n"]
        n_f = conn.execute("SELECT COUNT(*) AS n FROM frases").fetchone()["n"]
        n_e = conn.execute("SELECT COUNT(*) AS n FROM emociones").fetchone()["n"]

    return {
        "run_id":            run_row["run_id"] if run_row else None,
        "started_at":        run_row["started_at"] if run_row else None,
        "finished_at":       run_row["finished_at"] if run_row else None,
        "status":            run_row["status"] if run_row else None,
        "knowledge_version": run_row["knowledge_version"] if run_row else None,
        "prompt_version":    run_row["prompt_version"] if run_row else None,
        "ontology_version":  run_row["ontology_version"] if run_row else None,
        "schema_version":    run_row["schema_version"] if run_row else None,
        "notes":             (run_row["notes"] if run_row else None) or "",
        "n_discursos":       n_d,
        "n_frases":          n_f,
        "n_emociones":       n_e,
    }


# ══════════════════════════════════════════════════════════════════════════════
#  Discursos: un row por discurso, payloads desplegados
# ══════════════════════════════════════════════════════════════════════════════

def get_discursos(db_path: Path) -> pd.DataFrame:
    """Devuelve una fila por discurso con input y payloads de stages a nivel discurso.

    Los payloads JSON se expanden a columnas con el prefijo
    `<stage>__<campo>`, lo que evita exponer strings JSON crudos en la UI
    y permite filtrado directo por columna.

    Las columnas generadas dependen de la estructura de cada payload.
    Por ejemplo, un payload con `tipo_discurso` y `ciudad` produce
    columnas como `metadata__tipo_discurso` y `metadata__ciudad`.

    Si existen diferencias de estructura entre discursos, pandas completa
    las columnas faltantes con valores NaN.
    """
    with _ro_connect(db_path) as conn:
        rows = conn.execute(
            "SELECT codigo, input, "
            "summarizer_payload, summarizer_version, summarizer_error, "
            "metadata_payload, metadata_version, metadata_error, "
            "enunciation_payload, enunciation_version, enunciation_error, "
            "created_at, updated_at "
            "FROM discursos ORDER BY codigo"
        ).fetchall()

    if not rows:
        return pd.DataFrame()

    records: list[dict[str, Any]] = []
    for row in rows:
        rec: dict[str, Any] = {"codigo": row["codigo"]}
        # Input desplegado.
        rec.update(_unpack_json_dict(row["input"], prefix="input__"))
        # Stages.
        for stage in ("summarizer", "metadata", "enunciation"):
            payload_str = row[f"{stage}_payload"]
            error = row[f"{stage}_error"]
            rec[f"{stage}__status"] = _stage_status_from(payload_str, error)
            if payload_str:
                rec.update(_unpack_json_dict(payload_str, prefix=f"{stage}__"))
            if error:
                rec[f"{stage}__error"] = error
        rec["created_at"] = row["created_at"]
        rec["updated_at"] = row["updated_at"]
        records.append(rec)

    return pd.DataFrame.from_records(records)


# ══════════════════════════════════════════════════════════════════════════════
#  Frases: un row por frase, con actores y emociones (no exploded)
# ══════════════════════════════════════════════════════════════════════════════

def get_frases(
    db_path: Path,
    codigos: list[str] | None = None,
) -> pd.DataFrame:
    """Devuelve una fila por frase con actores y emociones deserializados.

    Los payloads JSON se convierten a estructuras Python (`list` / `dict`)
    para que la UI pueda iterarlos sin parseo adicional.

    Si `codigos` se especifica, limita la consulta a esos discursos.

    Para análisis a nivel emoción individual debe usarse `get_emociones`.
    """
    sql, params = _build_filter_sql(
        base="SELECT codigo, unit_idx, frase, "
             "actores_payload, actores_error, "
             "emociones_payload, emociones_error, "
             "emociones_pass2_payload, emociones_pass2_error "
             "FROM frases",
        column="codigo",
        values=codigos,
        order_by="codigo, unit_idx",
    )

    with _ro_connect(db_path) as conn:
        rows = conn.execute(sql, params).fetchall()

    if not rows:
        return pd.DataFrame()

    records: list[dict[str, Any]] = []
    for row in rows:
        records.append({
            "codigo":                  row["codigo"],
            "unit_idx":                row["unit_idx"],
            "frase":                   row["frase"],
            "actores":                 _parse_json(row["actores_payload"]),
            "actores_error":           row["actores_error"],
            "emociones":               _parse_json(row["emociones_payload"]),
            "emociones_error":         row["emociones_error"],
            "emociones_pass2":         _parse_json(row["emociones_pass2_payload"]),
            "emociones_pass2_error":   row["emociones_pass2_error"],
        })

    return pd.DataFrame.from_records(records)


# ══════════════════════════════════════════════════════════════════════════════
#  Emociones: un row por emoción individual (post-explode + caracterización)
# ══════════════════════════════════════════════════════════════════════════════

def get_emociones(
    db_path: Path,
    codigos: list[str] | None = None,
) -> pd.DataFrame:
    """Devuelve una fila por emoción individual.

    Es la fuente principal para visualizaciones analíticas como curva
    emocional, comparación entre discursos y análisis por actor.

    Incluye la caracterización expandida (foria, intensidad, dominancia,
    etc.) y metadata contextual de frase y discurso.
    """
    sql, params = _build_filter_sql(
        base="SELECT e.codigo, e.frase_idx, e.emocion_idx, "
             "e.experienciador, e.experienciador_marca, "
             "e.tipo_emocion, e.tipo_emocion_canonico, "
             "e.fuente_marca, e.fuente_inferencia, "
             "e.modo_existencia, "
             "e.caracterizacion_payload, e.caracterizacion_error, "
             "f.frase, "
             "d.input "
             "FROM emociones e "
             "LEFT JOIN frases f ON e.codigo = f.codigo AND e.frase_idx = f.unit_idx "
             "LEFT JOIN discursos d ON e.codigo = d.codigo",
        column="e.codigo",
        values=codigos,
        order_by="e.codigo, e.frase_idx, e.emocion_idx",
    )

    with _ro_connect(db_path) as conn:
        rows = conn.execute(sql, params).fetchall()

    if not rows:
        return pd.DataFrame()

    records: list[dict[str, Any]] = []
    for row in rows:
        rec: dict[str, Any] = {
            "codigo":                  row["codigo"],
            "frase_idx":               row["frase_idx"],
            "emocion_idx":             row["emocion_idx"],
            "experienciador":          row["experienciador"],
            "experienciador_marca":    row["experienciador_marca"],
            "tipo_emocion":            row["tipo_emocion"],
            "tipo_emocion_canonico":   row["tipo_emocion_canonico"],
            "modo_existencia":         row["modo_existencia"],
            "fuente_marca":            row["fuente_marca"],
            "fuente_inferencia":       row["fuente_inferencia"],
            "frase":                   row["frase"],
            "caracterizacion_error":   row["caracterizacion_error"],
        }
        # Caracterización flat: foria, dominancia, intensidad, etc.
        rec.update(_unpack_json_dict(row["caracterizacion_payload"], prefix=""))
        # Metadata del discurso (título, fecha).
        input_data = _parse_json(row["input"])
        if isinstance(input_data, dict):
            for key in ("titulo", "fecha", "url"):
                if key in input_data:
                    rec[f"discurso__{key}"] = input_data[key]
        records.append(rec)

    return pd.DataFrame.from_records(records)


# ══════════════════════════════════════════════════════════════════════════════
#  Revisión: header de discurso + emociones con payloads crudos
# ══════════════════════════════════════════════════════════════════════════════

def get_discurso_header(db_path: Path, codigo: str) -> dict[str, Any]:
    """Datos de cabecera de un discurso (una sola vez, no por frase).

    Combina input (título/fecha), metadata (tipo de discurso, lugar) y
    enunciación (enunciador, enunciatarios).
    """
    with _ro_connect(db_path) as conn:
        row = conn.execute(
            "SELECT codigo, input, metadata_payload, enunciation_payload "
            "FROM discursos WHERE codigo = ?",
            (codigo,),
        ).fetchone()
    if row is None:
        return {}
    inp = _parse_json(row["input"]) or {}
    meta = _parse_json(row["metadata_payload"]) or {}
    enun = _parse_json(row["enunciation_payload"]) or {}
    lugar_parts = [
        meta.get(k) for k in ("ciudad", "provincia", "pais")
        if meta.get(k) and str(meta.get(k)).lower() != "no identificado"
    ]
    return {
        "codigo": codigo,
        "titulo": inp.get("titulo") if isinstance(inp, dict) else None,
        "fecha": inp.get("fecha") if isinstance(inp, dict) else None,
        "tipo_discurso": meta.get("tipo_discurso"),
        "lugar": ", ".join(str(p) for p in lugar_parts) if lugar_parts else None,
        "enunciador": enun.get("enunciador"),
        "enunciatarios": enun.get("enunciatarios"),
    }


def get_actores_por_frase(db_path: Path, codigo: str) -> dict[int, list[dict[str, Any]]]:
    """Actores por frase con su canónico, desde la base de marcas.

    {unit_idx: [{actor_mencionado, actor_canonico, es_nuevo}]}. Toma las marcas
    con función 'actor'; el canónico aceptado prima sobre el propuesto, y si una
    marca no tiene ninguno, queda como nueva (`es_nuevo=True`).
    """
    out: dict[int, list[dict[str, Any]]] = {}
    with _ro_connect(db_path) as conn:
        ok = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='menciones'"
        ).fetchone()
        if ok is None:
            return out
        rows = conn.execute(
            "SELECT m.unit_idx AS unit_idx, m.marca AS marca, "
            "  (SELECT mc.canonical_id FROM mencion_canonico mc "
            "     WHERE mc.mencion_id = m.id AND mc.status != 'rejected' "
            "     ORDER BY (mc.status = 'accepted') DESC LIMIT 1) AS canonical "
            "FROM menciones m "
            "JOIN mencion_funcion mf ON mf.mencion_id = m.id AND mf.funcion = 'actor' "
            "WHERE m.codigo = ? ORDER BY m.unit_idx, m.id",
            (codigo,),
        ).fetchall()
    for r in rows:
        out.setdefault(int(r["unit_idx"]), []).append({
            "actor_mencionado": r["marca"],
            "actor_canonico": r["canonical"],
            "es_nuevo": r["canonical"] is None,
        })
    return out


def get_emociones_full(db_path: Path, codigo: str) -> list[dict[str, Any]]:
    """Emociones de un discurso con sus payloads crudos para revisión.

    Por cada emoción: campos base + caracterización (dict) + actantes (dict) +
    juicio (si existe). Indexable por (frase_idx, emocion_idx).
    """
    with _ro_connect(db_path) as conn:
        rows = conn.execute(
            "SELECT e.codigo, e.frase_idx, e.emocion_idx, "
            "e.experienciador, e.experienciador_marca, e.experienciador_canonico, "
            "e.tipo_emocion, e.tipo_emocion_canonico, "
            "e.fuente_marca, e.fuente_inferencia, "
            "e.modo_existencia, e.tipo_configuracion, "
            "e.caracterizacion_payload, e.actantes_payload, "
            "j.coherente, j.issues, j.confianza, j.sugerencias "
            "FROM emociones e "
            "LEFT JOIN judgments j ON e.codigo = j.codigo "
            "AND e.frase_idx = j.frase_idx AND e.emocion_idx = j.emocion_idx "
            "WHERE e.codigo = ? "
            "ORDER BY e.frase_idx, e.emocion_idx",
            (codigo,),
        ).fetchall()
    out: list[dict[str, Any]] = []
    for row in rows:
        coherente = row["coherente"]
        out.append({
            "frase_idx": row["frase_idx"],
            "emocion_idx": row["emocion_idx"],
            "experienciador": row["experienciador"],
            "experienciador_marca": row["experienciador_marca"],
            "experienciador_canonico": row["experienciador_canonico"],
            "tipo_emocion": row["tipo_emocion"],
            "tipo_emocion_canonico": row["tipo_emocion_canonico"],
            "fuente_marca": row["fuente_marca"],
            "fuente_inferencia": row["fuente_inferencia"],
            "modo_existencia": row["modo_existencia"],
            "tipo_configuracion": row["tipo_configuracion"],
            "caracterizacion": _parse_json(row["caracterizacion_payload"]) or {},
            "actantes": _parse_json(row["actantes_payload"]) or {},
            "juicio": (
                None if coherente is None and row["issues"] is None
                else {
                    "coherente": (None if coherente is None else bool(coherente)),
                    "issues": row["issues"],
                    "confianza": row["confianza"],
                    "sugerencias": _parse_json(row["sugerencias"]) or [],
                }
            ),
        })
    return out


# ══════════════════════════════════════════════════════════════════════════════
#  Estado del run: pending/failed/completed por stage
# ══════════════════════════════════════════════════════════════════════════════

def get_stage_statuses(db_path: Path) -> list[StageStatus]:
    """Devuelve un StageStatus por cada stage definida en STAGE_ORDER.

    El criterio de conteo depende de la granularidad de cada stage:

        - stages de discurso: 1 unidad = 1 discurso
        - stages de frase: 1 unidad = 1 frase
        - explode_emotions: cuenta discursos con `emociones_payload`
            que ya tienen filas materializadas en `emociones`
        - characterizer: 1 unidad = 1 emoción individual
    """
    out: list[StageStatus] = []
    with _ro_connect(db_path) as conn:
        for stage in STAGE_ORDER:
            if stage in _DISCURSO_STAGES:
                out.append(_count_discurso_stage(conn, stage))
            elif stage in _FRASE_STAGES:
                out.append(_count_frase_stage(conn, stage))
            elif stage == _EXPLODE_STAGE:
                out.append(_count_explode_stage(conn))
            elif stage in _EMOCION_STAGES:
                out.append(_count_characterizer_stage(conn))
            else:  # pragma: no cover — defensa contra stages nuevas no mapeadas
                out.append(StageStatus(
                    stage=stage, pending=0, failed=0, completed=0,
                    failed_codigos=[],
                ))
    return out


def _count_discurso_stage(conn: sqlite3.Connection, stage: str) -> StageStatus:
    """Calcula el estado de una stage que escribe en `discursos`."""
    col_p = f"{stage}_payload"
    col_e = f"{stage}_error"
    pending = conn.execute(
        f"SELECT COUNT(*) AS n FROM discursos "
        f"WHERE {col_p} IS NULL AND {col_e} IS NULL"
    ).fetchone()["n"]
    failed = conn.execute(
        f"SELECT COUNT(*) AS n FROM discursos WHERE {col_e} IS NOT NULL"
    ).fetchone()["n"]
    completed = conn.execute(
        f"SELECT COUNT(*) AS n FROM discursos WHERE {col_p} IS NOT NULL"
    ).fetchone()["n"]
    failed_codigos = [
        r["codigo"] for r in conn.execute(
            f"SELECT codigo FROM discursos WHERE {col_e} IS NOT NULL "
            f"ORDER BY codigo LIMIT 50"
        ).fetchall()
    ]
    return StageStatus(
        stage=stage, pending=pending, failed=failed, completed=completed,
        failed_codigos=failed_codigos,
    )


def _count_frase_stage(conn: sqlite3.Connection, stage: str) -> StageStatus:
    """Conteo para stages que escriben en `frases`.

    `failed_codigos` se agrupa por discurso: si varias frases fallan
    dentro del mismo discurso, el código aparece una sola vez.
    """
    col = _FRASE_STAGE_COL[stage]
    col_p = f"{col}_payload"
    col_e = f"{col}_error"
    pending = conn.execute(
        f"SELECT COUNT(*) AS n FROM frases "
        f"WHERE {col_p} IS NULL AND {col_e} IS NULL"
    ).fetchone()["n"]
    failed = conn.execute(
        f"SELECT COUNT(*) AS n FROM frases WHERE {col_e} IS NOT NULL"
    ).fetchone()["n"]
    completed = conn.execute(
        f"SELECT COUNT(*) AS n FROM frases WHERE {col_p} IS NOT NULL"
    ).fetchone()["n"]
    failed_codigos = [
        r["codigo"] for r in conn.execute(
            f"SELECT DISTINCT codigo FROM frases WHERE {col_e} IS NOT NULL "
            f"ORDER BY codigo LIMIT 50"
        ).fetchall()
    ]
    return StageStatus(
        stage=stage, pending=pending, failed=failed, completed=completed,
        failed_codigos=failed_codigos,
    )


def _count_explode_stage(conn: sqlite3.Connection) -> StageStatus:
    """Conteo para `explode_emotions`.

    No existe una columna propia de estado; se mide verificando cuántos
    discursos con `emociones_payload` ya tienen filas materializadas en
    la tabla `emociones`.
    """
    pending = conn.execute(
        "SELECT COUNT(DISTINCT f.codigo) AS n FROM frases f "
        "WHERE f.emociones_payload IS NOT NULL "
        "AND NOT EXISTS (SELECT 1 FROM emociones e WHERE e.codigo = f.codigo)"
    ).fetchone()["n"]
    completed = conn.execute(
        "SELECT COUNT(DISTINCT codigo) AS n FROM emociones"
    ).fetchone()["n"]
    return StageStatus(
        stage=_EXPLODE_STAGE, pending=pending, failed=0, completed=completed,
        failed_codigos=[],
    )


def _count_characterizer_stage(conn: sqlite3.Connection) -> StageStatus:
    """Conteo para `characterizer` (escribe en `emociones`)."""
    pending = conn.execute(
        "SELECT COUNT(*) AS n FROM emociones "
        "WHERE caracterizacion_payload IS NULL AND caracterizacion_error IS NULL"
    ).fetchone()["n"]
    failed = conn.execute(
        "SELECT COUNT(*) AS n FROM emociones WHERE caracterizacion_error IS NOT NULL"
    ).fetchone()["n"]
    completed = conn.execute(
        "SELECT COUNT(*) AS n FROM emociones WHERE caracterizacion_payload IS NOT NULL"
    ).fetchone()["n"]
    failed_codigos = [
        r["codigo"] for r in conn.execute(
            "SELECT DISTINCT codigo FROM emociones WHERE caracterizacion_error IS NOT NULL "
            "ORDER BY codigo LIMIT 50"
        ).fetchall()
    ]
    return StageStatus(
        stage="characterizer", pending=pending, failed=failed, completed=completed,
        failed_codigos=failed_codigos,
    )


# ══════════════════════════════════════════════════════════════════════════════
#  Helpers internos
# ══════════════════════════════════════════════════════════════════════════════

def _parse_json(s: str | None) -> Any:
    """Parsea un string JSON a su valor Python, o None si vacío."""
    if not s:
        return None
    try:
        return json.loads(s)
    except json.JSONDecodeError as e:
        logger.warning(f"[app.data] JSON inválido en DB: {e}")
        return None


def _unpack_json_dict(s: str | None, prefix: str) -> dict[str, Any]:
    """Expande un JSON object plano a un dict con claves prefijadas.

    Si el valor no es un objeto plano, se serializa preservando una única
    columna para evitar proliferación innecesaria de columnas.
    """
    parsed = _parse_json(s)
    if parsed is None:
        return {}
    if isinstance(parsed, dict):
        out: dict[str, Any] = {}
        for k, v in parsed.items():
            # Listas y dicts anidados se serializan como JSON string para que
            # quepan en una celda de DataFrame sin explotar el ancho.
            if isinstance(v, (list, dict)):
                out[f"{prefix}{k}"] = json.dumps(v, ensure_ascii=False)
            else:
                out[f"{prefix}{k}"] = v
        return out
    # Caso no esperado: payload con lista en top-level.
    # Se preserva serializado por compatibilidad defensiva.
    return {prefix.rstrip("_"): json.dumps(parsed, ensure_ascii=False)}


def _stage_status_from(payload: str | None, error: str | None) -> str:
    """payload + error → 'completed' | 'failed' | 'pending'."""
    if payload is not None:
        return "completed"
    if error is not None:
        return "failed"
    return "pending"


def _build_filter_sql(
    base: str,
    column: str,
    values: list[str] | None,
    order_by: str,
) -> tuple[str, tuple[Any, ...]]:
    """Construye una query con filtro opcional `WHERE ... IN (...)`.

    Los valores se insertan mediante placeholders parametrizados (`?`)
    para evitar SQL injection. `column` proviene de literales internos.
    """
    if values is None or len(values) == 0:
        return f"{base} ORDER BY {order_by}", ()
    placeholders = ",".join(["?"] * len(values))
    sql = f"{base} WHERE {column} IN ({placeholders}) ORDER BY {order_by}"
    return sql, tuple(values)


# ══════════════════════════════════════════════════════════════════════════════
#  Marcas discursivas → referentes canónicos
# ══════════════════════════════════════════════════════════════════════════════

def get_menciones(db_path: Path, codigo: str | None = None) -> pd.DataFrame:
    """Marcas discursivas con sus funciones, vínculos canónicos y frase.

    Una fila por (mención × vínculo canónico). Las menciones sin vínculo
    aparecen con `canonical_id` nulo. `funciones` viene como lista separada por
    coma. `frase` permite mostrar la frase completa al pasar el cursor.
    """
    with _ro_connect(db_path) as conn:
        exists = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='menciones'"
        ).fetchone()
        if exists is None:
            return pd.DataFrame()
        sql = (
            "SELECT m.id AS mencion_id, m.codigo, m.unit_idx, m.marca, "
            "       m.llm_inferencia, "
            "       (SELECT group_concat(funcion) FROM mencion_funcion "
            "          WHERE mencion_id = m.id) AS funciones, "
            "       mc.canonical_id, mc.status, mc.origin, "
            "       mc.modalidad, mc.naturaleza, mc.modalidad_origin, "
            "       f.frase AS frase "
            "FROM menciones m "
            "LEFT JOIN mencion_canonico mc ON mc.mencion_id = m.id "
            "LEFT JOIN frases f ON f.codigo = m.codigo AND f.unit_idx = m.unit_idx"
        )
        params: tuple = ()
        if codigo:
            sql += " WHERE m.codigo = ?"
            params = (codigo,)
        sql += " ORDER BY mc.canonical_id IS NULL, mc.canonical_id, m.unit_idx, m.marca"
        rows = conn.execute(sql, params).fetchall()
    return pd.DataFrame([dict(r) for r in rows])


def _json_or_none(raw: Any) -> Any:
    """Parsea JSON o devuelve None."""
    if not raw:
        return None
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return None


def get_referentes_resumen(
    db_path: Path, codigo: str | None = None
) -> pd.DataFrame:
    """Resumen liviano de referentes para el navegador (no carga las marcas).

    Una fila por canónico: canonical_id (NULL = sin canónico), nº de marcas, y
    cuántos vínculos están aceptados / propuestos.
    """
    with _ro_connect(db_path) as conn:
        if conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='menciones'"
        ).fetchone() is None:
            return pd.DataFrame()
        sql = (
            "SELECT mc.canonical_id AS canonical_id, "
            "       COUNT(DISTINCT m.id) AS n_marcas, "
            "       SUM(CASE WHEN mc.status='accepted' THEN 1 ELSE 0 END) AS n_accepted, "
            "       SUM(CASE WHEN mc.status='proposed' THEN 1 ELSE 0 END) AS n_proposed "
            "FROM menciones m "
            "LEFT JOIN mencion_canonico mc ON mc.mencion_id = m.id "
        )
        params: tuple = ()
        if codigo:
            sql += "WHERE m.codigo = ? "
            params = (codigo,)
        sql += ("GROUP BY mc.canonical_id "
                "ORDER BY mc.canonical_id IS NULL, mc.canonical_id")
        rows = conn.execute(sql, params).fetchall()
    return pd.DataFrame([dict(r) for r in rows])


def get_menciones_de_canonico(
    db_path: Path, canonical_id: str | None, codigo: str | None = None
) -> pd.DataFrame:
    """Marcas de UN referente (canonical_id None = marcas sin canónico).

    Mismas columnas que `get_menciones`, acotadas a un solo canónico para no
    cargar toda la base en la tab.
    """
    with _ro_connect(db_path) as conn:
        if conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='menciones'"
        ).fetchone() is None:
            return pd.DataFrame()
        sql = (
            "SELECT m.id AS mencion_id, m.codigo, m.unit_idx, m.marca, "
            "       m.llm_inferencia, "
            "       (SELECT group_concat(funcion) FROM mencion_funcion "
            "          WHERE mencion_id = m.id) AS funciones, "
            "       mc.canonical_id, mc.status, mc.origin, "
            "       mc.modalidad, mc.naturaleza, mc.modalidad_origin, "
            "       f.frase AS frase "
            "FROM menciones m "
            "LEFT JOIN mencion_canonico mc ON mc.mencion_id = m.id "
            "LEFT JOIN frases f ON f.codigo = m.codigo AND f.unit_idx = m.unit_idx "
            "WHERE "
        )
        params: list = []
        if canonical_id is None:
            sql += "mc.canonical_id IS NULL "
        else:
            sql += "mc.canonical_id = ? "
            params.append(canonical_id)
        if codigo:
            sql += "AND m.codigo = ? "
            params.append(codigo)
        sql += "ORDER BY m.unit_idx, m.id"
        rows = conn.execute(sql, tuple(params)).fetchall()
    return pd.DataFrame([dict(r) for r in rows])


def get_referente_funciones(
    db_path: Path, codigo: str | None = None
) -> dict[str, set]:
    """Funciones (actor/experienciador/fuente/…) presentes en cada referente.

    Devuelve canonical_id → conjunto de funciones de sus marcas, para filtrar
    la lista de referentes por función en la tab.
    """
    out: dict[str, set] = {}
    with _ro_connect(db_path) as conn:
        if not _menciones_exists(conn):
            return out
        sql = (
            "SELECT mc.canonical_id AS cid, mf.funcion AS funcion "
            "FROM mencion_canonico mc "
            "JOIN mencion_funcion mf ON mf.mencion_id = mc.mencion_id "
            "JOIN menciones m ON m.id = mc.mencion_id "
        )
        params: tuple = ()
        if codigo:
            sql += "WHERE m.codigo = ? "
            params = (codigo,)
        for r in conn.execute(sql, params):
            cid = r["cid"]
            if cid:
                out.setdefault(cid, set()).add(r["funcion"])
    return out


def get_referente_modalidades(
    db_path: Path, codigo: str | None = None
) -> dict[str, set]:
    """canonical_id → conjunto de modalidades referenciales de sus vínculos.

    Para filtrar la lista de referentes por modalidad (designacion /
    referencia_gramatical / identificacion_inferencial) en la tab.
    """
    out: dict[str, set] = {}
    with _ro_connect(db_path) as conn:
        if not _menciones_exists(conn):
            return out
        sql = (
            "SELECT mc.canonical_id AS cid, mc.modalidad AS modalidad "
            "FROM mencion_canonico mc "
            "JOIN menciones m ON m.id = mc.mencion_id "
            "WHERE mc.modalidad IS NOT NULL AND mc.status != 'rejected' "
        )
        params: tuple = ()
        if codigo:
            sql += "AND m.codigo = ? "
            params = (codigo,)
        for r in conn.execute(sql, params):
            cid = r["cid"]
            if cid and r["modalidad"]:
                out.setdefault(cid, set()).add(r["modalidad"])
    return out


def bulk_links(
    db_path: Path,
    codigo: str | None = None,
    status: str = "proposed",
    modalidades: list[str] | None = None,
    incluir_func: list[str] | None = None,
    excluir_func: list[str] | None = None,
    incluir_ref: list[str] | None = None,
    excluir_ref: list[str] | None = None,
) -> list[tuple[int, str]]:
    """Pares (mencion_id, canonical_id) que matchean los filtros de bulk.

    - `status`: estado actual de los vínculos a afectar (típico: 'proposed').
    - `modalidades`: solo vínculos con esa modalidad (vacío = todas).
    - `incluir_func` / `excluir_func`: la marca DEBE / NO DEBE tener esa función
      (selección negativa, p. ej. "todas las que no son actor").
    - `incluir_ref` / `excluir_ref`: canónicos a incluir / excluir.
    """
    pairs: list[tuple[int, str]] = []
    with _ro_connect(db_path) as conn:
        if not _menciones_exists(conn):
            return pairs
        sql = [
            "SELECT DISTINCT mc.mencion_id AS mid, mc.canonical_id AS cid "
            "FROM mencion_canonico mc JOIN menciones m ON m.id = mc.mencion_id "
            "WHERE mc.status = ? AND mc.canonical_id IS NOT NULL "
        ]
        params: list = [status]
        if codigo:
            sql.append("AND m.codigo = ? ")
            params.append(codigo)
        if modalidades:
            ph = ",".join("?" * len(modalidades))
            sql.append(f"AND mc.modalidad IN ({ph}) ")
            params.extend(modalidades)
        if incluir_ref:
            ph = ",".join("?" * len(incluir_ref))
            sql.append(f"AND mc.canonical_id IN ({ph}) ")
            params.extend(incluir_ref)
        if excluir_ref:
            ph = ",".join("?" * len(excluir_ref))
            sql.append(f"AND mc.canonical_id NOT IN ({ph}) ")
            params.extend(excluir_ref)
        if incluir_func:
            ph = ",".join("?" * len(incluir_func))
            sql.append(
                f"AND EXISTS (SELECT 1 FROM mencion_funcion mf "
                f"WHERE mf.mencion_id = m.id AND mf.funcion IN ({ph})) "
            )
            params.extend(incluir_func)
        if excluir_func:
            ph = ",".join("?" * len(excluir_func))
            sql.append(
                f"AND NOT EXISTS (SELECT 1 FROM mencion_funcion mf "
                f"WHERE mf.mencion_id = m.id AND mf.funcion IN ({ph})) "
            )
            params.extend(excluir_func)
        for r in conn.execute("".join(sql), params):
            pairs.append((int(r["mid"]), str(r["cid"])))
    return pairs


# ══════════════════════════════════════════════════════════════════════════════
#  Resolución de canónicos por marca (deixis / referentes)
# ══════════════════════════════════════════════════════════════════════════════

def _menciones_exists(conn: sqlite3.Connection) -> bool:
    return conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='menciones'"
    ).fetchone() is not None


def _frase_mention_canonicos(
    conn: sqlite3.Connection, funcion: str, codigo: str | None = None
) -> dict[tuple[str, int], dict[str, dict[str, tuple[int, int]]]]:
    """(codigo, unit_idx) → {marca_norm: {canonical_id: score}} de una función.

    Base compartida para resolver canónicos desde la capa de marcas (deixis/
    coref) de forma uniforme en Revisión, Simulacros y Búsqueda.
    """
    out: dict[tuple[str, int], dict[str, dict[str, tuple[int, int]]]] = {}
    if not _menciones_exists(conn):
        return out
    rank = {"accepted": 0, "proposed": 1}
    origin_rank = {"deixis_llm": 0, "human": 1, "auto": 2, "coref": 3, "llm": 4}
    sql = (
        "SELECT m.codigo, m.unit_idx, m.marca, mc.canonical_id, mc.status, mc.origin "
        "FROM menciones m "
        "JOIN mencion_funcion mf ON mf.mencion_id = m.id AND mf.funcion = ? "
        "JOIN mencion_canonico mc ON mc.mencion_id = m.id "
        "WHERE mc.status != 'rejected' "
    )
    params: list[Any] = [funcion]
    if codigo:
        sql += "AND m.codigo = ? "
        params.append(codigo)
    for r in conn.execute(sql, tuple(params)):
        cid = r["canonical_id"]
        mm = (r["marca"] or "").strip().lower()
        if not cid or not mm:
            continue
        score = (rank.get(r["status"], 9), origin_rank.get(r["origin"], 9))
        d = out.setdefault((r["codigo"], r["unit_idx"]), {}).setdefault(mm, {})
        if cid not in d or score < d[cid]:
            d[cid] = score
    return out


def _match_canonicos(
    marca_map: dict[str, dict[str, tuple[int, int]]] | None, fm: str
) -> list[str]:
    """Resuelve la marca `fm` (normalizada) contra las menciones de la frase.

    Match exacto primero; si no hay, por contención en ambos sentidos (separa
    marcas compuestas en sus sub-referentes). Dedup por canonical_id, ordenado
    por preferencia (aceptado/deixis primero) y luego alfabético.
    """
    if not marca_map or not fm:
        return []
    if fm in marca_map:
        matched = {fm: marca_map[fm]}
    else:
        matched = {mm: c for mm, c in marca_map.items() if mm in fm or fm in mm}
    scored: dict[str, tuple[int, int]] = {}
    for cids in matched.values():
        for cid, sc in cids.items():
            if cid not in scored or sc < scored[cid]:
                scored[cid] = sc
    return [cid for cid, _ in sorted(scored.items(), key=lambda kv: (kv[1], kv[0]))]


def _resolve_marca_canonicos(
    db_path: Path, codigo: str, funcion: str, marca_field: str
) -> dict[tuple[int, int], list[str]]:
    """(unit_idx, emocion_idx) → lista de canónicos DISTINTOS de la marca.

    Usa los helpers compartidos `_frase_mention_canonicos` + `_match_canonicos`,
    los mismos que Simulacros y Búsqueda, para que deixis/referentes propaguen
    igual en todas las tabs.
    """
    out: dict[tuple[int, int], list[str]] = {}
    with _ro_connect(db_path) as conn:
        per = _frase_mention_canonicos(conn, funcion, codigo)
        if not per:
            return out
        for r in conn.execute(
            "SELECT unit_idx, emociones_payload, emociones_pass2_payload "
            "FROM frases WHERE codigo = ?",
            (codigo,),
        ):
            marca_map = per.get((codigo, r["unit_idx"]))
            if not marca_map:
                continue
            payload = _json_or_none(r["emociones_pass2_payload"])
            if not isinstance(payload, list):
                payload = _json_or_none(r["emociones_payload"])
            if not isinstance(payload, list):
                continue
            for ei, emo in enumerate(payload):
                if not isinstance(emo, dict):
                    continue
                fm = str(emo.get(marca_field) or "").strip().lower()
                ordered = _match_canonicos(marca_map, fm)
                if ordered:
                    out[(r["unit_idx"], ei)] = ordered
    return out


def get_experienciador_canonicos_map(
    db_path: Path, codigo: str
) -> dict[tuple[int, int], list[str]]:
    """(unit_idx, emocion_idx) → canónicos del experienciador (varios, distintos).

    Si una emoción tiene fijado `experienciador_canonico` (atribución manual por
    emoción), ese valor tiene prioridad sobre la resolución por marca. Así la
    desarticulación por emoción se propaga a todas las vistas.
    """
    base = _resolve_marca_canonicos(
        db_path, codigo, "experienciador", "experienciador_marca"
    )
    with _ro_connect(db_path) as conn:
        if conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='emociones'"
        ).fetchone() is None:
            return base
        cols = {r["name"] for r in conn.execute("PRAGMA table_info(emociones)")}
        if "experienciador_canonico" not in cols:
            return base
        for r in conn.execute(
            "SELECT frase_idx, emocion_idx, experienciador_canonico "
            "FROM emociones WHERE codigo = ? "
            "AND experienciador_canonico IS NOT NULL "
            "AND TRIM(experienciador_canonico) != ''",
            (codigo,),
        ):
            fijado = [
                c.strip() for c in str(r["experienciador_canonico"]).split(";")
                if c.strip()
            ]
            if fijado:
                base[(int(r["frase_idx"]), int(r["emocion_idx"]))] = fijado
    return base


def get_fuente_canonicos_map(
    db_path: Path, codigo: str
) -> dict[tuple[int, int], list[str]]:
    """(unit_idx, emocion_idx) → canónicos de la fuente (varios, distintos).

    Si una emoción tiene fijado `fuente_canonico` (atribución manual por
    emoción), ese valor tiene prioridad sobre la resolución por marca.
    """
    base = _resolve_marca_canonicos(
        db_path, codigo, "fuente", "fuente_marca"
    )
    with _ro_connect(db_path) as conn:
        if conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='emociones'"
        ).fetchone() is None:
            return base
        cols = {r["name"] for r in conn.execute("PRAGMA table_info(emociones)")}
        if "fuente_canonico" not in cols:
            return base
        for r in conn.execute(
            "SELECT frase_idx, emocion_idx, fuente_canonico "
            "FROM emociones WHERE codigo = ? "
            "AND fuente_canonico IS NOT NULL AND TRIM(fuente_canonico) != ''",
            (codigo,),
        ):
            fijado = [
                c.strip() for c in str(r["fuente_canonico"]).split(";")
                if c.strip()
            ]
            if fijado:
                base[(int(r["frase_idx"]), int(r["emocion_idx"]))] = fijado
    return base


# ══════════════════════════════════════════════════════════════════════════════
#  Búsqueda (tab Búsqueda)
# ══════════════════════════════════════════════════════════════════════════════

def iter_all_frases(
    db_path: Path, codigos: list[str] | None = None
) -> list[tuple[str, int, str]]:
    """Todas las frases (codigo, unit_idx, frase), ordenadas. Para búsqueda/contexto."""
    sql, params = _build_filter_sql(
        base="SELECT codigo, unit_idx, frase FROM frases",
        column="codigo",
        values=codigos,
        order_by="codigo, unit_idx",
    )
    with _ro_connect(db_path) as conn:
        rows = conn.execute(sql, params).fetchall()
    return [(r["codigo"], int(r["unit_idx"]), r["frase"] or "") for r in rows]


def search_counts(db_path: Path, term: str) -> dict[str, int]:
    """Conteos de apariciones de un término (substring, insensible a caso/acentos).

    Devuelve {frases, emociones, experienciadores, fuentes}. Pensado para el
    encabezado del resultado de búsqueda ("→ 15 emociones, 10 experienciadores…").
    """
    from emoparse.app._textmatch import normalize as _norm
    t = _norm(term)
    if not t:
        return {"frases": 0, "emociones": 0, "experienciadores": 0, "fuentes": 0}
    n_frases = n_emo = 0
    exp_set: set[str] = set()
    fte_set: set[str] = set()
    with _ro_connect(db_path) as conn:
        for r in conn.execute("SELECT frase FROM frases"):
            if t in _norm(r["frase"] or ""):
                n_frases += 1
        if conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='emociones'"
        ).fetchone():
            exp_units = _frase_mention_canonicos(conn, "experienciador")
            fte_units = _frase_mention_canonicos(conn, "fuente")
            for r in conn.execute(
                "SELECT codigo, frase_idx, experienciador, experienciador_marca, "
                "fuente_marca, fuente_inferencia FROM emociones"
            ):
                exp_cids = _match_canonicos(
                    exp_units.get((r["codigo"], int(r["frase_idx"]))),
                    (r["experienciador_marca"] or "").strip().lower(),
                )
                fte_cids = _match_canonicos(
                    fte_units.get((r["codigo"], int(r["frase_idx"]))),
                    (r["fuente_marca"] or "").strip().lower(),
                )
                # Texto buscable: inferencia + marca + canónico(s) resuelto(s),
                # para que coincida igual que lo que muestra la búsqueda.
                exp_vals = exp_cids or (
                    [r["experienciador"].strip()] if (r["experienciador"] or "").strip() else []
                )
                fte_vals = fte_cids or (
                    [r["fuente_inferencia"].strip()] if (r["fuente_inferencia"] or "").strip() else []
                )
                exp_text = _norm(" ".join(
                    [str(r["experienciador"] or ""), str(r["experienciador_marca"] or "")]
                    + exp_cids))
                fte_text = _norm(" ".join(
                    [str(r["fuente_marca"] or ""), str(r["fuente_inferencia"] or "")]
                    + fte_cids))
                in_exp = t in exp_text
                in_fte = t in fte_text
                if in_exp or in_fte:
                    n_emo += 1
                if in_exp:
                    for v in exp_vals:
                        if v:
                            exp_set.add(_norm(v))
                if in_fte:
                    for v in fte_vals:
                        if v:
                            fte_set.add(_norm(v))
    return {
        "frases": n_frases,
        "emociones": n_emo,
        "experienciadores": len(exp_set),
        "fuentes": len(fte_set),
    }


def list_search_options(db_path: Path) -> dict[str, list[str]]:
    """Valores distintos para la búsqueda por selección.

    Experienciadores/fuentes/emociones se toman de `get_items_by_frase` (mismos
    valores que muestra la búsqueda: canónico resuelto con fallback al crudo),
    para que no haya desfasaje entre el selector y los ítems mostrados. Actores
    son los canónicos de función actor.
    """
    emos: set[str] = set()
    exps: set[str] = set()
    ftes: set[str] = set()
    actores: set[str] = set()
    for d in get_items_by_frase(db_path).values():
        emos.update(d.get("emociones", []))
        exps.update(d.get("experienciadores", []))
        ftes.update(d.get("fuentes", []))
    with _ro_connect(db_path) as conn:
        if _menciones_exists(conn):
            for r in conn.execute(
                "SELECT DISTINCT mc.canonical_id "
                "FROM mencion_canonico mc "
                "JOIN mencion_funcion mf ON mf.mencion_id = mc.mencion_id "
                "WHERE mf.funcion = 'actor' AND mc.status != 'rejected'"
            ):
                if r["canonical_id"]:
                    actores.add(r["canonical_id"])
    return {
        "emociones": sorted(emos),
        "experienciadores": sorted(exps),
        "fuentes": sorted(ftes),
        "actores": sorted(actores),
    }


def frases_for_selection(
    db_path: Path, kind: str, value: str
) -> list[tuple[str, int]]:
    """Frases (codigo, unit_idx) asociadas a una emoción/experienciador/fuente/actor.

    Para emoción/experienciador/fuente usa `get_items_by_frase` (canónico
    resuelto con fallback al crudo), consistente con `list_search_options` y con
    los ítems mostrados. Para actor, los vínculos de la base de marcas.
    """
    keys: list[tuple[str, int]] = []
    cat = {
        "emocion": "emociones",
        "experienciador": "experienciadores",
        "fuente": "fuentes",
    }.get(kind)
    if cat is not None:
        for (codigo, unit_idx), d in get_items_by_frase(db_path).items():
            if value in d.get(cat, []):
                keys.append((codigo, unit_idx))
    elif kind == "actor":
        with _ro_connect(db_path) as conn:
            if _menciones_exists(conn):
                for r in conn.execute(
                    "SELECT DISTINCT m.codigo, m.unit_idx "
                    "FROM menciones m "
                    "JOIN mencion_canonico mc ON mc.mencion_id = m.id "
                    "WHERE mc.canonical_id = ? AND mc.status != 'rejected'",
                    (value,),
                ):
                    keys.append((r["codigo"], int(r["unit_idx"])))
    return sorted(set(keys))


# ══════════════════════════════════════════════════════════════════════════════
#  Simulacros de emoción (tab Simulacros)
# ══════════════════════════════════════════════════════════════════════════════

def _canonico_semas_map(
    conn: sqlite3.Connection,
) -> dict[str, set[str]]:
    """Mapa canonical_id → conjunto de semas (no rechazados)."""
    out: dict[str, set[str]] = {}
    if conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='canonico_semas'"
    ).fetchone() is None:
        return out
    for r in conn.execute(
        "SELECT canonical_id, sema FROM canonico_semas WHERE status != 'rejected'"
    ):
        out.setdefault(r["canonical_id"], set()).add(r["sema"])
    return out


def get_simulacros(db_path: Path) -> pd.DataFrame:
    """Una fila por emoción con sus actantes y los semas de experienciador/fuente.

    Reúne lo necesario para reconstruir el "simulacro" emocional y filtrarlo:
    tipo de emoción (canónico), experienciador y fuente (con su canónico y
    semas resueltos) y el tipo de cada actante (mediador, verificadores,
    operador de modificación).
    """
    with _ro_connect(db_path) as conn:
        if conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='emociones'"
        ).fetchone() is None:
            return pd.DataFrame()
        exp_units = _frase_mention_canonicos(conn, "experienciador")
        fte_units = _frase_mention_canonicos(conn, "fuente")
        semas = _canonico_semas_map(conn)
        rows = conn.execute(
            "SELECT e.codigo, e.frase_idx, e.emocion_idx, "
            "e.experienciador, e.experienciador_marca, "
            "e.tipo_emocion, e.tipo_emocion_canonico, "
            "e.fuente_marca, e.fuente_inferencia, "
            "e.actantes_payload, f.frase "
            "FROM emociones e "
            "LEFT JOIN frases f ON e.codigo = f.codigo AND e.frase_idx = f.unit_idx "
            "ORDER BY e.codigo, e.frase_idx, e.emocion_idx"
        ).fetchall()
    records: list[dict[str, Any]] = []
    for r in rows:
        act = _parse_json(r["actantes_payload"]) or {}
        med = act.get("mediador") or {}
        vn = act.get("verificador_normativo") or {}
        vo = act.get("verificador_observacional") or {}
        om = act.get("operador_modificacion") or {}
        exp_cids = _match_canonicos(
            exp_units.get((r["codigo"], r["frase_idx"])),
            (r["experienciador_marca"] or "").strip().lower(),
        )
        fte_cids = _match_canonicos(
            fte_units.get((r["codigo"], r["frase_idx"])),
            (r["fuente_marca"] or "").strip().lower(),
        )
        exp_c = "; ".join(exp_cids)
        fte_c = "; ".join(fte_cids)
        exp_semas: set = set().union(*(semas.get(c, set()) for c in exp_cids)) if exp_cids else set()
        fte_semas: set = set().union(*(semas.get(c, set()) for c in fte_cids)) if fte_cids else set()
        records.append({
            "codigo": r["codigo"],
            "frase_idx": r["frase_idx"],
            "emocion_idx": r["emocion_idx"],
            "frase": r["frase"] or "",
            "tipo_emocion": r["tipo_emocion"] or "",
            "tipo_emocion_canonico": r["tipo_emocion_canonico"] or r["tipo_emocion"] or "",
            "experienciador": r["experienciador"] or "",
            "experienciador_canonico": exp_c,
            "experienciador_semas": sorted(exp_semas),
            "fuente_inferencia": r["fuente_inferencia"] or "",
            "fuente_canonico": fte_c,
            "fuente_semas": sorted(fte_semas),
            "mediador": (med.get("tipo") if isinstance(med, dict) else "") or "",
            "verificador_normativo": (vn.get("tipo") if isinstance(vn, dict) else "") or "",
            "verificador_observacional": (vo.get("tipo") if isinstance(vo, dict) else "") or "",
            "operador_modificacion": (om.get("funcion") if isinstance(om, dict) else "") or "",
        })
    return pd.DataFrame.from_records(records)


# ══════════════════════════════════════════════════════════════════════════════
#  Emociones enriquecidas: fuente única para el filtrado transversal de las tabs
# ══════════════════════════════════════════════════════════════════════════════

#: Actantes aplanados que se exponen a nivel emoción.
_ACTANTE_FLAT: tuple[tuple[str, str, str], ...] = (
    ("mediador", "tipo", "mediador"),
    ("verificador_normativo", "tipo", "verificador_normativo"),
    ("verificador_normativo", "evaluacion", "verificador_normativo_evaluacion"),
    ("verificador_observacional", "tipo", "verificador_observacional"),
    ("verificador_observacional", "evaluacion", "verificador_observacional_evaluacion"),
    ("operador_modificacion", "funcion", "operador_modificacion"),
    ("polaridad", "tipo", "polaridad"),
)


def _discurso_enunciador_map(conn: sqlite3.Connection) -> dict[str, str]:
    """codigo → enunciador (desde enunciation_payload)."""
    out: dict[str, str] = {}
    for r in conn.execute("SELECT codigo, enunciation_payload FROM discursos"):
        payload = _json_or_none(r["enunciation_payload"]) or {}
        if isinstance(payload, dict):
            out[r["codigo"]] = str(payload.get("enunciador") or "")
    return out


def _discurso_len_map(conn: sqlite3.Connection) -> dict[str, int]:
    """codigo → índice de frase máximo (longitud del discurso, para posición relativa)."""
    out: dict[str, int] = {}
    for r in conn.execute("SELECT codigo, MAX(unit_idx) AS m FROM frases GROUP BY codigo"):
        if r["m"] is not None:
            out[r["codigo"]] = int(r["m"])
    return out


def get_emociones_enriched(
    db_path: Path,
    codigos: list[str] | None = None,
) -> pd.DataFrame:
    """`get_emociones` + columnas resueltas para el filtrado transversal de las tabs.

    Suma, por emoción, el experienciador y la fuente **canónicos** (con la misma
    prioridad que la tab Revisión: atribución por emoción > resolución marca↔
    referente de deixis/coref > crudo del LLM), sus **semas**, el **enunciador**
    del discurso, los **actantes** aplanados y la longitud del discurso (para la
    posición relativa). Es la fuente única de curva, actores, tabla y correlación,
    para no duplicar la lógica de resolución entre tabs.

    Columnas nuevas: `experienciador_canonico`/`fuente_canonico` (str, `; `-join),
    `experienciador_canonicos`/`fuente_canonicos` (list), `experienciador_semas`/
    `fuente_semas` (list), `experienciador_efectivo`/`fuente_efectiva` (canónico o,
    si no resuelve, crudo), `enunciador`, `pos_max_discurso`, y los actantes
    (`mediador`, `verificador_normativo`, `operador_modificacion`, `polaridad`, …).
    """
    base = get_emociones(db_path, codigos)
    if base.empty:
        return base

    enr: dict[tuple[str, int, int], dict[str, Any]] = {}
    enun_map: dict[str, str] = {}
    len_map: dict[str, int] = {}
    with _ro_connect(db_path) as conn:
        if conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='emociones'"
        ).fetchone() is None:
            return base
        exp_units = _frase_mention_canonicos(conn, "experienciador")
        fte_units = _frase_mention_canonicos(conn, "fuente")
        semas = _canonico_semas_map(conn)
        enun_map = _discurso_enunciador_map(conn)
        len_map = _discurso_len_map(conn)
        emo_cols = {r["name"] for r in conn.execute("PRAGMA table_info(emociones)")}
        sel_exp_c = ("experienciador_canonico" if "experienciador_canonico" in emo_cols
                     else "NULL AS experienciador_canonico")
        sel_fte_c = ("fuente_canonico" if "fuente_canonico" in emo_cols
                     else "NULL AS fuente_canonico")
        sql = (
            "SELECT codigo, frase_idx, emocion_idx, "
            "experienciador_marca, fuente_marca, "
            f"{sel_exp_c}, {sel_fte_c}, actantes_payload FROM emociones"
        )
        params: tuple = ()
        if codigos:
            qm = ",".join("?" * len(codigos))
            sql += f" WHERE codigo IN ({qm})"
            params = tuple(codigos)
        for r in conn.execute(sql, params):
            key = (r["codigo"], int(r["frase_idx"]), int(r["emocion_idx"]))
            fkey = (r["codigo"], int(r["frase_idx"]))

            def _canon(override: Any, marca_map, marca_field: str) -> list[str]:
                fijado = [c.strip() for c in str(override or "").split(";") if c.strip()]
                if fijado:
                    return fijado
                return _match_canonicos(
                    marca_map, (r[marca_field] or "").strip().lower()
                )

            exp_c = _canon(r["experienciador_canonico"], exp_units.get(fkey), "experienciador_marca")
            fte_c = _canon(r["fuente_canonico"], fte_units.get(fkey), "fuente_marca")
            exp_s = sorted(set().union(*(semas.get(c, set()) for c in exp_c))) if exp_c else []
            fte_s = sorted(set().union(*(semas.get(c, set()) for c in fte_c))) if fte_c else []
            act = _parse_json(r["actantes_payload"]) or {}
            rec: dict[str, Any] = {
                "experienciador_canonicos": exp_c,
                "experienciador_canonico": "; ".join(exp_c),
                "experienciador_semas": exp_s,
                "fuente_canonicos": fte_c,
                "fuente_canonico": "; ".join(fte_c),
                "fuente_semas": fte_s,
            }
            for grupo, leaf, colname in _ACTANTE_FLAT:
                sub = act.get(grupo) if isinstance(act, dict) else None
                rec[colname] = (sub.get(leaf) if isinstance(sub, dict) else None) or ""
            enr[key] = rec

    keys = [
        (row.codigo, int(row.frase_idx), int(row.emocion_idx))
        for row in base.itertuples(index=False)
    ]
    new_cols = (
        "experienciador_canonicos", "experienciador_canonico", "experienciador_semas",
        "fuente_canonicos", "fuente_canonico", "fuente_semas",
    ) + tuple(c for _, _, c in _ACTANTE_FLAT)
    for col in new_cols:
        default: Any = [] if col.endswith(("_canonicos", "_semas")) else ""
        base[col] = [enr.get(k, {}).get(col, default) for k in keys]

    exp_raw = base["experienciador"].fillna("").astype(str)
    fte_raw = base.get("fuente_inferencia", pd.Series([""] * len(base))).fillna("").astype(str)
    base["experienciador_efectivo"] = [
        c if c else (raw or "—")
        for c, raw in zip(base["experienciador_canonico"], exp_raw)
    ]
    base["fuente_efectiva"] = [
        c if c else (raw or "—")
        for c, raw in zip(base["fuente_canonico"], fte_raw)
    ]
    base["enunciador"] = base["codigo"].map(enun_map).fillna("")
    base["pos_max_discurso"] = base["codigo"].map(len_map)
    return base


def list_canonico_semas(db_path: Path, canonical_id: str) -> list[dict[str, Any]]:
    """Semas de un referente con estado/origen (para la edición en tab Referentes)."""
    with _ro_connect(db_path) as conn:
        if conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='canonico_semas'"
        ).fetchone() is None:
            return []
        rows = conn.execute(
            "SELECT sema, status, origin FROM canonico_semas "
            "WHERE canonical_id = ? ORDER BY sema",
            (canonical_id,),
        ).fetchall()
    return [dict(r) for r in rows]


# ══════════════════════════════════════════════════════════════════════════════
#  Sugerencias de deixis (tab Deixis)
# ══════════════════════════════════════════════════════════════════════════════

def get_deixis_suggestions(
    db_path: Path, only_pending: bool = True, include_unlinked: bool = False
) -> list[dict[str, Any]]:
    """Sugerencias deícticas agrupadas por marca/mención.

    Devuelve, por mención con vínculos de deixis (`origin='deixis_llm'`):
    marca, funciones, frase, código/unidad y la lista de referentes sugeridos
    (canónico concreto, tipo deíctico y estado). Con `only_pending`, solo las
    menciones con al menos un referente deíctico aún sin revisar. Con
    `include_unlinked`, suma además las marcas deícticas (1ª/2ª persona) que NO
    tienen ningún vínculo deíctico, con `referentes=[]`, para poder asignarles
    uno a mano (p. ej. un auditorio agregado después en Enunciación).
    """
    with _ro_connect(db_path) as conn:
        if not _menciones_exists(conn):
            return []
        links = conn.execute(
            "SELECT mencion_id, canonical_id, deixis_tipo, status "
            "FROM mencion_canonico WHERE origin = 'deixis_llm'"
        ).fetchall()

        by_men: dict[int, list[dict[str, Any]]] = {}
        for r in links:
            by_men.setdefault(r["mencion_id"], []).append({
                "canonical_id": r["canonical_id"],
                "deixis_tipo": r["deixis_tipo"] or "",
                "status": r["status"],
            })
        mids = [
            mid for mid, ls in by_men.items()
            if not only_pending or any(l["status"] == "proposed" for l in ls)
        ]

        if include_unlinked:
            from emoparse.pipeline.deixis import is_deictic

            linked = set(by_men)
            for r in conn.execute("SELECT id, marca FROM menciones"):
                if r["id"] not in linked and is_deictic(str(r["marca"] or "")):
                    mids.append(r["id"])

        if not mids:
            return []
        mids = sorted(set(mids))

        qm = ",".join("?" * len(mids))
        men = {
            r["id"]: dict(r)
            for r in conn.execute(
                f"SELECT id, codigo, unit_idx, marca FROM menciones "
                f"WHERE id IN ({qm})",
                mids,
            )
        }
        func: dict[int, list[str]] = {}
        for r in conn.execute(
            f"SELECT mencion_id, funcion FROM mencion_funcion "
            f"WHERE mencion_id IN ({qm})",
            mids,
        ):
            func.setdefault(r["mencion_id"], []).append(r["funcion"])

        codigos = sorted({men[mid]["codigo"] for mid in mids if mid in men})
        frase_map: dict[tuple[str, int], str] = {}
        if codigos:
            qc = ",".join("?" * len(codigos))
            for r in conn.execute(
                f"SELECT codigo, unit_idx, frase FROM frases "
                f"WHERE codigo IN ({qc})",
                codigos,
            ):
                frase_map[(r["codigo"], r["unit_idx"])] = r["frase"] or ""

    out: list[dict[str, Any]] = []
    for mid in mids:
        info = men.get(mid)
        if not info:
            continue
        out.append({
            "mencion_id": mid,
            "codigo": info["codigo"],
            "unit_idx": info["unit_idx"],
            "marca": info["marca"],
            "funciones": sorted(set(func.get(mid, []))),
            "frase": frase_map.get((info["codigo"], info["unit_idx"]), ""),
            "referentes": sorted(by_men.get(mid, []),
                                 key=lambda r: r["deixis_tipo"]),
        })
    out.sort(key=lambda d: (d["codigo"], d["unit_idx"], d["mencion_id"]))
    return out


def _as_json_list(v: Any) -> list[Any]:
    """Parsea a lista JSON; [] ante cualquier problema."""
    p = _parse_json(v) if isinstance(v, str) else v
    return p if isinstance(p, list) else []


def get_deixis_referentes_map(
    db_path: Path, codigos: list[str] | None = None
) -> dict[str, list[dict[str, str]]]:
    """Por discurso, los referentes deícticos disponibles (enunciador, auditorio,
    colectivos), con su tipo, nombre y canónico. Para 'agregar otro' en tab Deixis.
    """
    from emoparse.core.text import canonical_slug

    out: dict[str, list[dict[str, str]]] = {}
    sql = "SELECT codigo, enunciation_payload FROM discursos"
    params: tuple = ()
    if codigos:
        qm = ",".join("?" * len(codigos))
        sql += f" WHERE codigo IN ({qm})"
        params = tuple(codigos)
    with _ro_connect(db_path) as conn:
        rows = conn.execute(sql, params).fetchall()
    for r in rows:
        payload = _json_or_none(r["enunciation_payload"])
        refs: list[dict[str, str]] = []
        if isinstance(payload, dict):
            enun = str(payload.get("enunciador") or "").strip()
            if enun:
                refs.append({"tipo": "enunciador", "nombre": enun,
                             "canonical_id": canonical_slug(enun)})
            for a in _as_json_list(payload.get("auditorio")):
                nom = str(a.get("actor", "")).strip() if isinstance(a, dict) else ""
                if nom:
                    refs.append({"tipo": "auditorio", "nombre": nom,
                                 "canonical_id": canonical_slug(nom)})
            for c in _as_json_list(payload.get("colectivos_identificacion")):
                nom = str(c.get("nombre", "")).strip() if isinstance(c, dict) else ""
                if nom:
                    refs.append({"tipo": "colectivo_identificacion", "nombre": nom,
                                 "canonical_id": canonical_slug(nom)})
        seen: set[str] = set()
        ded = [x for x in refs
               if x["canonical_id"] and not (x["canonical_id"] in seen
                                             or seen.add(x["canonical_id"]))]
        out[r["codigo"]] = ded
    return out


def get_items_by_frase(
    db_path: Path, codigos: list[str] | None = None
) -> dict[tuple[str, int], dict[str, list[str]]]:
    """Por frase (codigo, unit_idx), los ítems concretos: emociones,
    experienciadores y fuentes. Para mostrar al lado de cada frase en búsqueda.
    """
    out: dict[tuple[str, int], dict[str, set]] = {}
    with _ro_connect(db_path) as conn:
        if conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='emociones'"
        ).fetchone() is None:
            return {}
        exp_units = _frase_mention_canonicos(conn, "experienciador")
        fte_units = _frase_mention_canonicos(conn, "fuente")
        sql = ("SELECT codigo, frase_idx, tipo_emocion, tipo_emocion_canonico, "
               "experienciador, experienciador_marca, "
               "fuente_inferencia, fuente_marca FROM emociones")
        params: tuple = ()
        if codigos:
            qm = ",".join("?" * len(codigos))
            sql += f" WHERE codigo IN ({qm})"
            params = tuple(codigos)
        for r in conn.execute(sql, params):
            key = (r["codigo"], int(r["frase_idx"]))
            d = out.setdefault(key, {"emociones": set(), "experienciadores": set(),
                                     "fuentes": set()})
            emo = (r["tipo_emocion_canonico"] or r["tipo_emocion"] or "").strip()
            if emo:
                d["emociones"].add(emo)
            # Experienciadores/fuentes: mostrar el canónico resuelto desde marcas
            # (deixis/coref); si no resuelve, la inferencia cruda del LLM.
            exp_cids = _match_canonicos(
                exp_units.get((r["codigo"], int(r["frase_idx"]))),
                (r["experienciador_marca"] or "").strip().lower(),
            )
            if exp_cids:
                d["experienciadores"].update(exp_cids)
            elif (r["experienciador"] or "").strip():
                d["experienciadores"].add(r["experienciador"].strip())
            fte_cids = _match_canonicos(
                fte_units.get((r["codigo"], int(r["frase_idx"]))),
                (r["fuente_marca"] or "").strip().lower(),
            )
            if fte_cids:
                d["fuentes"].update(fte_cids)
            elif (r["fuente_inferencia"] or "").strip():
                d["fuentes"].add(r["fuente_inferencia"].strip())
    return {k: {kk: sorted(vv) for kk, vv in v.items()} for k, v in out.items()}


def _embedding_candidate_pairs(
    cids: list[str], threshold: float, model: str | None
) -> dict[tuple[str, str], float]:
    """Pares (cid_a, cid_b) → coseno ≥ threshold vía vectores spaCy.

    Solo modelos CON vectores (es_core_news_md / lg; el sm no tiene). Si falta
    spaCy/numpy/modelo o el modelo no trae vectores, devuelve {} (silencioso).
    """
    try:
        import numpy as np  # type: ignore
        import spacy  # type: ignore
    except Exception:
        return {}
    candidates = [model] if model else []
    candidates += ["es_core_news_md", "es_core_news_lg"]
    nlp = None
    for name in candidates:
        if not name:
            continue
        try:
            nlp = spacy.load(name, disable=[
                "parser", "ner", "tagger", "lemmatizer",
                "attribute_ruler", "morphologizer",
            ])
            break
        except Exception:
            continue
    if nlp is None or not getattr(nlp.vocab, "vectors_length", 0):
        return {}

    kept: list[str] = []
    vecs: list[Any] = []
    for cid, doc in zip(cids, nlp.pipe(c.replace("_", " ") for c in cids)):
        v = getattr(doc, "vector", None)
        if v is None:
            continue
        norm = float(np.linalg.norm(v))
        if norm > 0.0:
            kept.append(cid)
            vecs.append(v / norm)
    if len(kept) < 2:
        return {}

    mat = np.vstack(vecs)
    cos = mat @ mat.T
    out: dict[tuple[str, str], float] = {}
    n = len(kept)
    for i in range(n):
        row = cos[i]
        for j in range(i + 1, n):
            c = float(row[j])
            if c >= threshold:
                out[(kept[i], kept[j])] = round(c, 3)
    return out


def suggest_referent_merges(
    db_path: Path,
    codigo: str | None = None,
    threshold: float = 0.62,
    max_block: int = 60,
    use_embeddings: bool = True,
    embed_threshold: float = 0.80,
    nlp_model: str | None = None,
    embed_max_n: int = 6000,
) -> list[dict]:
    """Sugiere grupos de referentes canónicos que podrían ser el mismo.

    Escalable (no compara todos contra todos): **blocking** por token
    significativo compartido (los canónicos ya vienen sin artículos), y solo
    dentro de cada bloque calcula similitud léxica (Jaccard de tokens, ratio de
    caracteres y contención de conjuntos). Opcionalmente suma candidatos
    **semánticos** por embeddings (vectores spaCy + coseno), que capta sinónimos
    sin tokens compartidos. Agrupa con union-find. NO fusiona: solo propone.

    - `threshold`: score léxico mínimo (0..1) para proponer un par.
    - `max_block`: bloques por token con más canónicos que esto se saltean.
    - `use_embeddings`: si hay modelo spaCy con vectores (md/lg), agrega pares
      semánticos con coseno ≥ `embed_threshold`. Requiere numpy.
    - `embed_max_n`: si hay más canónicos que esto, se omite el pase semántico
      (evita la matriz de coseno n×n en bases enormes).
    """
    import difflib
    from collections import defaultdict

    stop = {"de", "la", "el", "los", "las", "un", "una", "y", "o", "del", "al"}

    def toks(cid: str) -> set:
        return {t for t in cid.split("_") if len(t) >= 3 and t not in stop}

    counts: dict[str, int] = {}
    with _ro_connect(db_path) as conn:
        if not _menciones_exists(conn):
            return []
        sql = (
            "SELECT mc.canonical_id AS cid, COUNT(*) AS n "
            "FROM mencion_canonico mc JOIN menciones m ON m.id = mc.mencion_id "
            "WHERE mc.status != 'rejected' AND mc.canonical_id IS NOT NULL "
        )
        params: tuple = ()
        if codigo:
            sql += "AND m.codigo = ? "
            params = (codigo,)
        sql += "GROUP BY mc.canonical_id"
        for r in conn.execute(sql, params):
            counts[str(r["cid"])] = int(r["n"])

    cids = list(counts)
    tok_map = {c: toks(c) for c in cids}

    # Blocking: token → cids que lo contienen.
    buckets: dict[str, list[str]] = defaultdict(list)
    for c, ts in tok_map.items():
        for t in ts:
            buckets[t].append(c)

    scored: dict[tuple[str, str], float] = {}
    for t, members in buckets.items():
        if len(members) < 2 or len(members) > max_block:
            continue
        for i in range(len(members)):
            for j in range(i + 1, len(members)):
                a, b = members[i], members[j]
                key = (a, b) if a < b else (b, a)
                if key in scored:
                    continue
                ta, tb = tok_map[a], tok_map[b]
                inter = ta & tb
                union_t = ta | tb
                jacc = len(inter) / len(union_t) if union_t else 0.0
                char = difflib.SequenceMatcher(None, a, b).ratio()
                # Contención de conjuntos de tokens (p. ej. "sociedad_humana" ⊆
                # "sociedad_humana_humanidad") = señal fuerte de sinonimia.
                contained = bool(inter) and (ta <= tb or tb <= ta)
                score = max(jacc, char, 0.9 if contained else 0.0)
                if score >= threshold:
                    scored[key] = score

    # ── Pase semántico opcional: candidatos por embeddings (spaCy + coseno) ───
    if use_embeddings and 2 <= len(cids) <= embed_max_n:
        emb_pairs = _embedding_candidate_pairs(cids, embed_threshold, nlp_model)
        for (a, b), cos in emb_pairs.items():
            key = (a, b) if a < b else (b, a)
            scored[key] = max(scored.get(key, 0.0), cos)

    if not scored:
        return []

    # Union-find sobre los pares que pasaron el umbral.
    parent: dict[str, str] = {}

    def find(x: str) -> str:
        parent.setdefault(x, x)
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(x: str, y: str) -> None:
        parent[find(x)] = find(y)

    pair_score: dict[str, float] = {}
    for (a, b), s in scored.items():
        union(a, b)
        pair_score[a] = max(pair_score.get(a, 0.0), s)
        pair_score[b] = max(pair_score.get(b, 0.0), s)

    groups: dict[str, list[str]] = defaultdict(list)
    for c in {x for pair in scored for x in pair}:
        groups[find(c)].append(c)

    out: list[dict] = []
    for members in groups.values():
        if len(members) < 2:
            continue
        sugerido = sorted(
            members, key=lambda c: (-counts.get(c, 0), len(c), c)
        )[0]
        out.append({
            "members": sorted(members, key=lambda c: (-counts.get(c, 0), c)),
            "sugerido": sugerido,
            "n_marcas": {c: counts.get(c, 0) for c in members},
            "score": round(max(pair_score.get(c, 0.0) for c in members), 3),
        })
    out.sort(key=lambda g: (-len(g["members"]), -g["score"]))
    return out


def get_frase_emociones_brief(
    db_path: Path,
) -> dict[tuple[str, int], list[dict[str, Any]]]:
    """Por frase (codigo, unit_idx), un resumen de sus emociones: cada una con
    experienciador, emoción, modo de existencia y fuente (canónicos resueltos,
    fallback al crudo), más su `emocion_idx`.

    Para el tooltip de la tab Referentes y para la atribución por emoción: al
    pasar el cursor por la frase de una marca (experienciador/fuente), ver el
    contexto emocional de esa frase. Si una emoción tiene fijado un
    `experienciador_canonico` por emoción (atribución manual), ese valor tiene
    prioridad sobre la resolución por marca.
    """
    out: dict[tuple[str, int], list[dict[str, Any]]] = {}
    with _ro_connect(db_path) as conn:
        if conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='emociones'"
        ).fetchone() is None:
            return out
        exp_units = _frase_mention_canonicos(conn, "experienciador")
        fte_units = _frase_mention_canonicos(conn, "fuente")
        emo_cols = {r["name"] for r in conn.execute("PRAGMA table_info(emociones)")}
        sel_exp_c = ("experienciador_canonico" if "experienciador_canonico" in emo_cols
                     else "NULL AS experienciador_canonico")
        sel_fte_c = ("fuente_canonico" if "fuente_canonico" in emo_cols
                     else "NULL AS fuente_canonico")
        for r in conn.execute(
            "SELECT codigo, frase_idx, emocion_idx, experienciador, "
            f"experienciador_marca, {sel_exp_c}, modo_existencia, "
            "tipo_emocion, tipo_emocion_canonico, "
            f"fuente_inferencia, fuente_marca, {sel_fte_c} FROM emociones "
            "ORDER BY codigo, frase_idx, emocion_idx"
        ):
            key = (r["codigo"], int(r["frase_idx"]))
            exp_override = (r["experienciador_canonico"] or "").strip()
            if exp_override:
                exp = exp_override
            else:
                exp_cids = _match_canonicos(
                    exp_units.get(key), (r["experienciador_marca"] or "").strip().lower()
                )
                exp = "; ".join(exp_cids) or (r["experienciador"] or "").strip() or "—"
            fte_override = (r["fuente_canonico"] or "").strip()
            if fte_override:
                fte = fte_override
            else:
                fte_cids = _match_canonicos(
                    fte_units.get(key), (r["fuente_marca"] or "").strip().lower()
                )
                fte = "; ".join(fte_cids) or (r["fuente_inferencia"] or "").strip() or "—"
            emo = (r["tipo_emocion_canonico"] or r["tipo_emocion"] or "").strip() or "—"
            modo = (r["modo_existencia"] or "").strip() or "—"
            out.setdefault(key, []).append({
                "emocion_idx": int(r["emocion_idx"]),
                "experienciador": exp,
                "experienciador_fijado": bool(exp_override),
                "emocion": emo,
                "modo": modo,
                "fuente": fte,
                "fuente_fijado": bool(fte_override),
            })
    return out


def list_canonicos(db_path: Path) -> list[str]:
    """Canónicos existentes (los visibles en tab Referentes), para reasignar."""
    out: set[str] = set()
    with _ro_connect(db_path) as conn:
        if _menciones_exists(conn):
            for r in conn.execute(
                "SELECT DISTINCT canonical_id FROM mencion_canonico "
                "WHERE status != 'rejected' AND canonical_id != ''"
            ):
                if r["canonical_id"]:
                    out.add(r["canonical_id"])
    return sorted(out)


# ══════════════════════════════════════════════════════════════════════════════
#  Enunciación por discurso (tab Enunciación)
# ══════════════════════════════════════════════════════════════════════════════

def list_discursos(db_path: Path) -> list[tuple[str, str]]:
    """(codigo, titulo) de cada discurso, para el selector de la tab."""
    out: list[tuple[str, str]] = []
    with _ro_connect(db_path) as conn:
        for r in conn.execute("SELECT codigo, input FROM discursos ORDER BY codigo"):
            inp = _json_or_none(r["input"]) or {}
            titulo = str(inp.get("titulo") or "") if isinstance(inp, dict) else ""
            out.append((r["codigo"], titulo))
    return out


def get_enunciation_full(db_path: Path, codigo: str) -> dict[str, Any] | None:
    """Estructura enunciativa editable + título y resumen global del discurso."""
    with _ro_connect(db_path) as conn:
        row = conn.execute(
            "SELECT input, enunciation_payload, summarizer_payload "
            "FROM discursos WHERE codigo = ?",
            (codigo,),
        ).fetchone()
    if row is None:
        return None
    inp = _json_or_none(row["input"]) or {}
    payload = _json_or_none(row["enunciation_payload"]) or {}
    summ = _json_or_none(row["summarizer_payload"]) or {}
    inp = inp if isinstance(inp, dict) else {}
    payload = payload if isinstance(payload, dict) else {}
    summ = summ if isinstance(summ, dict) else {}
    return {
        "codigo": codigo,
        "titulo": str(inp.get("titulo") or ""),
        "resumen": str(summ.get("resumen_global") or ""),
        "enunciador": str(payload.get("enunciador") or ""),
        "enunciador_justificacion": str(payload.get("enunciador_justificacion") or ""),
        "enunciatarios": _as_json_list(payload.get("enunciatarios")),
        "auditorio": _as_json_list(payload.get("auditorio")),
        "colectivos": _as_json_list(payload.get("colectivos_identificacion")),
    }
