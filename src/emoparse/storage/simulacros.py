# ══════════════════════════════════════════════════════════════════════════════
#  emoparse.storage.simulacros
#
#  Lectura del simulacro emocional reconstruido, sobre la DB de un run.
#
#  Un simulacro es la emoción con todos sus componentes resueltos: quién la
#  experimenta, de qué tipo es, qué la origina, con qué actantes y con qué
#  caracterización. Reconstruirlo exige una prelación que no es obvia —la
#  atribución por emoción manda sobre el vínculo marca-referente, y este sobre
#  el crudo del modelo— y que tiene que ser la misma en todas partes: si el
#  dashboard y el análisis de redes resolvieran distinto, dos vistas del mismo
#  run dirían cosas distintas sobre la misma emoción.
#
#  Por eso vive en la capa de storage y no en la de la app: la consumen la app,
#  el análisis de redes y el export. Son funciones de lectura sobre una
#  conexión de solo lectura; no escriben nada.
# ══════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

import pandas as pd
from loguru import logger

from emoparse.storage.referencia import (
    hay_base_de_marcas,
    marca_canonicos_index,
    resolver_canonico,
    resolver_canonicos,
)


@contextmanager
def _ro_connect(db_path: Path) -> Iterator[sqlite3.Connection]:
    """Conexión de solo lectura a la DB de un run."""
    uri = f"file:{Path(db_path).resolve().as_posix()}?mode=ro"
    conn = sqlite3.connect(uri, uri=True, detect_types=sqlite3.PARSE_DECLTYPES)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()


def _table_cols(conn: sqlite3.Connection, table: str) -> set[str]:
    """Columnas de una tabla, o conjunto vacío si la tabla no existe."""
    if conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
    ).fetchone() is None:
        return set()
    return {r["name"] for r in conn.execute(f"PRAGMA table_info({table})")}


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


def _json_or_none(raw: Any) -> Any:
    """Parsea JSON o devuelve None."""
    if not raw:
        return None
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return None


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


def _menciones_exists(conn: sqlite3.Connection) -> bool:
    return conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='menciones'"
    ).fetchone() is not None


def _canon_col(cols: set[str], name: str) -> str:
    """Selecciona una columna canónica, o NULL si el run es anterior a ella."""
    return name if name in cols else f"NULL AS {name}"


def _resolve_marca_canonicos(
    db_path: str | Path,
    codigo: str,
    funcion: str,
    marca_field: str,
    inferencia_field: str,
    canonico_field: str,
) -> dict[tuple[int, int], list[str]]:
    """(unit_idx, emocion_idx) → los referentes canónicos del rol.

    Recorre la tabla `emociones`, no los payloads de la frase: el explode
    desdobla las emociones con experienciador coordinado, de modo que la
    posición en el payload no equivale al `emocion_idx` materializado. La
    atribución por emoción prima sobre la resolución por marca, y esta sobre
    los canónicos derivados de la inferencia.
    """
    out: dict[tuple[int, int], list[str]] = {}
    with _ro_connect(db_path) as conn:
        if conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='emociones'"
        ).fetchone() is None:
            return out
        per = _frase_mention_canonicos(conn, funcion, codigo)
        cols = {r["name"] for r in conn.execute("PRAGMA table_info(emociones)")}
        for r in conn.execute(
            "SELECT frase_idx, emocion_idx, "
            f"{marca_field} AS marca, {inferencia_field} AS inferencia, "
            f"{_canon_col(cols, canonico_field)} AS fijado "
            "FROM emociones WHERE codigo = ?",
            (codigo,),
        ):
            canonicos = resolver_canonicos(
                per.get((codigo, int(r["frase_idx"]))),
                r["marca"],
                override=r["fijado"],
                inferencia=r["inferencia"],
            )
            if canonicos:
                out[(int(r["frase_idx"]), int(r["emocion_idx"]))] = canonicos
    return out


def _frase_mention_canonicos(
    conn: sqlite3.Connection, funcion: str, codigo: str | None = None
) -> dict[tuple[str, int], dict[str, dict[str, tuple[int, int]]]]:
    """(codigo, unit_idx) → {marca_norm: {canonical_id: prelación}} de una función.

    Delega en `storage.referencia`, que es el criterio compartido con las
    stages y el export: Revisión, Simulacros y Búsqueda resuelven igual.
    """
    if not hay_base_de_marcas(conn):
        return {}
    return marca_canonicos_index(conn, funcion, codigo)


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
            "experienciador, experienciador_marca, "
            "fuente_inferencia, fuente_marca, "
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

            exp_c = resolver_canonico(
                exp_units.get(fkey), r["experienciador_marca"],
                override=r["experienciador_canonico"],
                inferencia=r["experienciador"],
            )
            fte_cids = resolver_canonicos(
                fte_units.get(fkey), r["fuente_marca"],
                override=r["fuente_canonico"],
                inferencia=r["fuente_inferencia"],
            )
            act = _parse_json(r["actantes_payload"]) or {}
            rec: dict[str, Any] = {
                "experienciador_canonicos": [exp_c] if exp_c else [],
                "experienciador_canonico": exp_c,
                "experienciador_semas": sorted(semas.get(exp_c, set())) if exp_c else [],
                "fuente_canonicos": fte_cids,
                "fuente_canonico": "; ".join(fte_cids),
                "fuente_semas": sorted(
                    set().union(*(semas.get(c, set()) for c in fte_cids))
                ) if fte_cids else [],
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
