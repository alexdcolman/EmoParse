# ══════════════════════════════════════════════════════════════════════════════
#  emoparse.pipeline.status
#
#  Estado de cada stage del pipeline sobre la DB de un run.
#
#  Fuente única del criterio de conteo: la consumen el subcomando `status` y
#  la tab Estado del dashboard, de modo que CLI y UI no puedan discrepar.
#
#  El conteo distingue cuatro cosas que antes se confundían en `pending`:
#
#  - pendiente: la unidad entra en el alcance de la stage y todavía no tiene
#    resultado ni error.
#  - no aplica: la unidad existe en el corpus pero está fuera del alcance de
#    la stage (un post sin cita no tiene reframing; un hashtag por debajo del
#    umbral de frecuencia no se analiza; un post sin tecnolingüísticos no
#    deja entidades). Sin esta distinción el porcentaje se calcula contra un
#    universo que la stage nunca iba a cubrir.
#  - fuera de alcance: la unidad fue excluida por un selector dinámico. No es
#    material no aplicable: una ejecución posterior sin selector debe poder
#    procesarla.
#  - no ejecutada: la stage no dejó registro en `run_metrics`, es decir que
#    no corrió en este run (opt-in no habilitada, o desactivada por el
#    género). Sus unidades no son pendientes: nadie las iba a procesar.
# ══════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from pathlib import Path

from emoparse.pipeline.dag import EMOPARSE_DAG

#: Orden de presentación: el topológico del pipeline.
STAGE_ORDER: tuple[str, ...] = EMOPARSE_DAG.toposort()

#: Umbral de usos por debajo del cual `hashtag_semiotics` no analiza un
#: hashtag. Espeja el default de `HashtagSemioticsStage.min_usos`: con 1 se
#: analizan todos, y la columna `no aplica` de la stage queda en cero.
MIN_USOS_HASHTAG = 1

#: Stages que persisten en `discursos` (1 fila = 1 discurso).
_DISCURSO_STAGES: frozenset[str] = frozenset({"summarizer", "metadata", "enunciation"})

#: Stages que persisten en `frases`, con su prefijo de columna.
_FRASE_STAGE_COL: dict[str, str] = {
    "actors": "actores",
    "emotions": "emociones",
    "emotions_pass2": "emociones_pass2",
}

#: Stages medidas a nivel emoción, con sus columnas (payload, error).
#: `normalize_emotions` no invoca LLM: no tiene columna de error.
_EMOCION_STAGE_COLS: dict[str, tuple[str, str | None]] = {
    "characterizer": ("caracterizacion_payload", "caracterizacion_error"),
    "actants": ("actantes_payload", "actantes_error"),
    "normalize_emotions": ("normalize_emotions_version", None),
}

#: Stages del corpus de posts: solo se listan si el run trae posts.
_POST_STAGES: frozenset[str] = frozenset(
    {
        "technoparse",
        "reframing",
        "hashtag_semiotics",
        "tecno_usage",
        "emoji_affect",
        "vision_describe",
    }
)

#: Atributo de `mencion_canonico` que resuelve cada stage de referente.
_REFERENTE_STAGE_ATTR: dict[str, str] = {"modalidad": "modalidad"}


@dataclass(frozen=True, slots=True)
class StageStatus:
    """Estado agregado de una stage dentro de un run.

    `pending`, `failed` y `completed` cubren el universo aplicable; `total`
    es su suma. `no_aplica` queda afuera de ese universo y del porcentaje.
    `unidad` nombra qué se cuenta: cada stage mide en su propia granularidad
    (discursos, frases, emociones, entidades), y sin decirlo los números se
    leen contra el total de posts, que casi nunca es el universo correcto.
    `failed_codigos` alimenta el detalle de errores de la UI.
    """

    stage: str
    pending: int = 0
    failed: int = 0
    completed: int = 0
    no_aplica: int = 0
    fuera_alcance: int = 0
    ejecutada: bool = False
    unidad: str = "unidades"
    failed_codigos: list[str] = field(default_factory=list)

    @property
    def total(self) -> int:
        """Unidades dentro del alcance de la stage."""
        return self.pending + self.failed + self.completed

    @property
    def pct(self) -> int | None:
        """Porcentaje completado sobre el universo aplicable.

        None cuando no hay universo que medir (stage sin unidades a su
        alcance): es distinto de 0%, que significa que hay trabajo sin hacer.
        """
        total = self.total
        return int(round(100 * self.completed / total)) if total else None


# ══════════════════════════════════════════════════════════════════════════════
#  API
# ══════════════════════════════════════════════════════════════════════════════


def collect_stage_statuses(conn: sqlite3.Connection) -> list[StageStatus]:
    """Estado de todas las stages del pipeline, en orden topológico."""
    ejecutadas = _stages_ejecutadas(conn)
    tiene_posts = _tabla_no_vacia(conn, "posts")
    out: list[StageStatus] = []
    for stage in STAGE_ORDER:
        if stage in _POST_STAGES and not tiene_posts:
            continue
        out.append(_status_de(conn, stage, stage in ejecutadas))
    return out


def collect_from_path(db_path: Path | str) -> list[StageStatus]:
    """Igual que `collect_stage_statuses`, abriendo la DB en solo lectura."""
    uri = f"file:{Path(db_path).resolve().as_posix()}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row
    try:
        return collect_stage_statuses(conn)
    finally:
        conn.close()


def _status_de(conn: sqlite3.Connection, stage: str, ejecutada: bool) -> StageStatus:
    """Despacha el conteo de una stage según su granularidad."""
    if stage in _DISCURSO_STAGES:
        return _discurso_stage(conn, stage, ejecutada)
    if stage in _FRASE_STAGE_COL:
        return _frase_stage(conn, stage, ejecutada)
    if stage == "explode_emotions":
        return _explode_stage(conn, ejecutada)
    if stage in _EMOCION_STAGE_COLS:
        return _emocion_stage(conn, stage, ejecutada)
    if stage == "judge":
        return _judge_stage(conn, ejecutada)
    if stage in ("deixis", "modalidad", "semas"):
        return _referente_stage(conn, stage, ejecutada)
    if stage in _POST_STAGES:
        return _post_stage(conn, stage, ejecutada)
    return StageStatus(stage=stage, ejecutada=ejecutada)


# ══════════════════════════════════════════════════════════════════════════════
#  Conteos por granularidad
# ══════════════════════════════════════════════════════════════════════════════


def _discurso_stage(conn: sqlite3.Connection, stage: str, ejecutada: bool) -> StageStatus:
    """Stage que escribe un payload por discurso."""
    return _payload_stage(
        conn,
        stage,
        ejecutada,
        tabla="discursos",
        col_payload=f"{stage}_payload",
        col_error=f"{stage}_error",
        col_codigo="codigo",
        unidad="discursos",
    )


def _frase_stage(conn: sqlite3.Connection, stage: str, ejecutada: bool) -> StageStatus:
    """Stage que escribe un payload por frase."""
    col = _FRASE_STAGE_COL[stage]
    return _payload_stage(
        conn,
        stage,
        ejecutada,
        tabla="frases",
        col_payload=f"{col}_payload",
        col_error=f"{col}_error",
        col_codigo="codigo",
        unidad="frases",
    )


def _payload_stage(
    conn: sqlite3.Connection,
    stage: str,
    ejecutada: bool,
    *,
    tabla: str,
    col_payload: str,
    col_error: str,
    col_codigo: str | None,
    scope: str = "1",
    unidad: str = "unidades",
) -> StageStatus:
    """Conteo genérico de una stage con payload, error y selector dinámico."""
    cols = _columnas(conn, tabla)
    if col_payload not in cols:
        return StageStatus(stage=stage, ejecutada=ejecutada)

    selector = _selector_clause(conn, stage, f"{tabla}.{col_codigo}") if col_codigo else "1"
    applicable = f"({scope}) AND ({selector})"
    pending = _uno(
        conn,
        f"SELECT COUNT(*) FROM {tabla} WHERE {applicable} "
        f"AND {col_payload} IS NULL AND {col_error} IS NULL",
    )
    failed = _uno(
        conn,
        f"SELECT COUNT(*) FROM {tabla} WHERE {applicable} AND {col_error} IS NOT NULL",
    )
    completed = _uno(
        conn,
        f"SELECT COUNT(*) FROM {tabla} WHERE {applicable} AND {col_payload} IS NOT NULL",
    )
    no_aplica = _uno(
        conn,
        f"SELECT COUNT(*) FROM {tabla} WHERE NOT ({scope}) AND ({selector})",
    )
    fuera = _uno(conn, f"SELECT COUNT(*) FROM {tabla} WHERE NOT ({selector})") if col_codigo else 0
    codigos: list[str] = []
    if col_codigo and failed:
        codigos = _lista(
            conn,
            f"SELECT DISTINCT {col_codigo} FROM {tabla} "
            f"WHERE {applicable} AND {col_error} IS NOT NULL "
            f"ORDER BY {col_codigo} LIMIT 50",
        )
    return StageStatus(
        stage=stage,
        pending=pending,
        failed=failed,
        completed=completed,
        no_aplica=no_aplica,
        fuera_alcance=fuera,
        ejecutada=ejecutada,
        unidad=unidad,
        failed_codigos=codigos,
    )


def _explode_stage(conn: sqlite3.Connection, ejecutada: bool) -> StageStatus:
    """`explode_emotions`, a nivel discurso y respetando el selector."""
    if "emociones" not in _tablas(conn):
        return StageStatus(stage="explode_emotions", ejecutada=ejecutada)
    selector_f = _selector_clause(conn, "explode_emotions", "frases.codigo")
    selector_e = _selector_clause(conn, "explode_emotions", "emociones.codigo")
    total = _uno(
        conn,
        f"SELECT COUNT(DISTINCT codigo) FROM frases WHERE {selector_f}",
    )
    completed = _uno(
        conn,
        f"SELECT COUNT(DISTINCT codigo) FROM emociones WHERE {selector_e}",
    )
    con_emociones = _uno(
        conn,
        "SELECT COUNT(DISTINCT codigo) FROM frases "
        f"WHERE ({selector_f}) AND {_TIENE_EMOCIONES_SQL}",
    )
    fuera = _uno(
        conn,
        f"SELECT COUNT(DISTINCT codigo) FROM frases WHERE NOT ({selector_f})",
    )
    pending = max(con_emociones - completed, 0)
    return StageStatus(
        stage="explode_emotions",
        pending=pending,
        completed=completed,
        no_aplica=max(total - completed - pending, 0),
        fuera_alcance=fuera,
        ejecutada=ejecutada,
        unidad="discursos",
    )


#: Frase cuya mejor lectura (pase 2 si corrió, si no pase 1) trae emociones.
_TIENE_EMOCIONES_SQL = """
json_array_length(
    CASE
        WHEN emociones_pass2_payload IS NOT NULL
             AND json_valid(emociones_pass2_payload)
        THEN emociones_pass2_payload
        WHEN json_valid(emociones_payload) THEN emociones_payload
        ELSE '[]'
    END
) > 0
""".strip()


def _emocion_stage(conn: sqlite3.Connection, stage: str, ejecutada: bool) -> StageStatus:
    """Stage medida sobre `emociones`, respetando alcance dinámico."""
    col_p, col_e = _EMOCION_STAGE_COLS[stage]
    cols = _columnas(conn, "emociones")
    if col_p not in cols:
        return StageStatus(stage=stage, ejecutada=ejecutada)
    tiene_error = col_e is not None and col_e in cols
    err = f"{col_e} IS NOT NULL" if tiene_error else "0"
    selector = _selector_clause(conn, stage, "emociones.codigo")
    return StageStatus(
        stage=stage,
        pending=_uno(
            conn,
            f"SELECT COUNT(*) FROM emociones WHERE ({selector}) "
            f"AND {col_p} IS NULL AND NOT ({err})",
        ),
        failed=(
            _uno(
                conn,
                f"SELECT COUNT(*) FROM emociones WHERE ({selector}) AND {err}",
            )
            if tiene_error
            else 0
        ),
        completed=_uno(
            conn,
            f"SELECT COUNT(*) FROM emociones WHERE ({selector}) AND {col_p} IS NOT NULL",
        ),
        fuera_alcance=_uno(
            conn,
            f"SELECT COUNT(*) FROM emociones WHERE NOT ({selector})",
        ),
        ejecutada=ejecutada,
        unidad="emociones",
        failed_codigos=(
            _lista(
                conn,
                f"SELECT DISTINCT codigo FROM emociones "
                f"WHERE ({selector}) AND {err} ORDER BY codigo LIMIT 50",
            )
            if tiene_error
            else []
        ),
    )


def _judge_stage(conn: sqlite3.Connection, ejecutada: bool) -> StageStatus:
    """`judge`: una emoción está juzgada cuando tiene veredicto."""
    tablas = _tablas(conn)
    if "emociones" not in tablas:
        return StageStatus(stage="judge", ejecutada=ejecutada)
    selector_e = _selector_clause(conn, "judge", "emociones.codigo")
    selector_j = _selector_clause(conn, "judge", "judgments.codigo")
    total = _uno(
        conn,
        f"SELECT COUNT(*) FROM emociones WHERE {selector_e}",
    )
    fuera = _uno(
        conn,
        f"SELECT COUNT(*) FROM emociones WHERE NOT ({selector_e})",
    )
    if "judgments" not in tablas:
        return StageStatus(
            stage="judge",
            pending=total,
            fuera_alcance=fuera,
            ejecutada=ejecutada,
            unidad="emociones",
        )
    completed = _uno(
        conn,
        f"SELECT COUNT(*) FROM judgments WHERE ({selector_j}) AND coherente IS NOT NULL",
    )
    failed = _uno(
        conn,
        f"SELECT COUNT(*) FROM judgments WHERE ({selector_j}) AND judge_error IS NOT NULL",
    )
    return StageStatus(
        stage="judge",
        pending=max(total - completed - failed, 0),
        failed=failed,
        completed=completed,
        fuera_alcance=fuera,
        ejecutada=ejecutada,
        unidad="emociones",
        failed_codigos=_lista(
            conn,
            f"SELECT DISTINCT codigo FROM judgments WHERE ({selector_j}) "
            "AND judge_error IS NOT NULL ORDER BY codigo LIMIT 50",
        ),
    )


def _referente_stage(conn: sqlite3.Connection, stage: str, ejecutada: bool) -> StageStatus:
    """Stages que anotan referentes o vínculos marca↔referente."""
    tablas = _tablas(conn)
    if "mencion_canonico" not in tablas:
        return StageStatus(stage=stage, ejecutada=ejecutada)

    if stage == "semas":
        if "canonico_semas" not in tablas:
            return StageStatus(stage=stage, ejecutada=ejecutada)
        selector = _selector_clause(conn, stage, "m.codigo")
        total = _uno(
            conn,
            "SELECT COUNT(DISTINCT mc.canonical_id) "
            "FROM mencion_canonico mc "
            "JOIN menciones m ON m.id = mc.mencion_id "
            f"WHERE {selector}",
        )
        total_global = _uno(
            conn,
            "SELECT COUNT(DISTINCT canonical_id) FROM mencion_canonico",
        )
        fuera = max(total_global - total, 0)
        cols = _columnas(conn, "mencion_canonico")
        if {"semas_version", "semas_error"}.issubset(cols):
            completed = _uno(
                conn,
                "SELECT COUNT(DISTINCT mc.canonical_id) "
                "FROM mencion_canonico mc "
                "JOIN menciones m ON m.id = mc.mencion_id "
                "WHERE mc.semas_version IS NOT NULL "
                "AND mc.semas_error IS NULL "
                f"AND {selector}",
            )
            failed = _uno(
                conn,
                "SELECT COUNT(DISTINCT mc.canonical_id) "
                "FROM mencion_canonico mc "
                "JOIN menciones m ON m.id = mc.mencion_id "
                "WHERE mc.semas_error IS NOT NULL "
                f"AND {selector}",
            )
            return StageStatus(
                stage=stage,
                pending=max(total - completed - failed, 0),
                failed=failed,
                completed=completed,
                fuera_alcance=fuera,
                ejecutada=ejecutada,
                unidad="referentes",
            )

        # Compatibilidad con DBs anteriores a schema v38: solo puede saberse
        # qué referentes dejaron al menos un sema.
        completed = _uno(
            conn,
            "SELECT COUNT(DISTINCT cs.canonical_id) "
            "FROM canonico_semas cs WHERE EXISTS ("
            "SELECT 1 FROM mencion_canonico mc "
            "JOIN menciones m ON m.id = mc.mencion_id "
            "WHERE mc.canonical_id = cs.canonical_id "
            f"AND {selector})",
        )
        return StageStatus(
            stage=stage,
            pending=max(total - completed, 0),
            completed=completed,
            fuera_alcance=fuera,
            ejecutada=ejecutada,
            unidad="referentes",
        )

    if stage == "deixis":
        # La stage recorre todos los discursos, pero solo deja vínculos donde
        # hay marcas de 1ª/2ª persona que resolver: el resto no es pendiente.
        selector_disc = _selector_clause(conn, stage, "discursos.codigo")
        selector_m = _selector_clause(conn, stage, "m.codigo")
        return _cobertura_barrida(
            conn,
            stage,
            ejecutada,
            total=_uno(conn, f"SELECT COUNT(*) FROM discursos WHERE {selector_disc}"),
            completed=_uno(
                conn,
                "SELECT COUNT(DISTINCT m.codigo) FROM mencion_canonico mc "
                "JOIN menciones m ON m.id = mc.mencion_id "
                f"WHERE mc.origin = 'deixis_llm' AND {selector_m}",
            ),
            fuera_alcance=_uno(
                conn,
                f"SELECT COUNT(*) FROM discursos WHERE NOT ({selector_disc})",
            ),
        )

    attr = _REFERENTE_STAGE_ATTR[stage]
    cols = _columnas(conn, "mencion_canonico")
    if attr not in cols:
        return StageStatus(stage=stage, ejecutada=ejecutada)
    # Dos cosas quedan fuera del universo de la stage: los vínculos rechazados
    # (no reciben modalidad por diseño) y, si la stage ya corrió, los que
    # barrió sin que el modelo devolviera un valor. Igual que en las stages de
    # tecno: barrido sin resultado no es trabajo pendiente. Sin ejecución, en
    # cambio, todo lo no rechazado sí está pendiente.
    aplica = "mc.status != 'rejected'" if "status" in cols else "1"
    selector = _selector_clause(conn, stage, "m.codigo")
    base = "FROM mencion_canonico mc JOIN menciones m ON m.id = mc.mencion_id "
    en_alcance = _uno(
        conn,
        f"SELECT COUNT(*) {base} WHERE ({aplica}) AND ({selector})",
    )
    completed = _uno(
        conn,
        f"SELECT COUNT(*) {base} WHERE ({aplica}) AND ({selector}) AND mc.{attr} IS NOT NULL",
    )
    rechazados = _uno(
        conn,
        f"SELECT COUNT(*) {base} WHERE NOT ({aplica}) AND ({selector})",
    )
    fuera = _uno(
        conn,
        f"SELECT COUNT(*) {base} WHERE NOT ({selector})",
    )
    sin_resultado = max(en_alcance - completed, 0)
    return StageStatus(
        stage=stage,
        pending=sin_resultado if not ejecutada else 0,
        completed=completed,
        no_aplica=rechazados + (sin_resultado if ejecutada else 0),
        fuera_alcance=fuera,
        ejecutada=ejecutada,
        unidad="vínculos marca-referente",
    )


def _post_stage(conn: sqlite3.Connection, stage: str, ejecutada: bool) -> StageStatus:
    """Stages del corpus de posts, cada una a su granularidad."""
    tablas = _tablas(conn)

    if stage == "technoparse":
        if "tecno_entidades" not in tablas:
            return StageStatus(stage=stage, ejecutada=ejecutada)
        # Determinista y de una sola pasada: los posts que no dejaron
        # entidades es porque no tenían tecnolingüísticos, no porque falten.
        selector_d = _selector_clause(conn, stage, "discursos.codigo")
        selector_t = _selector_clause(conn, stage, "tecno_entidades.codigo")
        return _cobertura_barrida(
            conn,
            stage,
            ejecutada,
            total=_uno(conn, f"SELECT COUNT(*) FROM discursos WHERE {selector_d}"),
            completed=_uno(
                conn,
                f"SELECT COUNT(DISTINCT codigo) FROM tecno_entidades WHERE {selector_t}",
            ),
            fuera_alcance=_uno(
                conn,
                f"SELECT COUNT(*) FROM discursos WHERE NOT ({selector_d})",
            ),
        )

    if stage == "reframing":
        # Solo califican las citas y los reposts con comentario propio: el
        # resto del corpus nunca entra en esta stage.
        return _payload_stage(
            conn,
            stage,
            ejecutada,
            tabla="posts",
            col_payload="reframing_payload",
            col_error="reframing_error",
            col_codigo="post_id",
            unidad="posts que citan",
            scope="es_repost_puro = 0 AND (cita_a IS NOT NULL OR "
            "(reposteo_a IS NOT NULL AND TRIM(texto) != ''))",
        )

    if stage == "vision_describe":
        return _payload_stage(
            conn,
            stage,
            ejecutada,
            tabla="media",
            col_payload="descripcion_payload",
            col_error="descripcion_error",
            col_codigo="post_id",
            unidad="imágenes",
            scope="tipo = 'imagen' AND (url IS NOT NULL OR path_local IS NOT NULL)",
        )

    if stage == "hashtag_semiotics":
        # Los hashtags por debajo del umbral de usos no se analizan.
        return _payload_stage(
            conn,
            stage,
            ejecutada,
            tabla="hashtags",
            col_payload="analisis_payload",
            col_error="analisis_error",
            col_codigo=None,
            unidad="hashtags",
            scope=f"n_usos >= {MIN_USOS_HASHTAG}",
        )

    if "tecno_entidades" not in tablas:
        return StageStatus(stage=stage, ejecutada=ejecutada)

    if stage == "emoji_affect":
        alcance = "tipo = 'emoji'"
        clave, err_key = "afecto", "afecto_error"
        unidad = "emojis"
    else:  # tecno_usage
        alcance = "tipo IN ('mencion', 'tecnografismo', 'url')"
        clave, err_key = "uso", "uso_error"
        unidad = "tecno-entidades"
    selector = _selector_clause(conn, stage, "tecno_entidades.codigo")
    total = _uno(
        conn,
        f"SELECT COUNT(*) FROM tecno_entidades WHERE ({alcance}) AND ({selector})",
    )
    completed = _uno(
        conn,
        f"SELECT COUNT(*) FROM tecno_entidades WHERE ({alcance}) "
        f"AND ({selector}) AND json_extract(extra, '$.{clave}') IS NOT NULL",
    )
    failed = _uno(
        conn,
        f"SELECT COUNT(*) FROM tecno_entidades WHERE ({alcance}) "
        f"AND ({selector}) AND json_extract(extra, '$.{err_key}') IS NOT NULL",
    )
    fuera = _uno(
        conn,
        f"SELECT COUNT(*) FROM tecno_entidades WHERE ({alcance}) AND NOT ({selector})",
    )
    # Barrido de una sola pasada: si la stage corrió, lo que quedó sin
    # resolver y sin error es una entidad que el modelo no devolvió, no
    # trabajo por hacer. Sin ejecución, en cambio, todo está pendiente.
    resto = max(total - completed - failed, 0)
    return StageStatus(
        stage=stage,
        pending=resto if not ejecutada else 0,
        failed=failed,
        completed=completed,
        no_aplica=resto if ejecutada else 0,
        fuera_alcance=fuera,
        ejecutada=ejecutada,
        unidad=unidad,
    )


def _cobertura_barrida(
    conn: sqlite3.Connection,
    stage: str,
    ejecutada: bool,
    *,
    total: int,
    completed: int,
    fuera_alcance: int = 0,
    unidad: str = "discursos",
) -> StageStatus:
    """Estado de una stage que barre todo el corpus en una sola pasada.

    Estas stages no dejan marca por unidad, así que lo no cubierto se lee
    según hayan corrido o no: si corrieron, es material sin nada que
    resolver; si no, está todo pendiente.
    """
    resto = max(total - completed, 0)
    return StageStatus(
        stage=stage,
        pending=0 if ejecutada else resto,
        completed=completed,
        no_aplica=resto if ejecutada else 0,
        fuera_alcance=fuera_alcance,
        ejecutada=ejecutada,
        unidad=unidad,
    )


# ══════════════════════════════════════════════════════════════════════════════
#  Helpers de lectura
# ══════════════════════════════════════════════════════════════════════════════


def _selector_clause(conn: sqlite3.Connection, stage: str, codigo_expr: str | None) -> str:
    """SQL que conserva únicamente unidades dentro del selector de la stage."""
    if codigo_expr is None or "stage_selector_scope" not in _tablas(conn):
        return "1"
    escaped = stage.replace("'", "''")
    return (
        "NOT EXISTS ("
        "SELECT 1 FROM stage_selector_scope ss "
        f"WHERE ss.stage = '{escaped}' "
        f"AND ss.codigo = {codigo_expr} AND ss.en_alcance = 0"
        ")"
    )


def _selector_fuera(
    conn: sqlite3.Connection,
    stage: str,
    *,
    tabla: str,
    codigo_expr: str,
    where: str = "1",
) -> int:
    """Cuenta unidades excluidas por selector en una tabla dada."""
    selector = _selector_clause(conn, stage, codigo_expr)
    return _uno(
        conn,
        f"SELECT COUNT(*) FROM {tabla} WHERE ({where}) AND NOT ({selector})",
    )


def _stages_ejecutadas(conn: sqlite3.Connection) -> set[str]:
    """Stages con registro de ejecución en `run_metrics`."""
    if "run_metrics" not in _tablas(conn):
        return set()
    return set(_lista(conn, "SELECT DISTINCT stage_name FROM run_metrics"))


def _tablas(conn: sqlite3.Connection) -> set[str]:
    """Nombres de tabla existentes en la DB."""
    return {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}


def _columnas(conn: sqlite3.Connection, tabla: str) -> set[str]:
    """Columnas de una tabla, o conjunto vacío si no existe."""
    if tabla not in _tablas(conn):
        return set()
    return {r[1] for r in conn.execute(f"PRAGMA table_info({tabla})")}


def _tabla_no_vacia(conn: sqlite3.Connection, tabla: str) -> bool:
    """True si la tabla existe y tiene al menos una fila."""
    if tabla not in _tablas(conn):
        return False
    return conn.execute(f"SELECT 1 FROM {tabla} LIMIT 1").fetchone() is not None


def _uno(conn: sqlite3.Connection, sql: str) -> int:
    """Primer valor entero de una consulta agregada."""
    row = conn.execute(sql).fetchone()
    return int(row[0] or 0) if row is not None else 0


def _lista(conn: sqlite3.Connection, sql: str) -> list[str]:
    """Primera columna de una consulta, como lista de strings."""
    return [str(r[0]) for r in conn.execute(sql).fetchall()]
