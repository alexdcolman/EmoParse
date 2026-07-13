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
    experienciador_marca    TEXT NOT NULL,
    tipo_emocion            TEXT NOT NULL,
    fuente_marca            TEXT NOT NULL,
    fuente_inferencia       TEXT NOT NULL,
    modo_existencia         TEXT NOT NULL,
    -- Configuración del simulacro emocional (TIPO_CONF, 1..8).
    -- Emitido por EmotionsAgent junto con la detección. NULL solo en bases
    -- pre-V0.3.0 que aún no han re-ejecutado emotions con la versión nueva.
    tipo_configuracion      TEXT,

    -- Output de NormalizeEmotionsStage. Canónico según ontología.
    -- NULL = stage no corrida o emoción no cubierta por la ontología.
    tipo_emocion_canonico       TEXT,
    normalize_emotions_version  TEXT,

    -- Experienciador canónico, materializado por el commit de la revisión
    -- (overlay → base). String legible por discurso (p. ej. el nombre del
    -- enunciador). NULL = sin revisión commiteada para esa emoción.
    experienciador_canonico        TEXT,

    -- Fuente canónica por emoción, fijada en la revisión de referentes. NULL =
    -- sin atribución por emoción (la fuente se resuelve por marca). Prima sobre
    -- la resolución por marca en las vistas de referentes/simulacros/búsqueda.
    fuente_canonico                TEXT,

    -- Output del CharacterizerAgent. JSON con los 4 atributos.
    caracterizacion_payload TEXT,
    caracterizacion_version TEXT,
    caracterizacion_error   TEXT,

    -- Output del ActantsAgent (opt-in). JSON con la configuración
    -- actancial completa: mediador, verificadores normativo y
    -- observacional, y operador de modificación. NULL = stage no
    -- corrida sobre esta emoción.
    actantes_payload        TEXT,
    actantes_version        TEXT,
    actantes_error          TEXT,

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
    -- Correcciones propuestas por elemento (JSON: lista de
    -- {campo, valor_sugerido, justificacion}). NULL o '[]' = sin sugerencias.
    sugerencias             TEXT,
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
#  Marcas discursivas → referentes canónicos
#
#  Una `mencion` es una marca discursiva en su lugar (codigo, unit_idx),
#  independiente de su función actancial. `mencion_funcion` registra las
#  funciones de cada marca: una misma marca puede ser a la vez actor y
#  experienciador (una mención, varias funciones). `mencion_canonico` liga la
#  marca (muchos-a-muchos) a uno o más referentes de `referentes_kb` (resuelve
#  el "nosotros" inclusivo: una marca → varios canónicos). `canonico_semas`
#  adjunta semas al referente.
# ══════════════════════════════════════════════════════════════════════════════

CREATE_MENCIONES = """
CREATE TABLE IF NOT EXISTS menciones (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    codigo          TEXT NOT NULL,
    unit_idx        INTEGER NOT NULL,
    -- Marca discursiva tal como aparece ("tomamos", "Javier Milei",
    -- "la barbarie invasora", "ellos").
    marca           TEXT NOT NULL,
    -- Referente inferido por el LLM en origen (auditoría; el vínculo efectivo
    -- vive en mencion_canonico).
    llm_inferencia  TEXT,
    origin          TEXT NOT NULL DEFAULT 'llm',   -- 'llm'|'human'|'technoparse'
    created_at      TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (codigo, unit_idx, marca),
    FOREIGN KEY (codigo) REFERENCES discursos(codigo) ON DELETE CASCADE
)
""".strip()


CREATE_MENCIONES_INDEX = """
CREATE INDEX IF NOT EXISTS idx_menciones_codigo_unit
    ON menciones(codigo, unit_idx)
""".strip()


CREATE_MENCION_FUNCION = """
CREATE TABLE IF NOT EXISTS mencion_funcion (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    mencion_id  INTEGER NOT NULL,
    funcion     TEXT NOT NULL,    -- 'actor'|'experienciador'|'fuente'|'circunstante'
    origin      TEXT NOT NULL DEFAULT 'llm',   -- 'llm'|'human'
    created_at  TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (mencion_id, funcion),
    FOREIGN KEY (mencion_id) REFERENCES menciones(id) ON DELETE CASCADE
)
""".strip()


CREATE_MENCION_FUNCION_MENCION_INDEX = """
CREATE INDEX IF NOT EXISTS idx_mencion_funcion_mencion
    ON mencion_funcion(mencion_id)
""".strip()


CREATE_MENCION_FUNCION_FUNCION_INDEX = """
CREATE INDEX IF NOT EXISTS idx_mencion_funcion_funcion
    ON mencion_funcion(funcion)
""".strip()


CREATE_MENCION_CANONICO = """
CREATE TABLE IF NOT EXISTS mencion_canonico (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    mencion_id      INTEGER NOT NULL,
    -- Referente canónico (slug en referentes_kb). Una mención puede ligarse a
    -- varios canónicos (UNIQUE por par, no por mención).
    canonical_id    TEXT NOT NULL,
    status          TEXT NOT NULL DEFAULT 'proposed',  -- 'proposed'|'accepted'|'rejected'
    -- Procedencia del vínculo: el deíctico entra como sugerencia ('deixis'),
    -- no como resolución automática.
    origin          TEXT NOT NULL DEFAULT 'llm',        -- 'llm'|'deixis'|'deixis_llm'|'auto'|'coref'|'human'|'technoparse'
    -- Categoría esquemática cuando el vínculo proviene de la resolución de
    -- deixis: 'enunciador'|'auditorio'|'colectivo_identificacion'. NULL si no
    -- es un vínculo deíctico. El canonical_id sigue siendo el referente concreto.
    deixis_tipo     TEXT,
    -- Modalidad referencial del vínculo marca→referente (stage `modalidad`):
    --   'designacion'              (SN/nombre propio que nombra/categoriza)
    --   'referencia_gramatical'    (deixis/morfología: pronombres, concordancia)
    --   'identificacion_inferencial' (se identifica por la actitud/valores)
    -- NULL si no fue clasificado.
    modalidad       TEXT,
    -- Naturaleza del referente al que apunta la marca:
    --   'persona'|'colectivo'|'institucion'|'objeto_proceso'|'otro'. NULL si no.
    naturaleza      TEXT,
    -- Procedencia de la clasificación de modalidad/naturaleza: 'nlp'|'llm'|'human'.
    modalidad_origin TEXT,
    created_at      TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    reviewed_at     TIMESTAMP,
    UNIQUE (mencion_id, canonical_id),
    FOREIGN KEY (mencion_id) REFERENCES menciones(id) ON DELETE CASCADE
)
""".strip()


CREATE_MENCION_CANONICO_INDEX = """
CREATE INDEX IF NOT EXISTS idx_mencion_canonico_canonical_status
    ON mencion_canonico(canonical_id, status)
""".strip()


CREATE_MENCION_CANONICO_MENCION_INDEX = """
CREATE INDEX IF NOT EXISTS idx_mencion_canonico_mencion
    ON mencion_canonico(mencion_id)
""".strip()


CREATE_CANONICO_SEMAS = """
CREATE TABLE IF NOT EXISTS canonico_semas (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    -- Referente canónico (slug en referentes_kb). El sema se adjunta al
    -- referente, no a una mención puntual.
    canonical_id    TEXT NOT NULL,
    sema            TEXT NOT NULL,    -- del vocabulario curado (knowledge/semas.json)
    status          TEXT NOT NULL DEFAULT 'proposed',  -- 'proposed'|'accepted'|'rejected'
    origin          TEXT NOT NULL DEFAULT 'llm',        -- 'llm'|'human'
    created_at      TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (canonical_id, sema)
)
""".strip()


CREATE_CANONICO_SEMAS_CANONICAL_INDEX = """
CREATE INDEX IF NOT EXISTS idx_canonico_semas_canonical
    ON canonico_semas(canonical_id)
""".strip()


CREATE_CANONICO_SEMAS_SEMA_INDEX = """
CREATE INDEX IF NOT EXISTS idx_canonico_semas_sema
    ON canonico_semas(sema)
""".strip()


# ══════════════════════════════════════════════════════════════════════════════
#  Corpus de posts (géneros de discurso nativo digital: tuit y afines)
#
#  Un post es un documento corto con estructura conversacional (hilos de
#  respuestas), operaciones de circulación (repost, cita) y métricas. Cada
#  post analizable tiene además su fila espejo en `discursos` (codigo =
#  post_id), que es lo que consume el pipeline; estas tablas conservan la
#  materialidad técnica que `discursos` no modela. Los reposts puros (sin
#  texto propio) viven solo acá: registran circulación, no enunciación propia.
# ══════════════════════════════════════════════════════════════════════════════

CREATE_POSTS = """
CREATE TABLE IF NOT EXISTS posts (
    post_id             TEXT PRIMARY KEY,
    plataforma          TEXT NOT NULL,     -- 'bluesky'|'x'|'mastodon'|...
    autor_handle        TEXT NOT NULL,
    -- Texto propio del post. Vacío en reposts puros.
    texto               TEXT NOT NULL,
    fecha               TEXT,              -- ISO-8601
    lang                TEXT,
    tipo                TEXT NOT NULL DEFAULT 'original',  -- 'original'|'reply'|'quote'|'repost'
    -- Estructura conversacional y de circulación (ids de otros posts,
    -- presentes o no en el corpus).
    conversacion_id     TEXT,
    en_respuesta_a      TEXT,
    cita_a              TEXT,
    reposteo_a          TEXT,
    -- Repost sin texto propio: no se analiza como enunciado del reposteador.
    es_repost_puro      INTEGER NOT NULL DEFAULT 0,
    -- Reply cuyo padre no fue capturado en el corpus (normal en scrapeos).
    huerfano            INTEGER NOT NULL DEFAULT 0,
    -- Profundidad en el árbol conversacional (0 = raíz). NULL = no calculable.
    profundidad         INTEGER,
    url                 TEXT,
    metricas            TEXT,              -- JSON: likes, reposts, replies, ...
    raw                 TEXT,              -- JSON crudo de la fuente (auditoría)
    -- Clasificación de la operación de redocumentación (stage reframing),
    -- solo para posts que citan o repostean con comentario. JSON.
    reframing_payload   TEXT,
    reframing_version   TEXT,
    reframing_error     TEXT,
    created_at          TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at          TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
)
""".strip()


CREATE_POSTS_CONVERSACION_INDEX = """
CREATE INDEX IF NOT EXISTS idx_posts_conversacion
    ON posts(conversacion_id)
""".strip()


CREATE_POSTS_AUTOR_INDEX = """
CREATE INDEX IF NOT EXISTS idx_posts_autor
    ON posts(autor_handle)
""".strip()


CREATE_AUTORES = """
CREATE TABLE IF NOT EXISTS autores (
    plataforma          TEXT NOT NULL,
    handle              TEXT NOT NULL,
    display_name        TEXT,
    bio                 TEXT,
    verificado          INTEGER,
    -- Snapshot al momento de la captura.
    seguidores          INTEGER,
    siguiendo           INTEGER,
    url                 TEXT,
    extras              TEXT,              -- JSON
    created_at          TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at          TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (plataforma, handle)
)
""".strip()


CREATE_HILOS = """
CREATE TABLE IF NOT EXISTS hilos (
    conversacion_id     TEXT PRIMARY KEY,
    -- post_id de la raíz. Puede no estar en `posts` si no fue capturada.
    post_raiz           TEXT NOT NULL,
    n_posts             INTEGER NOT NULL DEFAULT 1,
    profundidad_max     INTEGER NOT NULL DEFAULT 0,
    participantes       TEXT,              -- JSON: lista de handles
    fecha_inicio        TEXT,
    fecha_fin           TEXT,
    created_at          TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at          TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
)
""".strip()


CREATE_MEDIA = """
CREATE TABLE IF NOT EXISTS media (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    post_id             TEXT NOT NULL,
    tipo                TEXT NOT NULL,     -- 'imagen'|'video'|'gif'|'otro'
    url                 TEXT,
    path_local          TEXT,              -- si se descargó (opt-in)
    alt_text            TEXT,
    -- Descripción generada por el análisis multimodal (opt-in). JSON.
    descripcion_payload TEXT,
    descripcion_version TEXT,
    descripcion_error   TEXT,
    ocr_text            TEXT,
    created_at          TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (post_id) REFERENCES posts(post_id) ON DELETE CASCADE
)
""".strip()


CREATE_MEDIA_POST_INDEX = """
CREATE INDEX IF NOT EXISTS idx_media_post
    ON media(post_id)
""".strip()


# ══════════════════════════════════════════════════════════════════════════════
#  Tabla `tecno_entidades`: tecnolingüísticos por unidad.
#
#  Salida de la stage determinista `technoparse`: hashtags, menciones (@),
#  URLs, emojis y tecnografismos (mayúsculas sostenidas, alargamientos,
#  puntuación expresiva, risas), con sus offsets sobre el texto de la unidad.
#  El texto nunca se altera: se anota.
# ══════════════════════════════════════════════════════════════════════════════

CREATE_TECNO_ENTIDADES = """
CREATE TABLE IF NOT EXISTS tecno_entidades (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    codigo          TEXT NOT NULL,
    unit_idx        INTEGER NOT NULL,
    tipo            TEXT NOT NULL,     -- 'hashtag'|'mencion'|'url'|'emoji'|'tecnografismo'
    -- Valor tal como aparece en el texto (con # / @ / repeticiones).
    valor           TEXT NOT NULL,
    -- Valor normalizado: hashtag/handle sin prefijo y en minúsculas, emoji
    -- en shortcode, URL reducida a dominio, tecnografismo colapsado.
    valor_norm      TEXT NOT NULL,
    -- Offsets [inicio, fin) sobre el texto de la unidad.
    inicio          INTEGER NOT NULL,
    fin             INTEGER NOT NULL,
    -- Atributos específicos del tipo, JSON: p. ej. la función sintáctica del
    -- hashtag ('integrada'|'pospuesta'), la posición de la mención
    -- ('vocativo_inicial'|'integrada'), el subtipo de tecnografismo.
    extra           TEXT,
    created_at      TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (codigo, unit_idx, tipo, inicio),
    FOREIGN KEY (codigo) REFERENCES discursos(codigo) ON DELETE CASCADE
)
""".strip()


CREATE_TECNO_ENTIDADES_INDEX = """
CREATE INDEX IF NOT EXISTS idx_tecno_codigo_unit
    ON tecno_entidades(codigo, unit_idx)
""".strip()


CREATE_TECNO_ENTIDADES_TIPO_INDEX = """
CREATE INDEX IF NOT EXISTS idx_tecno_tipo_valor
    ON tecno_entidades(tipo, valor_norm)
""".strip()


# ══════════════════════════════════════════════════════════════════════════════
#  Tabla `hashtags`: caracterización semiótica a nivel corpus.
#
#  Salida de la stage `hashtag_semiotics`: función dominante, acoplamiento
#  actitud-tema y foria del entorno, por hashtag frecuente.
# ══════════════════════════════════════════════════════════════════════════════

CREATE_HASHTAGS = """
CREATE TABLE IF NOT EXISTS hashtags (
    valor_norm          TEXT PRIMARY KEY,
    n_usos              INTEGER NOT NULL DEFAULT 0,
    -- 'topico'|'afiliacion_consigna'|'evaluativo'|'ironico'|'campania'|'mixto'
    funcion             TEXT,
    acoplamiento        TEXT,
    foria_entorno       TEXT,
    justificacion       TEXT,
    analisis_payload    TEXT,              -- JSON completo del agente
    analisis_version    TEXT,
    analisis_error      TEXT,
    created_at          TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at          TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
)
""".strip()


# ══════════════════════════════════════════════════════════════════════════════
#  Tablas de red: aristas de interacción y métricas por nodo.
#
#  Construidas post-hoc por `emoparse network` (sin LLM) desde `posts` y
#  `tecno_entidades`. Grafos: 'reply', 'mention', 'rt', 'qt', 'hashtag_co'.
# ══════════════════════════════════════════════════════════════════════════════

CREATE_ARISTAS = """
CREATE TABLE IF NOT EXISTS aristas (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    grafo           TEXT NOT NULL,
    origen          TEXT NOT NULL,
    destino         TEXT NOT NULL,
    -- Post que materializa la interacción (NULL en grafos agregados).
    post_id         TEXT,
    peso            REAL NOT NULL DEFAULT 1.0,
    fecha           TEXT,
    created_at      TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
)
""".strip()


CREATE_ARISTAS_GRAFO_INDEX = """
CREATE INDEX IF NOT EXISTS idx_aristas_grafo
    ON aristas(grafo, origen, destino)
""".strip()


CREATE_RED_METRICAS = """
CREATE TABLE IF NOT EXISTS red_metricas (
    grafo               TEXT NOT NULL,
    nodo                TEXT NOT NULL,
    grado_in            INTEGER,
    grado_out           INTEGER,
    grado_total         INTEGER,
    pagerank            REAL,
    intermediacion      REAL,
    comunidad           INTEGER,
    updated_at          TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (grafo, nodo)
)
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
    CREATE_MENCIONES,
    CREATE_MENCIONES_INDEX,
    CREATE_MENCION_FUNCION,
    CREATE_MENCION_FUNCION_MENCION_INDEX,
    CREATE_MENCION_FUNCION_FUNCION_INDEX,
    CREATE_MENCION_CANONICO,
    CREATE_MENCION_CANONICO_INDEX,
    CREATE_MENCION_CANONICO_MENCION_INDEX,
    CREATE_CANONICO_SEMAS,
    CREATE_CANONICO_SEMAS_CANONICAL_INDEX,
    CREATE_CANONICO_SEMAS_SEMA_INDEX,
    CREATE_POSTS,
    CREATE_POSTS_CONVERSACION_INDEX,
    CREATE_POSTS_AUTOR_INDEX,
    CREATE_AUTORES,
    CREATE_HILOS,
    CREATE_MEDIA,
    CREATE_MEDIA_POST_INDEX,
    CREATE_TECNO_ENTIDADES,
    CREATE_TECNO_ENTIDADES_INDEX,
    CREATE_TECNO_ENTIDADES_TIPO_INDEX,
    CREATE_HASHTAGS,
    CREATE_ARISTAS,
    CREATE_ARISTAS_GRAFO_INDEX,
    CREATE_RED_METRICAS,
]
