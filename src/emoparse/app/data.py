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
    fuente, etc.) y metadata contextual de frase y discurso.
    """
    sql, params = _build_filter_sql(
        base="SELECT e.codigo, e.frase_idx, e.emocion_idx, "
             "e.experienciador, e.tipo_emocion, e.tipo_emocion_canonico, "
             "e.modo_existencia, "
             "e.deteccion_justificacion, "
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
            "tipo_emocion":            row["tipo_emocion"],
            "tipo_emocion_canonico":   row["tipo_emocion_canonico"],
            "modo_existencia":         row["modo_existencia"],
            "deteccion_justificacion": row["deteccion_justificacion"],
            "frase":                   row["frase"],
            "caracterizacion_error":   row["caracterizacion_error"],
        }
        # Caracterización flat: foria, dominancia, intensidad, fuente, etc.
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
