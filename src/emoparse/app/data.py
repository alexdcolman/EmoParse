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
_EXPLODE_STAGE: str = "explode_emociones"

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
            "e.modo_existencia, e.tipo_configuracion, "
            "e.caracterizacion_payload, e.actantes_payload, "
            "j.coherente, j.issues, j.confianza "
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
        - explode_emociones: cuenta discursos con `emociones_payload`
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
    """Conteo para `explode_emociones`.

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


def get_fuente_canonico_map(
    db_path: Path, codigo: str
) -> dict[tuple[int, int], str]:
    """Mapa (unit_idx, emocion_idx) → canónico de fuente ACEPTADO.

    Cruza la `fuente_marca` de cada emoción (del payload de detección,
    pase 2 si existe) con el vínculo aceptado de esa marca como fuente en la
    base de marcas. Permite mostrar en la revisión que, si hay canónico de
    fuente, ese es el que vale.
    """
    out: dict[tuple[int, int], str] = {}
    with _ro_connect(db_path) as conn:
        ok = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='menciones'"
        ).fetchone()
        if ok is None:
            return out
        canon: dict[tuple[int, str], str] = {}
        for r in conn.execute(
            "SELECT m.unit_idx, m.marca, mc.canonical_id "
            "FROM menciones m "
            "JOIN mencion_canonico mc ON mc.mencion_id = m.id "
            "JOIN mencion_funcion mf ON mf.mencion_id = m.id AND mf.funcion = 'fuente' "
            "WHERE m.codigo = ? AND mc.status = 'accepted'",
            (codigo,),
        ):
            canon[(r["unit_idx"], (r["marca"] or "").strip())] = r["canonical_id"]
        if not canon:
            return out
        for r in conn.execute(
            "SELECT unit_idx, emociones_payload, emociones_pass2_payload "
            "FROM frases WHERE codigo = ?",
            (codigo,),
        ):
            payload = _json_or_none(r["emociones_pass2_payload"])
            if not isinstance(payload, list):
                payload = _json_or_none(r["emociones_payload"])
            if not isinstance(payload, list):
                continue
            for ei, emo in enumerate(payload):
                if not isinstance(emo, dict):
                    continue
                fm = str(emo.get("fuente_marca") or "").strip()
                key = (r["unit_idx"], fm)
                if fm and key in canon:
                    out[(r["unit_idx"], ei)] = canon[key]
    return out


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


# ══════════════════════════════════════════════════════════════════════════════
#  Resolución de canónicos por marca (deixis / referentes)
# ══════════════════════════════════════════════════════════════════════════════

def _menciones_exists(conn: sqlite3.Connection) -> bool:
    return conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='menciones'"
    ).fetchone() is not None


def _marca_canonico_map(
    conn: sqlite3.Connection,
    funcion: str,
    codigo: str | None = None,
) -> dict[tuple[str, str], str]:
    """Mapa (codigo, marca_lower) → canónico para una función dada.

    Prefiere vínculos aceptados; en su defecto, la mejor propuesta (deixis del
    LLM primero). Descarta rechazados. Sirve para mostrar/filtrar por el
    referente concreto que resolvió la deixis.
    """
    if not _menciones_exists(conn):
        return {}
    sql = (
        "SELECT m.codigo, m.marca, mc.canonical_id, mc.status, mc.origin "
        "FROM menciones m "
        "JOIN mencion_funcion mf ON mf.mencion_id = m.id AND mf.funcion = ? "
        "JOIN mencion_canonico mc ON mc.mencion_id = m.id "
        "WHERE mc.status != 'rejected' "
    )
    params: list[Any] = [funcion]
    if codigo:
        sql += "AND m.codigo = ? "
        params.append(codigo)
    # Orden de preferencia: accepted > deixis_llm > resto.
    rank = {"accepted": 0, "proposed": 1}
    origin_rank = {"deixis_llm": 0, "human": 1, "auto": 2, "coref": 3, "llm": 4}
    best: dict[tuple[str, str], tuple[int, int, str]] = {}
    for r in conn.execute(sql, tuple(params)):
        key = (r["codigo"], (r["marca"] or "").strip().lower())
        score = (rank.get(r["status"], 9), origin_rank.get(r["origin"], 9))
        prev = best.get(key)
        if prev is None or score < prev[:2]:
            best[key] = (score[0], score[1], r["canonical_id"])
    return {k: v[2] for k, v in best.items()}


def get_experienciador_canonico_map(
    db_path: Path, codigo: str
) -> dict[tuple[int, int], str]:
    """Mapa (unit_idx, emocion_idx) → canónico de experienciador resuelto.

    Cruza la `experienciador_marca` de cada emoción con el vínculo de esa marca
    como experienciador en la base de marcas (deixis incluida). Permite que la
    revisión muestre, p. ej., que el experienciador con marca "yo" resuelve a
    "javier_milei" y nunca al tipo.
    """
    out: dict[tuple[int, int], str] = {}
    with _ro_connect(db_path) as conn:
        canon = _marca_canonico_map(conn, "experienciador", codigo)
        if not canon:
            return out
        for r in conn.execute(
            "SELECT unit_idx, emociones_payload, emociones_pass2_payload "
            "FROM frases WHERE codigo = ?",
            (codigo,),
        ):
            payload = _json_or_none(r["emociones_pass2_payload"])
            if not isinstance(payload, list):
                payload = _json_or_none(r["emociones_payload"])
            if not isinstance(payload, list):
                continue
            for ei, emo in enumerate(payload):
                if not isinstance(emo, dict):
                    continue
                marca = str(emo.get("experienciador_marca") or "").strip().lower()
                key = (r["unit_idx"], marca)
                if marca and key in canon:
                    out[(r["unit_idx"], ei)] = canon[key]
    return out


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
            for r in conn.execute(
                "SELECT experienciador, experienciador_marca, "
                "fuente_marca, fuente_inferencia FROM emociones"
            ):
                in_exp = t in _norm(f"{r['experienciador']} {r['experienciador_marca']}")
                in_fte = t in _norm(f"{r['fuente_marca']} {r['fuente_inferencia']}")
                if in_exp or in_fte:
                    n_emo += 1
                if in_exp and _norm(r["experienciador"]):
                    exp_set.add(_norm(r["experienciador"]))
                if in_fte and _norm(r["fuente_inferencia"]):
                    fte_set.add(_norm(r["fuente_inferencia"]))
    return {
        "frases": n_frases,
        "emociones": n_emo,
        "experienciadores": len(exp_set),
        "fuentes": len(fte_set),
    }


def list_search_options(db_path: Path) -> dict[str, list[str]]:
    """Valores distintos para la búsqueda por selección.

    Claves: 'emociones' (canónicas con fallback a crudas), 'experienciadores',
    'fuentes', 'actores'.
    """
    emos: set[str] = set()
    exps: set[str] = set()
    ftes: set[str] = set()
    actores: set[str] = set()
    with _ro_connect(db_path) as conn:
        if conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='emociones'"
        ).fetchone():
            for r in conn.execute(
                "SELECT tipo_emocion, tipo_emocion_canonico, "
                "experienciador, fuente_inferencia FROM emociones"
            ):
                emo = (r["tipo_emocion_canonico"] or r["tipo_emocion"] or "").strip()
                if emo:
                    emos.add(emo)
                if (r["experienciador"] or "").strip():
                    exps.add(r["experienciador"].strip())
                if (r["fuente_inferencia"] or "").strip():
                    ftes.add(r["fuente_inferencia"].strip())
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
    """Frases (codigo, unit_idx) asociadas a una emoción/experienciador/fuente/actor."""
    keys: list[tuple[str, int]] = []
    with _ro_connect(db_path) as conn:
        if kind in ("emocion", "experienciador", "fuente"):
            if kind == "emocion":
                sql = ("SELECT DISTINCT codigo, frase_idx FROM emociones "
                       "WHERE tipo_emocion_canonico = ? OR tipo_emocion = ?")
                params: tuple = (value, value)
            elif kind == "experienciador":
                sql = ("SELECT DISTINCT codigo, frase_idx FROM emociones "
                       "WHERE experienciador = ?")
                params = (value,)
            else:
                sql = ("SELECT DISTINCT codigo, frase_idx FROM emociones "
                       "WHERE fuente_inferencia = ?")
                params = (value,)
            for r in conn.execute(sql, params):
                keys.append((r["codigo"], int(r["frase_idx"])))
        elif kind == "actor" and _menciones_exists(conn):
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
        exp_canon = _marca_canonico_map(conn, "experienciador")
        fte_canon = _marca_canonico_map(conn, "fuente")
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
        exp_key = (r["codigo"], (r["experienciador_marca"] or "").strip().lower())
        fte_key = (r["codigo"], (r["fuente_marca"] or "").strip().lower())
        exp_c = exp_canon.get(exp_key, "")
        fte_c = fte_canon.get(fte_key, "")
        records.append({
            "codigo": r["codigo"],
            "frase_idx": r["frase_idx"],
            "emocion_idx": r["emocion_idx"],
            "frase": r["frase"] or "",
            "tipo_emocion": r["tipo_emocion"] or "",
            "tipo_emocion_canonico": r["tipo_emocion_canonico"] or r["tipo_emocion"] or "",
            "experienciador": r["experienciador"] or "",
            "experienciador_canonico": exp_c,
            "experienciador_semas": sorted(semas.get(exp_c, set())),
            "fuente_inferencia": r["fuente_inferencia"] or "",
            "fuente_canonico": fte_c,
            "fuente_semas": sorted(semas.get(fte_c, set())),
            "mediador": (med.get("tipo") if isinstance(med, dict) else "") or "",
            "verificador_normativo": (vn.get("tipo") if isinstance(vn, dict) else "") or "",
            "verificador_observacional": (vo.get("tipo") if isinstance(vo, dict) else "") or "",
            "operador_modificacion": (om.get("funcion") if isinstance(om, dict) else "") or "",
        })
    return pd.DataFrame.from_records(records)


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
    db_path: Path, only_pending: bool = True
) -> list[dict[str, Any]]:
    """Sugerencias deícticas agrupadas por marca/mención.

    Devuelve, por mención con vínculos de deixis (`origin='deixis_llm'`):
    marca, funciones, frase, código/unidad y la lista de referentes sugeridos
    (canónico concreto, tipo deíctico y estado). Con `only_pending`, solo las
    menciones que tienen al menos un referente deíctico aún sin revisar.
    """
    with _ro_connect(db_path) as conn:
        if not _menciones_exists(conn):
            return []
        links = conn.execute(
            "SELECT mencion_id, canonical_id, deixis_tipo, status "
            "FROM mencion_canonico WHERE origin = 'deixis_llm'"
        ).fetchall()
        if not links:
            return []

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
        if not mids:
            return []

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
            "referentes": sorted(by_men[mid], key=lambda r: r["deixis_tipo"]),
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
        sql = ("SELECT codigo, frase_idx, tipo_emocion, tipo_emocion_canonico, "
               "experienciador, fuente_inferencia FROM emociones")
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
            if (r["experienciador"] or "").strip():
                d["experienciadores"].add(r["experienciador"].strip())
            if (r["fuente_inferencia"] or "").strip():
                d["fuentes"].add(r["fuente_inferencia"].strip())
    return {k: {kk: sorted(vv) for kk, vv in v.items()} for k, v in out.items()}
