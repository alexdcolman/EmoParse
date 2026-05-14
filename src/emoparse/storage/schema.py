# ══════════════════════════════════════════════════════════════════════════════
#  emoparse.storage.schema
#
#  Definición declarativa del esquema SQL.
# ══════════════════════════════════════════════════════════════════════════════

from __future__ import annotations


# ══════════════════════════════════════════════════════════════════════════════
#  Tabla `runs`: metadata del run.
# ══════════════════════════════════════════════════════════════════════════════

CREATE_RUNS = """
CREATE TABLE IF NOT EXISTS runs (
    run_id              TEXT PRIMARY KEY,
    started_at          TIMESTAMP NOT NULL,
    finished_at         TIMESTAMP,
    status              TEXT NOT NULL DEFAULT 'running',  -- running|completed|failed
    -- Versions inyectadas por el caller. NULL si no aplica.
    knowledge_version   TEXT,
    prompt_version      TEXT,
    ontology_version    TEXT,
    schema_version      TEXT,
    -- Configuración del run, JSON.
    config              TEXT,
    -- Notas opcionales del usuario.
    notes               TEXT
)
""".strip()


# ══════════════════════════════════════════════════════════════════════════════
#  Tabla `discursos`: una fila por discurso.
# ══════════════════════════════════════════════════════════════════════════════

CREATE_DISCURSOS = """
CREATE TABLE IF NOT EXISTS discursos (
    codigo                  TEXT PRIMARY KEY,
    -- Input original como JSON. Contiene 'contenido', 'titulo', 'fecha',
    -- y cualquier campo extra del CSV/JSON de input.
    input                   TEXT NOT NULL,

    -- Outputs por etapa, cada uno como JSON. NULL = etapa no procesada.
    summarizer_payload      TEXT,
    summarizer_version      TEXT,
    summarizer_error        TEXT,

    metadata_payload        TEXT,
    metadata_version        TEXT,
    metadata_error          TEXT,

    enunciation_payload     TEXT,
    enunciation_version     TEXT,
    enunciation_error       TEXT,

    -- Timestamps.
    created_at              TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at              TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
)
""".strip()


# ══════════════════════════════════════════════════════════════════════════════
#  Tabla `frases`: una fila por unidad textual (frase/párrafo).
# ══════════════════════════════════════════════════════════════════════════════

CREATE_FRASES = """
CREATE TABLE IF NOT EXISTS frases (
    codigo                  TEXT NOT NULL,
    unit_idx                INTEGER NOT NULL,
    -- Texto de la frase y posición. Estables, vienen del chunking.
    frase                   TEXT NOT NULL,

    -- Outputs por agente. JSON.
    actores_payload         TEXT,
    actores_version         TEXT,
    actores_error           TEXT,

    emociones_payload       TEXT,
    emociones_version       TEXT,
    emociones_error         TEXT,

    -- Pase 2 de emociones (opcional, opt-in en STAGE_ORDER).
    -- Output con el mismo formato que `emociones_payload` pero producido
    -- con contexto de rolling summary. Cuando NULL, no se corrió.
    -- El consumidor (downstream / visualizaciones) decide si usar pase 1
    -- o pase 2 — ambos coexisten.
    emociones_pass2_payload TEXT,
    emociones_pass2_version TEXT,
    emociones_pass2_error   TEXT,

    created_at              TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at              TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,

    PRIMARY KEY (codigo, unit_idx),
    FOREIGN KEY (codigo) REFERENCES discursos(codigo) ON DELETE CASCADE
)
""".strip()


# ══════════════════════════════════════════════════════════════════════════════
#  Tabla `emociones`: una fila por emoción individual.
# ══════════════════════════════════════════════════════════════════════════════

CREATE_EMOCIONES = """
CREATE TABLE IF NOT EXISTS emociones (
    codigo                  TEXT NOT NULL,
    frase_idx               INTEGER NOT NULL,
    emocion_idx             INTEGER NOT NULL,

    -- Atributos de la emoción al momento de su detección.
    -- Vienen de EmocionSchema y se duplican aquí (no normalizamos)
    -- porque consultar "todas las emociones de tipo miedo" sin un join
    -- es órdenes de magnitud más rápido. Storage es barato.
    experienciador          TEXT NOT NULL,
    tipo_emocion            TEXT NOT NULL,
    modo_existencia         TEXT NOT NULL,
    deteccion_justificacion TEXT,

    -- Output del CharacterizerAgent. JSON con los 4 atributos.
    caracterizacion_payload TEXT,
    caracterizacion_version TEXT,
    caracterizacion_error   TEXT,

    created_at              TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at              TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,

    PRIMARY KEY (codigo, frase_idx, emocion_idx),
    FOREIGN KEY (codigo, frase_idx) REFERENCES frases(codigo, unit_idx)
        ON DELETE CASCADE
)
""".strip()


# ══════════════════════════════════════════════════════════════════════════════
#  Tabla `llm_cache`: cache de respuestas LLM.
# ══════════════════════════════════════════════════════════════════════════════

CREATE_LLM_CACHE = """
CREATE TABLE IF NOT EXISTS llm_cache (
    cache_key           TEXT PRIMARY KEY,
    -- Para debug y lookup: campos del key explícitos.
    model_alias         TEXT NOT NULL,
    schema_qualname     TEXT,                -- NULL = sin schema
    -- Versions activas al momento del SET (auditoría).
    knowledge_version   TEXT,
    prompt_version      TEXT,
    ontology_version    TEXT,
    schema_version      TEXT,
    -- La respuesta cacheada.
    raw                 TEXT NOT NULL,
    -- Metadata útil sin tener que reparsear.
    finish_reason       TEXT,
    prompt_tokens       INTEGER,
    completion_tokens   INTEGER,
    latency_ms          REAL,        -- latencia del backend original (ms), NULL en entradas pre-T13
    -- Para purge_before / TTL.
    created_at          TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    -- Para hit-rate por modelo.
    last_hit_at         TIMESTAMP,
    hit_count           INTEGER NOT NULL DEFAULT 0
)
""".strip()


CREATE_LLM_CACHE_INDEX = """
CREATE INDEX IF NOT EXISTS idx_llm_cache_model
    ON llm_cache(model_alias)
""".strip()


CREATE_VALIDATION_ISSUES = """
CREATE TABLE IF NOT EXISTS validation_issues (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    validator_id        TEXT NOT NULL,
    severidad           TEXT NOT NULL DEFAULT 'warning',
    mensaje             TEXT NOT NULL,
    codigo              TEXT NOT NULL,
    frase_idx           INTEGER,
    emocion_idx         INTEGER,
    contexto            TEXT,
    run_at              TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
)
""".strip()

CREATE_VALIDATION_ISSUES_INDEX = """
CREATE INDEX IF NOT EXISTS idx_validation_issues_codigo
    ON validation_issues(codigo)
""".strip()


# ══════════════════════════════════════════════════════════════════════════════
#  Tabla `run_metrics`: telemetría por stage del run.
# ══════════════════════════════════════════════════════════════════════════════

CREATE_RUN_METRICS = """
CREATE TABLE IF NOT EXISTS run_metrics (
    run_id                  TEXT NOT NULL,
    stage_name              TEXT NOT NULL,
    n_items_ok              INTEGER NOT NULL DEFAULT 0,
    n_items_failed          INTEGER NOT NULL DEFAULT 0,
    total_latency_ms        REAL NOT NULL DEFAULT 0.0,
    p50_latency_ms          REAL,
    p99_latency_ms          REAL,
    total_prompt_tokens     INTEGER NOT NULL DEFAULT 0,
    total_completion_tokens INTEGER NOT NULL DEFAULT 0,
    cache_hits              INTEGER NOT NULL DEFAULT 0,
    cache_misses            INTEGER NOT NULL DEFAULT 0,
    recorded_at             TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (run_id, stage_name, recorded_at)
)
""".strip()


CREATE_RUN_METRICS_INDEX = """
CREATE INDEX IF NOT EXISTS idx_run_metrics_run_id
    ON run_metrics(run_id)
""".strip()


# ══════════════════════════════════════════════════════════════════════════════
#  Tabla `judgments`: capa 3 de validación.
# ══════════════════════════════════════════════════════════════════════════════

CREATE_JUDGMENTS = """
CREATE TABLE IF NOT EXISTS judgments (
    codigo                  TEXT NOT NULL,
    frase_idx               INTEGER NOT NULL,
    emocion_idx             INTEGER NOT NULL,
    -- Veredicto del juez. NULL = no procesado todavía o falló.
    coherente               INTEGER,           -- 0/1 (SQLite no tiene BOOL nativo)
    issues                  TEXT,
    confianza               TEXT,              -- 'alta'|'media'|'baja'
    -- Metadata.
    judge_version           TEXT,
    judge_error             TEXT,
    created_at              TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at              TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (codigo, frase_idx, emocion_idx),
    FOREIGN KEY (codigo, frase_idx, emocion_idx)
        REFERENCES emociones(codigo, frase_idx, emocion_idx)
        ON DELETE CASCADE
)
""".strip()


CREATE_JUDGMENTS_INDEX = """
CREATE INDEX IF NOT EXISTS idx_judgments_codigo
    ON judgments(codigo)
""".strip()


# ══════════════════════════════════════════════════════════════════════════════
#  Lista canónica de DDLs en orden de creación
# ══════════════════════════════════════════════════════════════════════════════

#: Las tablas con FKs deben crearse después de sus referenciadas.
ALL_TABLES_DDL: list[str] = [
    CREATE_RUNS,
    CREATE_DISCURSOS,
    CREATE_FRASES,
    CREATE_EMOCIONES,
    CREATE_LLM_CACHE,
    CREATE_LLM_CACHE_INDEX,
    CREATE_VALIDATION_ISSUES,
    CREATE_VALIDATION_ISSUES_INDEX,
    CREATE_RUN_METRICS,
    CREATE_RUN_METRICS_INDEX,
    CREATE_JUDGMENTS,
    CREATE_JUDGMENTS_INDEX,
]
