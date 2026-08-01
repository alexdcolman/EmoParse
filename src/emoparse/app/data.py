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
from collections.abc import Iterable, Iterator
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
from emoparse.storage.posts import cita_embebida

#: Importado desde el runner para mantener una única fuente de verdad
#: sobre el orden y definición de stages.
from emoparse.pipeline.runner import STAGE_ORDER

#: El estado por stage lo resuelve el pipeline, que es quien sabe el alcance
#: de cada una; acá solo se reexpone para las tabs.
from emoparse.pipeline import status as stage_status

#: Resolución del referente canónico de una emoción: la misma que usan las
#: stages y el export, para que ninguna tab muestre algo distinto.
from emoparse.storage.referencia import (
    canonicos_de_override,
    hay_base_de_marcas,
    marca_canonicos_index,
    resolver_canonico,
    resolver_canonicos,
)


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


# ══════════════════════════════════════════════════════════════════════════════
#  Reexports desde storage.simulacros
#
#  La reconstrucción del simulacro (prelación de referentes, semas, actantes,
#  caracterización) vive en la capa de storage porque la comparten la app, el
#  análisis de redes y el export. Acá se reexpone con los nombres que las tabs
#  ya consumen, para que ninguna tenga que cambiar de import.
# ══════════════════════════════════════════════════════════════════════════════

from emoparse.storage.simulacros import (
    _ACTANTE_FLAT,
    _build_filter_sql,
    _canon_col,
    _canonico_semas_map,
    _discurso_enunciador_map,
    _discurso_len_map,
    _frase_mention_canonicos,
    _json_or_none,
    _menciones_exists,
    _parse_json,
    _resolve_marca_canonicos,
    _unpack_json_dict,
    get_emociones,
    get_emociones_enriched,
)

#: Re-export: el estado por stage lo calcula `pipeline.status`, que es la
#: fuente única del criterio de conteo (la comparte el subcomando `status`).
StageStatus = stage_status.StageStatus


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
    """Estado de cada stage del run, en orden topológico.

    Delega en `pipeline.status`, que define el alcance de cada stage y
    distingue lo pendiente de lo que queda fuera de ese alcance.
    """
    with _ro_connect(db_path) as conn:
        return stage_status.collect_stage_statuses(conn)


def _table_cols(conn: sqlite3.Connection, table: str) -> set[str]:
    """Columnas de una tabla, o conjunto vacío si la tabla no existe."""
    if conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
    ).fetchone() is None:
        return set()
    return {r["name"] for r in conn.execute(f"PRAGMA table_info({table})")}


# ══════════════════════════════════════════════════════════════════════════════
#  Helpers internos
# ══════════════════════════════════════════════════════════════════════════════





def _stage_status_from(payload: str | None, error: str | None) -> str:
    """payload + error → 'completed' | 'failed' | 'pending'."""
    if payload is not None:
        return "completed"
    if error is not None:
        return "failed"
    return "pending"




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









def get_experienciador_canonico_map(
    db_path: Path, codigo: str
) -> dict[tuple[int, int], str]:
    """(unit_idx, emocion_idx) → el experienciador canónico de esa emoción.

    Uno solo por emoción: la atribución manual si la hay, el vínculo
    marca↔referente de mayor prelación si no, y el canónico de la inferencia
    como piso. Cuando una marca liga varios referentes aceptados, la emoción ya
    fue desdoblada en la base (una por referente).
    """
    return {
        key: canonicos[0]
        for key, canonicos in _resolve_marca_canonicos(
            db_path, codigo, "experienciador",
            "experienciador_marca", "experienciador", "experienciador_canonico",
        ).items()
    }


def get_fuente_canonicos_map(
    db_path: Path, codigo: str
) -> dict[tuple[int, int], list[str]]:
    """(unit_idx, emocion_idx) → los referentes canónicos de la fuente.

    Misma prelación que `get_experienciador_canonico_map`, pero la fuente de
    una emoción puede combinar entidades y se devuelven todas.
    """
    return _resolve_marca_canonicos(
        db_path, codigo, "fuente",
        "fuente_marca", "fuente_inferencia", "fuente_canonico",
    )


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
                exp_canon = resolver_canonico(
                    exp_units.get((r["codigo"], int(r["frase_idx"]))),
                    r["experienciador_marca"],
                    inferencia=r["experienciador"],
                )
                fte_cids = resolver_canonicos(
                    fte_units.get((r["codigo"], int(r["frase_idx"]))),
                    r["fuente_marca"],
                    inferencia=r["fuente_inferencia"],
                )
                exp_cids = [exp_canon] if exp_canon else []
                # Texto buscable: inferencia + marca + canónico resuelto, para
                # que coincida igual que lo que muestra la búsqueda.
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
        emo_cols = {r["name"] for r in conn.execute("PRAGMA table_info(emociones)")}
        sel_exp_c = ("e.experienciador_canonico" if "experienciador_canonico" in emo_cols
                     else "NULL AS experienciador_canonico")
        sel_fte_c = ("e.fuente_canonico" if "fuente_canonico" in emo_cols
                     else "NULL AS fuente_canonico")
        rows = conn.execute(
            "SELECT e.codigo, e.frase_idx, e.emocion_idx, "
            "e.experienciador, e.experienciador_marca, "
            "e.tipo_emocion, e.tipo_emocion_canonico, "
            "e.fuente_marca, e.fuente_inferencia, "
            f"{sel_exp_c}, {sel_fte_c}, "
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
        # Misma prelación que Revisión y Referentes: atribución por emoción
        # (columna canónica) > vínculo marca↔referente > canónico inferido.
        exp_c = resolver_canonico(
            exp_units.get((r["codigo"], r["frase_idx"])),
            r["experienciador_marca"],
            override=r["experienciador_canonico"],
            inferencia=r["experienciador"],
        )
        fte_cids = resolver_canonicos(
            fte_units.get((r["codigo"], r["frase_idx"])),
            r["fuente_marca"],
            override=r["fuente_canonico"],
            inferencia=r["fuente_inferencia"],
        )
        fte_c = "; ".join(fte_cids)
        exp_semas = semas.get(exp_c, set()) if exp_c else set()
        fte_semas: set = (
            set().union(*(semas.get(c, set()) for c in fte_cids))
            if fte_cids else set()
        )
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

    Devuelve, por mención con vínculos deícticos (propuestos por el stage o
    agregados a mano en esta tab): marca, funciones, frase, código/unidad y la
    lista de referentes (canónico concreto, tipo deíctico, estado, origen y en
    qué simulacros de la unidad rige). Con `only_pending`, solo las
    menciones con al menos un referente deíctico aún sin revisar. Con
    `include_unlinked`, suma además las marcas deícticas (1ª/2ª persona) que NO
    tienen ningún vínculo deíctico, con `referentes=[]`, para poder asignarles
    uno a mano (p. ej. un auditorio agregado después en Enunciación).
    """
    with _ro_connect(db_path) as conn:
        if not _menciones_exists(conn):
            return []
        # Vínculos deícticos: los que propuso el stage y los que se agregaron
        # a mano desde esta tab (que llevan tipo deíctico). Un vínculo humano
        # sin tipo viene de la tab Referentes y no se revisa acá.
        links = conn.execute(
            "SELECT mencion_id, canonical_id, deixis_tipo, status, origin "
            "FROM mencion_canonico "
            "WHERE origin IN ('deixis_llm', 'deixis') "
            "   OR (origin = 'human' AND deixis_tipo IS NOT NULL)"
        ).fetchall()

        by_men: dict[int, list[dict[str, Any]]] = {}
        for r in links:
            by_men.setdefault(r["mencion_id"], []).append({
                "canonical_id": r["canonical_id"],
                "deixis_tipo": r["deixis_tipo"] or "",
                "status": r["status"],
                "origin": r["origin"],
            })
        mids = list(by_men)

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
        aplicados = _deixis_aplicados(conn, codigos)
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
        unidad = (info["codigo"], int(info["unit_idx"]))
        referentes = sorted(by_men.get(mid, []), key=lambda r: r["deixis_tipo"])
        for ref in referentes:
            ref["aplicado_en"] = aplicados.get(unidad, {}).get(
                ref["canonical_id"], []
            )
        pendiente = any(
            r["status"] != "rejected" and not r["aplicado_en"] for r in referentes
        ) or not referentes
        if only_pending and not pendiente:
            continue
        out.append({
            "mencion_id": mid,
            "codigo": info["codigo"],
            "unit_idx": info["unit_idx"],
            "marca": info["marca"],
            "funciones": sorted(set(func.get(mid, []))),
            "frase": frase_map.get(unidad, ""),
            "referentes": referentes,
        })
    out.sort(key=lambda d: (d["codigo"], d["unit_idx"], d["mencion_id"]))
    return out


def _deixis_aplicados(
    conn: sqlite3.Connection, codigos: list[str]
) -> dict[tuple[str, int], dict[str, list[str]]]:
    """Por unidad, en qué simulacros rige cada referente por atribución.

    Un referente está aplicado cuando alguna emoción de la unidad lo fijó como
    experienciador o como fuente. Es lo que distingue una sugerencia todavía
    sin usar de una que ya gobierna un simulacro.
    """
    out: dict[tuple[str, int], dict[str, list[str]]] = {}
    if not codigos or conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='emociones'"
    ).fetchone() is None:
        return out
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(emociones)")}
    qc = ",".join("?" * len(codigos))
    for r in conn.execute(
        "SELECT codigo, frase_idx, emocion_idx, "
        f"{_canon_col(cols, 'experienciador_canonico')}, "
        f"{_canon_col(cols, 'fuente_canonico')} "
        f"FROM emociones WHERE codigo IN ({qc})",
        tuple(codigos),
    ):
        unidad = (r["codigo"], int(r["frase_idx"]))
        etiqueta = f"#{int(r['emocion_idx'])}"
        for campo in ("experienciador_canonico", "fuente_canonico"):
            for cid in canonicos_de_override(r[campo]):
                destinos = out.setdefault(unidad, {}).setdefault(cid, [])
                if etiqueta not in destinos:
                    destinos.append(etiqueta)
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
            # Experienciadores/fuentes: el canónico de cada emoción; si no hay
            # con qué resolverlo, la inferencia cruda del LLM.
            exp_canon = resolver_canonico(
                exp_units.get((r["codigo"], int(r["frase_idx"]))),
                r["experienciador_marca"],
                inferencia=r["experienciador"],
            )
            if exp_canon:
                d["experienciadores"].add(exp_canon)
            elif (r["experienciador"] or "").strip():
                d["experienciadores"].add(r["experienciador"].strip())
            fte_cids = resolver_canonicos(
                fte_units.get((r["codigo"], int(r["frase_idx"]))),
                r["fuente_marca"],
                inferencia=r["fuente_inferencia"],
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
    fallback al crudo), su `emocion_idx` y las marcas de ambos roles.

    Las marcas permiten saber qué simulacros toca una marca dada, que es lo que
    necesita la tab Deixis para ofrecer reemplazar o añadir por emoción.

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
            exp = resolver_canonico(
                exp_units.get(key), r["experienciador_marca"],
                override=exp_override, inferencia=r["experienciador"],
            ) or "—"
            fte_override = (r["fuente_canonico"] or "").strip()
            fte = "; ".join(resolver_canonicos(
                fte_units.get(key), r["fuente_marca"],
                override=fte_override, inferencia=r["fuente_inferencia"],
            )) or "—"
            emo = (r["tipo_emocion_canonico"] or r["tipo_emocion"] or "").strip() or "—"
            modo = (r["modo_existencia"] or "").strip() or "—"
            out.setdefault(key, []).append({
                "emocion_idx": int(r["emocion_idx"]),
                "experienciador": exp,
                "experienciador_marca": (r["experienciador_marca"] or "").strip(),
                "experienciador_fijado": bool(exp_override),
                "emocion": emo,
                "modo": modo,
                "fuente": fte,
                "fuente_marca": (r["fuente_marca"] or "").strip(),
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


# ══════════════════════════════════════════════════════════════════════════════
#  Corpus de posts (género tuit): lectores para las tabs de tecnodiscurso
# ══════════════════════════════════════════════════════════════════════════════

def has_posts(db_path: Path) -> bool:
    """True si el run contiene un corpus de posts (habilita las tabs tuit)."""
    with _ro_connect(db_path) as conn:
        row = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='posts'"
        ).fetchone()
        if row is None:
            return False
        n = conn.execute("SELECT COUNT(*) FROM posts").fetchone()[0]
        return int(n) > 0


def get_posts(db_path: Path) -> pd.DataFrame:
    """Posts del corpus con métricas desplegadas (metricas__likes, ...)."""
    with _ro_connect(db_path) as conn:
        rows = conn.execute(
            "SELECT * FROM posts ORDER BY fecha, post_id"
        ).fetchall()
    if not rows:
        return pd.DataFrame()
    records = []
    for row in rows:
        rec = {k: row[k] for k in row.keys() if k not in ("metricas", "raw")}
        rec.update(_unpack_json_dict(row["metricas"], prefix="metricas__"))
        records.append(rec)
    return pd.DataFrame(records)


def get_hilos(db_path: Path, min_posts: int = 2) -> pd.DataFrame:
    """Hilos del corpus (conversaciones con al menos `min_posts` posts)."""
    with _ro_connect(db_path) as conn:
        rows = conn.execute(
            "SELECT * FROM hilos WHERE n_posts >= ? "
            "ORDER BY n_posts DESC, conversacion_id",
            (min_posts,),
        ).fetchall()
    df = pd.DataFrame([dict(r) for r in rows])
    if not df.empty:
        df["participantes"] = df["participantes"].map(_parse_json)
    return df


def get_posts_de_hilo(db_path: Path, conversacion_id: str) -> pd.DataFrame:
    """Posts de una conversación en orden cronológico, con su foria dominante."""
    with _ro_connect(db_path) as conn:
        rows = conn.execute(
            "SELECT * FROM posts WHERE conversacion_id = ? "
            "ORDER BY fecha, post_id",
            (conversacion_id,),
        ).fetchall()
        forias = _foria_dominante_map(conn)
    if not rows:
        return pd.DataFrame()
    return pd.DataFrame([_post_record(r, forias) for r in rows])


def _foria_dominante_map(conn: sqlite3.Connection) -> dict[str, str]:
    """Foria dominante por post desde la caracterización de sus emociones."""
    try:
        rows = conn.execute(
            "SELECT codigo, caracterizacion_payload FROM emociones "
            "WHERE caracterizacion_payload IS NOT NULL"
        ).fetchall()
    except sqlite3.OperationalError:
        return {}
    conteo: dict[str, dict[str, int]] = {}
    for row in rows:
        payload = _parse_json(row["caracterizacion_payload"])
        if not isinstance(payload, dict):
            continue
        foria = str(payload.get("foria") or "indeterminado")
        codigo = str(row["codigo"])
        conteo.setdefault(codigo, {})
        conteo[codigo][foria] = conteo[codigo].get(foria, 0) + 1
    return {
        codigo: max(forias, key=forias.get)  # type: ignore[arg-type]
        for codigo, forias in conteo.items()
    }


def get_posts_citadores(db_path: Path) -> pd.DataFrame:
    """Posts que citan o repostean, con su reframing y el post citado.

    Es el alcance de la stage `reframing` (citas y reposts con comentario)
    más los reposts puros, que no se clasifican pero sí registran
    circulación. Se lee del corpus entero y no de un hilo: una cita no crea
    conversación, así que la mayoría de estos posts no aparece en `hilos`.
    """
    with _ro_connect(db_path) as conn:
        try:
            rows = conn.execute(
                "SELECT p.*, q.texto AS citado_texto, "
                "q.autor_handle AS citado_autor, q.fecha AS citado_fecha "
                "FROM posts p "
                "LEFT JOIN posts q "
                "  ON q.post_id = COALESCE(p.cita_a, p.reposteo_a) "
                "WHERE p.cita_a IS NOT NULL OR p.reposteo_a IS NOT NULL "
                "ORDER BY p.fecha, p.post_id"
            ).fetchall()
        except sqlite3.OperationalError:
            return pd.DataFrame()
        forias = _foria_dominante_map(conn)
    if not rows:
        return pd.DataFrame()
    return pd.DataFrame([_post_record(row, forias) for row in rows])


def get_posts_por_id(
    db_path: Path, post_ids: Iterable[str],
) -> dict[str, dict[str, Any]]:
    """Posts por id, en una sola consulta (para embeber los citados)."""
    ids = sorted({str(p) for p in post_ids if p})
    if not ids:
        return {}
    marcas = ",".join("?" * len(ids))
    with _ro_connect(db_path) as conn:
        try:
            rows = conn.execute(
                f"SELECT * FROM posts WHERE post_id IN ({marcas})", ids
            ).fetchall()
        except sqlite3.OperationalError:
            return {}
        forias = _foria_dominante_map(conn)
    return {str(r["post_id"]): _post_record(r, forias) for r in rows}


def get_emociones_de_posts(
    db_path: Path,
    codigos: Iterable[str],
    max_por_post: int = 6,
) -> dict[str, list[dict[str, Any]]]:
    """Emociones materializadas de un conjunto de discursos, en breve.

    Para reponer en el dashboard las emociones del post citado cuando ese
    post es unidad del corpus. Prefiere los canónicos (revisados o resueltos
    por referencia) sobre la inferencia cruda, igual que el bloque que
    `reframing` recibe en el prompt, para que la tab y el agente hablen de
    lo mismo.
    """
    ids = sorted({str(c) for c in codigos if c})
    if not ids:
        return {}
    marcas = ",".join("?" * len(ids))
    out: dict[str, list[dict[str, Any]]] = {}
    with _ro_connect(db_path) as conn:
        try:
            rows = conn.execute(
                f"SELECT * FROM emociones WHERE codigo IN ({marcas}) "
                "ORDER BY codigo, frase_idx, emocion_idx",
                ids,
            ).fetchall()
        except sqlite3.OperationalError:
            return {}
    for r in rows:
        d = dict(r)
        destino = out.setdefault(str(d["codigo"]), [])
        if len(destino) >= max_por_post:
            continue
        caracterizacion = _parse_json(d.get("caracterizacion_payload")) or {}
        destino.append({
            "tipo": (
                d.get("tipo_emocion_canonico") or d.get("tipo_emocion") or "?"
            ),
            "experienciador": (
                d.get("experienciador_canonico")
                or d.get("experienciador") or "?"
            ),
            "fuente": (
                d.get("fuente_canonico") or d.get("fuente_inferencia") or ""
            ),
            "foria": caracterizacion.get("foria"),
        })
    return out


def _post_record(row: sqlite3.Row, forias: dict[str, str]) -> dict[str, Any]:
    """Fila de `posts` → dict con foria dominante, reframing y cita embebida.

    `raw` no viaja al dashboard (es el payload completo de la fuente), pero sí
    lo único que hace falta de él: la copia del post citado, para los citados
    que no están en el corpus.
    """
    claves = row.keys()
    rec = {k: row[k] for k in claves if k not in ("metricas", "raw")}
    rec["foria_dominante"] = forias.get(str(row["post_id"]))
    rec["reframing"] = (
        _parse_json(row["reframing_payload"])
        if "reframing_payload" in claves else None
    )
    rec["cita_embebida"] = (
        cita_embebida(_parse_json(row["raw"])) if "raw" in claves else None
    )
    return rec


def get_tecno_resumen(db_path: Path) -> pd.DataFrame:
    """Conteo de tecno-entidades por tipo y valor normalizado."""
    with _ro_connect(db_path) as conn:
        try:
            rows = conn.execute(
                "SELECT tipo, valor_norm, COUNT(*) AS n, "
                "COUNT(DISTINCT codigo) AS n_posts "
                "FROM tecno_entidades GROUP BY tipo, valor_norm "
                "ORDER BY tipo, n DESC"
            ).fetchall()
        except sqlite3.OperationalError:
            return pd.DataFrame()
    return pd.DataFrame([dict(r) for r in rows])


def get_emojis_con_afecto(db_path: Path) -> pd.DataFrame:
    """Usos de emoji con su afecto resuelto (léxico o LLM).

    Devuelve una fila por ocurrencia, pero con el bloque de repetición
    desplegado: `primario` marca la que representa a su racha (🤣🤣🤣 es un
    gesto, no tres) y `repeticiones`/`intensidad` la caracterizan. Las
    lecturas que cuentan gestos filtran por `primario`; las que cuentan
    pulsaciones, no.
    """
    with _ro_connect(db_path) as conn:
        try:
            rows = conn.execute(
                "SELECT codigo, unit_idx, valor, extra FROM tecno_entidades "
                "WHERE tipo = 'emoji'"
            ).fetchall()
        except sqlite3.OperationalError:
            return pd.DataFrame()
    return pd.DataFrame([
        {
            "codigo": row["codigo"],
            "unit_idx": row["unit_idx"],
            "emoji": row["valor"],
            **_afecto_record(_parse_json(row["extra"])),
        }
        for row in rows
    ])


def _afecto_record(extra: Any) -> dict[str, Any]:
    """Afecto y repetición de un uso de emoji, desde su columna `extra`.

    Los usos anteriores a la agrupación por rachas no tienen bloque
    `repeticion`: cuentan como racha de uno, que es lo que eran.
    """
    extra = extra if isinstance(extra, dict) else {}
    afecto = extra.get("afecto")
    afecto = afecto if isinstance(afecto, dict) else {}
    rep = extra.get("repeticion")
    rep = rep if isinstance(rep, dict) else {}
    return {
        "candidato": afecto.get("candidato"),
        "foria": afecto.get("foria"),
        "origin": afecto.get("origin"),
        "justificacion": afecto.get("justificacion"),
        "repeticiones": int(rep.get("n", 1)),
        "primario": bool(rep.get("primario", True)),
        "intensidad": rep.get("intensidad", "simple"),
        "inicio_racha": rep.get("inicio"),
        "fin_racha": rep.get("fin"),
    }


def get_hashtags_analizados(db_path: Path) -> pd.DataFrame:
    """Hashtags con caracterización semiótica (y los pendientes, con n_usos).

    `funcion`/`foria_entorno` son las dominantes derivadas por agregación de
    los usos; `distribucion` formatea la distribución completa de funciones
    del `analisis_payload` ('' si el hashtag aún no fue analizado).
    """
    with _ro_connect(db_path) as conn:
        try:
            rows = conn.execute(
                "SELECT valor_norm, n_usos, funcion, acoplamiento, "
                "foria_entorno, justificacion, analisis_payload, "
                "analisis_error FROM hashtags ORDER BY n_usos DESC"
            ).fetchall()
        except sqlite3.OperationalError:
            return pd.DataFrame()
    records = []
    for r in rows:
        rec = {k: r[k] for k in r.keys() if k != "analisis_payload"}
        payload = _parse_json(r["analisis_payload"]) or {}
        funciones = payload.get("funciones") if isinstance(payload, dict) else None
        rec["distribucion"] = (
            ", ".join(
                f"{f} ({n})"
                for f, n in sorted(
                    funciones.items(), key=lambda kv: -int(kv[1])
                )
            )
            if isinstance(funciones, dict) and funciones else ""
        )
        records.append(rec)
    return pd.DataFrame(records)


def get_posts_con_hashtag(db_path: Path, valor_norm: str) -> pd.DataFrame:
    """Posts que usan un hashtag (drill-down de la tab Hashtags)."""
    with _ro_connect(db_path) as conn:
        rows = conn.execute(
            "SELECT DISTINCT p.post_id, p.autor_handle, p.texto, p.fecha "
            "FROM tecno_entidades t JOIN posts p ON p.post_id = t.codigo "
            "WHERE t.tipo = 'hashtag' AND t.valor_norm = ? "
            "ORDER BY p.fecha",
            (valor_norm,),
        ).fetchall()
    return pd.DataFrame([dict(r) for r in rows])


def codigo_labels(db_path: Path) -> dict[str, str]:
    """Mapa codigo → etiqueta visible para los selectores y gráficos.

    Usa el título del input (`input_titulo`) cuando existe; si no, el código.
    En corpus de posts mejora la lectura: el código es el id técnico del post.
    """
    out: dict[str, str] = {}
    with _ro_connect(db_path) as conn:
        for r in conn.execute("SELECT codigo, input FROM discursos"):
            inp = _json_or_none(r["input"]) or {}
            titulo = str(inp.get("titulo") or "").strip() if isinstance(inp, dict) else ""
            out[str(r["codigo"])] = titulo or str(r["codigo"])
    # Unicidad: dos posts pueden compartir título; se desambigua con el código.
    vistos: dict[str, int] = {}
    for label in out.values():
        vistos[label] = vistos.get(label, 0) + 1
    for codigo, label in list(out.items()):
        if vistos[label] > 1 and label != codigo:
            out[codigo] = f"{label} · {codigo}"
    return out


def get_post_contexto(db_path: Path) -> pd.DataFrame:
    """Contexto conversacional por post: codigo, conversacion_id, fecha, autor.

    En corpus de posts, `codigo` coincide con `post_id`. Vacío si el run no
    trae posts.
    """
    with _ro_connect(db_path) as conn:
        try:
            rows = conn.execute(
                "SELECT post_id AS codigo, conversacion_id, fecha, "
                "autor_handle FROM posts"
            ).fetchall()
        except sqlite3.OperationalError:
            return pd.DataFrame()
    return pd.DataFrame([dict(r) for r in rows])


def get_post_hashtags(db_path: Path) -> pd.DataFrame:
    """Pares (codigo, hashtag) por cada uso de hashtag en el corpus de posts."""
    with _ro_connect(db_path) as conn:
        try:
            rows = conn.execute(
                "SELECT DISTINCT codigo, valor_norm AS hashtag "
                "FROM tecno_entidades WHERE tipo = 'hashtag'"
            ).fetchall()
        except sqlite3.OperationalError:
            return pd.DataFrame()
    return pd.DataFrame([dict(r) for r in rows])


def get_usos_hashtag(db_path: Path, valor_norm: str) -> pd.DataFrame:
    """Usos de un hashtag con su análisis por post (drill-down de la tab).

    Una fila por uso, con el post y, si la stage `hashtag_semiotics` corrió,
    la función, el acoplamiento y la foria de ese uso concreto.
    """
    with _ro_connect(db_path) as conn:
        try:
            rows = conn.execute(
                "SELECT t.codigo, t.extra, p.autor_handle, p.fecha, p.texto "
                "FROM tecno_entidades t "
                "LEFT JOIN posts p ON p.post_id = t.codigo "
                "WHERE t.tipo = 'hashtag' AND t.valor_norm = ? "
                "ORDER BY p.fecha, t.codigo",
                (valor_norm,),
            ).fetchall()
        except sqlite3.OperationalError:
            return pd.DataFrame()
    records = []
    for r in rows:
        extra = _parse_json(r["extra"]) or {}
        funcion = extra.get("funcion") if isinstance(extra, dict) else None
        funcion = funcion if isinstance(funcion, dict) else {}
        records.append({
            "codigo": r["codigo"],
            "autor_handle": r["autor_handle"],
            "fecha": r["fecha"],
            "texto": r["texto"],
            "funcion": funcion.get("funcion"),
            "acoplamiento": funcion.get("acoplamiento"),
            "foria_entorno": funcion.get("foria_entorno"),
            "justificacion": funcion.get("justificacion"),
        })
    return pd.DataFrame(records)


def get_tecno_usos(db_path: Path) -> pd.DataFrame:
    """Menciones, tecnografismos y URLs con su uso pragmático resuelto.

    Una fila por entidad, con el atributo determinista de cada tipo (posición
    de la mención, subtipo del tecnografismo, dominio de la URL) y, si la
    stage `tecno_usage` corrió, el uso en contexto y su justificación.
    """
    with _ro_connect(db_path) as conn:
        try:
            rows = conn.execute(
                "SELECT t.codigo, t.unit_idx, t.tipo, t.valor, t.valor_norm, "
                "t.extra, f.frase FROM tecno_entidades t "
                "LEFT JOIN frases f "
                "ON f.codigo = t.codigo AND f.unit_idx = t.unit_idx "
                "WHERE t.tipo IN ('mencion', 'tecnografismo', 'url') "
                "ORDER BY t.codigo, t.unit_idx, t.inicio"
            ).fetchall()
        except sqlite3.OperationalError:
            return pd.DataFrame()
    records = []
    for r in rows:
        extra = _parse_json(r["extra"]) or {}
        extra = extra if isinstance(extra, dict) else {}
        uso = extra.get("uso")
        uso = uso if isinstance(uso, dict) else {}
        records.append({
            "codigo": r["codigo"],
            "unit_idx": r["unit_idx"],
            "tipo": r["tipo"],
            "valor": r["valor"],
            "valor_norm": r["valor_norm"],
            # El dominio ya vive en valor_norm: es el atributo determinista
            # de la URL, equivalente a la posición o el subtipo de las otras.
            "atributo": (
                r["valor_norm"] if r["tipo"] == "url"
                else extra.get("posicion") or extra.get("subtipo") or ""
            ),
            "alcance": extra.get("alcance") or "",
            "uso": uso.get("uso"),
            "uso_justificacion": uso.get("justificacion"),
            "frase": r["frase"],
        })
    return pd.DataFrame(records)


def get_frases_con_emoji(db_path: Path, emoji: str) -> pd.DataFrame:
    """Frases donde aparece un emoji, con su afecto resuelto por racha."""
    with _ro_connect(db_path) as conn:
        try:
            rows = conn.execute(
                "SELECT t.codigo, t.unit_idx, t.extra, f.frase "
                "FROM tecno_entidades t "
                "LEFT JOIN frases f "
                "ON f.codigo = t.codigo AND f.unit_idx = t.unit_idx "
                "WHERE t.tipo = 'emoji' AND t.valor = ? "
                "ORDER BY t.codigo, t.unit_idx",
                (emoji,),
            ).fetchall()
        except sqlite3.OperationalError:
            return pd.DataFrame()
    return pd.DataFrame([
        {
            "codigo": r["codigo"],
            "unit_idx": r["unit_idx"],
            "frase": r["frase"],
            **_afecto_record(_parse_json(r["extra"])),
        }
        for r in rows
    ])


def get_tecno_of_unit(
    db_path: Path, codigo: str, unit_idx: int
) -> list[dict[str, Any]]:
    """Tecno-entidades de una unidad, con `extra` parseado (para Revisión)."""
    with _ro_connect(db_path) as conn:
        try:
            rows = conn.execute(
                "SELECT tipo, valor, valor_norm, extra FROM tecno_entidades "
                "WHERE codigo = ? AND unit_idx = ? ORDER BY inicio",
                (codigo, int(unit_idx)),
            ).fetchall()
        except sqlite3.OperationalError:
            return []
    out = []
    for r in rows:
        extra = _parse_json(r["extra"]) or {}
        out.append({
            "tipo": r["tipo"],
            "valor": r["valor"],
            "valor_norm": r["valor_norm"],
            "extra": extra if isinstance(extra, dict) else {},
        })
    return out


def agrupar_por_conversacion(
    db_path: Path, df: pd.DataFrame, modo: str
) -> pd.DataFrame:
    """Reagrupa un DataFrame de emociones de posts por conversación pública.

    `modo` es 'hashtag' (un grupo por hashtag; un post con dos hashtags
    integra ambos grupos) o 'hilo' (conversaciones con al menos dos posts).
    El `codigo` pasa a ser el id del grupo y `posicion`/`frase_idx`, el orden
    temporal del post dentro del grupo, de modo que las visualizaciones
    secuenciales representen la evolución de la conversación.
    """
    ctx = get_post_contexto(db_path)
    fechas = (
        dict(zip(ctx["codigo"].astype(str), ctx["fecha"]))
        if not ctx.empty else {}
    )
    if modo == "hashtag":
        pares = get_post_hashtags(db_path)
        if pares.empty:
            return pd.DataFrame()
        grupos = {
            f"#{tag}": sub["codigo"].astype(str).tolist()
            for tag, sub in pares.groupby("hashtag")
        }
    elif modo == "hilo":
        if ctx.empty:
            return pd.DataFrame()
        con_hilo = ctx[ctx["conversacion_id"].notna()]
        grupos = {
            str(conv): sub["codigo"].astype(str).tolist()
            for conv, sub in con_hilo.groupby("conversacion_id")
            if len(sub) >= 2
        }
    else:
        raise ValueError(f"Modo de agrupación desconocido: {modo!r}")
    partes: list[pd.DataFrame] = []
    for grupo_id, codigos in grupos.items():
        sub = df[df["codigo"].astype(str).isin(codigos)].copy()
        if sub.empty:
            continue
        orden = sorted(
            sub["codigo"].astype(str).unique(),
            key=lambda c: (str(fechas.get(c) or ""), c),
        )
        rank = {c: i for i, c in enumerate(orden)}
        sub["posicion"] = sub["codigo"].astype(str).map(rank)
        sub["frase_idx"] = sub["posicion"]
        sub["pos_max_discurso"] = max(rank.values()) if rank else 0
        sub["codigo"] = grupo_id
        partes.append(sub)
    if not partes:
        return pd.DataFrame()
    return pd.concat(partes, ignore_index=True)


def get_emociones_carac(db_path: Path) -> pd.DataFrame:
    """Emociones con la caracterización sin expandir.

    Insumo del acoplamiento emocional de `emoparse.network`, que parsea
    `caracterizacion_payload` por su cuenta; `get_emociones` lo despliega
    en columnas para el resto de la UI.
    """
    with _ro_connect(db_path) as conn:
        try:
            rows = conn.execute(
                "SELECT codigo, tipo_emocion, tipo_emocion_canonico, "
                "caracterizacion_payload FROM emociones"
            ).fetchall()
        except sqlite3.OperationalError:
            return pd.DataFrame()
    return pd.DataFrame([dict(r) for r in rows])


def get_red_metricas(db_path: Path, grafo: str) -> pd.DataFrame:
    """Métricas por nodo de un grafo persistido por `emoparse network`."""
    with _ro_connect(db_path) as conn:
        try:
            rows = conn.execute(
                "SELECT * FROM red_metricas WHERE grafo = ? "
                "ORDER BY pagerank DESC",
                (grafo,),
            ).fetchall()
        except sqlite3.OperationalError:
            return pd.DataFrame()
    return pd.DataFrame([dict(r) for r in rows])


def get_red_aristas(db_path: Path, grafo: str) -> pd.DataFrame:
    """Aristas de un grafo persistido."""
    with _ro_connect(db_path) as conn:
        try:
            rows = conn.execute(
                "SELECT origen, destino, SUM(peso) AS peso FROM aristas "
                "WHERE grafo = ? GROUP BY origen, destino",
                (grafo,),
            ).fetchall()
        except sqlite3.OperationalError:
            return pd.DataFrame()
    return pd.DataFrame([dict(r) for r in rows])


def list_red_grafos(db_path: Path) -> list[str]:
    """Grafos con aristas persistidas (vacío si `emoparse network` no corrió)."""
    with _ro_connect(db_path) as conn:
        try:
            rows = conn.execute(
                "SELECT DISTINCT grafo FROM aristas ORDER BY grafo"
            ).fetchall()
        except sqlite3.OperationalError:
            return []
    return [str(r["grafo"]) for r in rows]


def get_media_of_post(db_path: Path, post_id: str) -> list[dict[str, Any]]:
    """Adjuntos de un post con su descripción generada parseada."""
    with _ro_connect(db_path) as conn:
        try:
            rows = conn.execute(
                "SELECT * FROM media WHERE post_id = ? ORDER BY id", (post_id,)
            ).fetchall()
        except sqlite3.OperationalError:
            return []
    out = []
    for r in rows:
        d = dict(r)
        d["descripcion_payload"] = _parse_json(d.get("descripcion_payload"))
        out.append(d)
    return out
