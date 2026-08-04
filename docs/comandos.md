# Referencia de comandos

Generado desde el parser del CLI con `scripts/gen_cli_reference.py`.
No editar a mano: los cambios se hacen en el módulo del subcomando.

## Opciones globales

Válidas para cualquier subcomando, escritas antes de él.

| Opción | Valor | Default | Qué hace |
|---|---|---|---|
| `-v, --verbose` |  |  | Logging en DEBUG (más detalle). |
| `-q, --quiet` |  |  | Logging en WARNING (menos ruido). |
| `--log-dir` | DIR |  | Directorio donde escribir el log de la corrida. Default: la variable EMOPARSE_LOG_DIR, o `logs/`. |
| `--no-log-file` |  |  | No escribir el log a archivo; solo consola. |

## `emoparse run`

Carga la config, ingesta los discursos del input, y ejecuta todas las stages habilitadas. Si la DB ya existe (mismo run-id), reanuda desde donde quedó.

| Opción | Valor | Default | Qué hace |
|---|---|---|---|
| `--config, -c` | CONFIG | requerido | Path al YAML de config. |
| `--input, -i` | INPUT | requerido | Path al CSV/JSON de discursos. |
| `--run-id` | RUN_ID | requerido | Identificador único del run. |
| `--db` | DB |  | Path al .sqlite del run. Default: <runs_dir>/<run_id>.sqlite. |
| `--stages` | STAGES |  | Lista comma-separated de stages a correr. Válidas: technoparse,emoji_affect,hashtag_semiotics,tecno_usage,vision_describe,summarizer,metadata,enunciation,actors,emotions,emotions_pass2,explode_emotions,deixis,modalidad,normalize_emotions,characterizer,reframing,actants,judge,semas. Si se omite, se usan las stages por default; el género puede sumar etapas propias. Un --stages explícito se respeta tal como fue escrito y debe incluir las dependencias duras. |
| `--genre` | GENRE |  | ID del género de discurso a aplicar. Default: 'discurso_presidencial'. Los géneros disponibles dependen de los entry-points 'emoparse.genres' instalados. El género determina los roles enunciativos válidos, la unidad de chunking (frase/parrafo/documento), y opcionalmente overrides de modelos y batch_sizes. |
| `--select` | ARCHIVO.YAML |  | Archivo YAML que acota qué unidades se analizan. Admite campos del input y payloads de stages previas con notación punto, por ejemplo metadata.tipo_discurso o enunciation.enunciador. Los filtros de payload empiezan a regir después de que su stage productora queda completa. Ver data/ejemplos/seleccion.yaml y seleccion_payload_v070.yaml. |
| `--enunciador` |  |  | Acota la detección de emociones (ambos pases) a las del enunciador. Combinable con --enunciatarios y --actores (se unen). Si no se pasa ninguna de las tres, se analizan todos los experienciadores. |
| `--enunciatarios` |  |  | Acota la detección de emociones (ambos pases) a las de los enunciatarios. |
| `--actores` |  |  | Acota la detección de emociones (ambos pases) a las de otros actores (distintos del enunciador y los enunciatarios). |
| `--embed` |  |  | Inyecta como contexto la información adjunta de cada post (título/descripción/sitio de links del campo embed, alt de imágenes) en emotions, emotions_pass2, enunciation y metadata. Las descripciones de vision_describe ya se inyectan solas si esa stage corrió antes. |
| `--overwrite-db` |  |  | Si la DB del run ya existe, la elimina y empieza de cero sin preguntar. Sin esta flag (ni --resume), una DB existente dispara una pregunta interactiva (o un error si no hay TTY). |
| `--resume` |  |  | Si la DB del run ya existe, reanuda sin preguntar (el comportamiento clásico de re-correr el mismo run-id). |

## `emoparse status`

Muestra el progreso del pipeline en una DB.

| Opción | Valor | Default | Qué hace |
|---|---|---|---|
| `--db` | DB | requerido | Path al .sqlite. |

## `emoparse retry`

Modos: 1) --stage <n>: limpia todos los errors de esa stage. En el próximo `emoparse run` se reintentan. 2) --policy <file>: aplica un YAML de policies (target=failed/completed/all, filters declarativos sobre el payload JSON, override_model opcional). Si además se pasan --config + --input + --run-id, ejecuta el pipeline con el config overrideado por las policies.

| Opción | Valor | Default | Qué hace |
|---|---|---|---|
| `--db` | DB | requerido | Path al .sqlite. |
| `--stage` | STAGE |  | Modo legacy: stage cuyos errors limpiar. Una de: summarizer, metadata, enunciation, actores, emociones, characterizer, actants. |
| `--policy` | POLICY |  | Modo policy: path al YAML de retry policies declarativas. Incompatible con --stage. |
| `--config` | CONFIG |  | (opcional, solo con --policy) Path al config.yaml. Si se pasa junto con --input y --run-id, después de aplicar las policies se ejecuta el pipeline con el config overrideado. |
| `--input` | INPUT |  | (opcional, solo con --policy) Path al CSV/JSON de discursos. |
| `--run-id` | RUN_ID |  | (opcional, solo con --policy) Identificador del run. |

## `emoparse inspect`

Imprime los datos asociados a un discurso en la DB.

| Opción | Valor | Default | Qué hace |
|---|---|---|---|
| `--db` | DB | requerido | Path al .sqlite. |
| `--codigo` | CODIGO | requerido | Código del discurso a inspeccionar. |

## `emoparse stats`

Muestra estadísticas del cache LLM.

| Opción | Valor | Default | Qué hace |
|---|---|---|---|
| `--db` | DB | requerido | Path al .sqlite. |

## `emoparse metrics`

Imprime la última métrica registrada de cada stage del run. Las métricas se persisten al final de cada stage durante `emoparse run`. Si una stage corrió varias veces, se muestra la más reciente.

| Opción | Valor | Default | Qué hace |
|---|---|---|---|
| `--db` | DB | requerido | Path al .sqlite del run. |

## `emoparse judge`

Read-only: imprime el resumen de juicios persistidos en la tabla `judgments`. La ejecución del judge se hace incluyéndolo en `--stages` durante `emoparse run` (es opt-in).

| Opción | Valor | Default | Qué hace |
|---|---|---|---|
| `--db` | DB | requerido | Path al .sqlite del run. |
| `--codigo` | CODIGO |  | Mostrar solo este discurso. Default: todos. |
| `--coherentes` |  |  | Listar también las emociones juzgadas como coherentes. |

## `emoparse modalidad`

Clasifica, con el pre-pass NLP (spaCy) y sin LLM, la modalidad referencial (designacion / referencia_gramatical / identificacion_inferencial) y la naturaleza del referente de cada vínculo marca→referente de una DB existente. Idempotente: solo clasifica lo que aún no tiene modalidad y no pisa lo editado a mano. La variante con LLM (para los casos ambiguos) se corre vía `emoparse run --stages ...,modalidad`.

| Opción | Valor | Default | Qué hace |
|---|---|---|---|
| `--db` | DB | requerido | Path al .sqlite del run. |
| `--nlp-model` | NLP_MODEL |  | Modelo spaCy a usar (ES). Default: es_core_news_md con fallback a sm/lg. Instalá el modelo con `python -m spacy download <modelo>`. |

## `emoparse semas`

Read-only por default (no ejecuta nada sin flags). Con --reset, borra todos los semas persistidos en `canonico_semas` (propuestos y editados a mano), sin distinguir origen. Para reasignarlos con el vocabulario vigente, correr después `emoparse run --stages ...,semas` sobre el mismo run.

| Opción | Valor | Default | Qué hace |
|---|---|---|---|
| `--db` | DB | requerido | Path al .sqlite del run. |
| `--reset` |  |  | Borra todos los semas existentes (propuestos y humanos). No hay vuelta atrás. |

## `emoparse export`

Genera cuatro CSVs en el directorio de salida: discursos.csv, metadata_genero.csv, frases.csv y emociones.csv. La metadata propia del género se exporta en formato largo, con etiquetas y presencia por campo. Los payloads de stages a nivel discurso se flatten a columnas; los de frases se preservan como JSON strings.

| Opción | Valor | Default | Qué hace |
|---|---|---|---|
| `--db` | DB | requerido | Path al .sqlite del run. |
| `--output-dir` | OUTPUT_DIR | requerido | Directorio donde escribir los CSVs. Se crea si no existe. |

## `emoparse validate`

Lee las emociones ya caracterizadas de la DB y aplica los domain validators. Las issues encontradas se persisten en 'validation_issues' y se muestran en consola. Siempre informativo (warnings), no bloquea.

| Opción | Valor | Default | Qué hace |
|---|---|---|---|
| `--db` | DB | requerido | Path al .sqlite. |
| `--codigo` | CODIGO |  | Validar solo este discurso (por código). Default: todos. |
| `--verbose-issues` |  |  | Mostrar detalle de cada issue aunque sean muchas. |
| `--knowledge-dir` | KNOWLEDGE_DIR |  | Directorio de knowledge files. Permite cargar restricciones de caracterización para activar V11_DesviacionOntologica. |
| `--constraints-file` | CONSTRAINTS_FILE | restricciones_caracterizacion_emociones.json | Nombre del archivo de restricciones de caracterización dentro de --knowledge-dir. Default: restricciones_caracterizacion_emociones.json. |

## `emoparse scrape`

Scrapea discursos de una fuente registrada. Modo append incremental: se puede interrumpir y reanudar (dedupe por URL).

| Opción | Valor | Default | Qué hace |
|---|---|---|---|
| `--source` | casarosada \| pagina12 | requerido | Fuente registrada a scrapear. |
| `--output` | OUTPUT | requerido | CSV de salida. Se crea si no existe; append si ya existe. |
| `--max` | MAX |  | Máximo de discursos a extraer en esta corrida. None = sin tope. |
| `--from` | YYYY-MM-DD |  | Solo discursos con fecha >= esta. Best-effort si la fuente no expone fechas en el listado. |
| `--to` | YYYY-MM-DD |  | Solo discursos con fecha <= esta. |
| `--max-after-filter` |  |  | Si se usa junto con --from/--to, --max cuenta discursos ya filtrados por fecha (no el listado crudo del adapter). Por defecto --max se pasa tal cual al adapter, que puede cortar el listado antes de que se aplique el filtro de fechas, dando menos resultados de los esperados. |
| `--mode` | auto \| http \| selenium | auto | Cómo descargar páginas. auto = HTTP con fallback Selenium. |
| `--timeout` | TIMEOUT | 20.0 | Timeout HTTP por request (segundos). |

## `emoparse acquire`

Adquiere posts (tuits y afines) de una fuente registrada. Modo append incremental: se puede interrumpir y reanudar (dedupe por id). El JSONL resultante se analiza con `emoparse run --genre tuit --input <archivo>.jsonl`.

| Opción | Valor | Default | Qué hace |
|---|---|---|---|
| `--source` | bluesky \| csv \| jsonl \| mastodon \| x_api | requerido | Fuente de posts (ej. bluesky, jsonl, csv). |
| `--out` | OUT | requerido | JSONL de salida. Se crea si no existe; append si ya existe. |
| `--query` | QUERY |  | Búsqueda (texto libre, hashtag, operadores de la fuente). |
| `--user` | USER |  | Handle de una cuenta cuyos posts adquirir. |
| `--thread` | THREAD |  | Id del post raíz de una conversación a adquirir completa. |
| `--max` | MAX |  | Máximo de posts a extraer en esta corrida. None = sin tope. |
| `--min-conv-posts` | N |  | Solo con --query: adquiere únicamente conversaciones con al menos N posts. Por cada resultado de búsqueda se expande su hilo completo (una llamada por conversación candidata, deduplicadas); las conversaciones más cortas se descartan. Agnóstico de la fuente: usa el fetch_thread del adapter. |
| `--max-convs` | M |  | Con --min-conv-posts: corta tras adquirir M conversaciones que pasaron el filtro (economía de adquisición). |
| `--from` | YYYY-MM-DD |  | Solo posts con fecha >= esta. Best-effort si la fuente no filtra por fecha. |
| `--to` | YYYY-MM-DD |  | Solo posts con fecha <= esta. |
| `--lang` | LANG |  | Filtro de idioma (código ISO, ej. 'es') si la fuente lo soporta. |
| `--input` | PATH |  | Archivo de entrada para fuentes de importación (jsonl, csv). |
| `--mapping` | MAPPING |  | JSON {campo_normalizado: columna} para la fuente csv. |
| `--with-media` |  |  | Descarga las imágenes adjuntas a <out>_media/ y registra path_local en cada post (solo imágenes, con tope de tamaño). |
| `--with-author-profile` |  |  | Completa autor_bio/autor_seguidores/autor_siguiendo/autor_verificado con una llamada extra por autor (cache en memoria). Solo si la fuente lo soporta; se ignora con un warning si no. |
| `--pseudonymize` |  |  | Seudonimiza handles al escribir (sal persistida en <out>.salt). Ver emoparse/acquisition/README.md. |
| `--timeout` | TIMEOUT | 20.0 | Timeout HTTP por request (segundos), si la fuente lo usa. |

## `emoparse network`

Construye grafos de interacción (reply, mention, rt, qt, hashtag_co) desde los posts del run, calcula métricas y comunidades, las persiste en la DB y reporta el acoplamiento con el análisis emocional. Requiere el extra [network].

| Opción | Valor | Default | Qué hace |
|---|---|---|---|
| `--db` | DB | requerido | Path a la DB SQLite del run. |
| `--graphs` | LISTA | reply,mention,rt,qt,hashtag_co | Grafos a construir, separados por coma. Válidos: reply, mention, rt, qt, hashtag_co. El grafo 'follow' se adquiere aparte con `emoparse follows` y se mide agregándolo acá. |
| `--cliques` |  |  | Reporta las cliques de vínculos recíprocos de cada grafo de cuentas (todos se vinculan con todos, a diferencia de la comunidad, que solo es una zona densa). |
| `--min-clique` | N | 3 | Tamaño mínimo de clique a reportar (default 3). |
| `--flujo` |  |  | Circulación de la emoción: contagio por tipo de emoción y transición fórica partida en intra e inter comunidad. |
| `--similitud` |  |  | Agrupamiento narrativo: agrupa los simulacros emocionales por parecido entre sus componentes. |
| `--similitud-componentes` | LISTA | experienciador,tipo_emocion,fuente,mediador,verificador_normativo,verificador_observacional,operador_modificacion,foria | Componentes del simulacro que inciden en el parecido, separados por coma. Disponibles: experienciador, tipo_emocion, fuente, semas_experienciador, semas_fuente, mediador, verificador_normativo, verificador_observacional, operador_modificacion, polaridad, foria, intensidad, dominancia, tipo_configuracion. |
| `--similitud-umbral` | X | 0.5 | Parecido mínimo para ligar dos simulacros (default 0.5). |
| `--semantico` |  |  | Agrupa los posts por contenido semántico (requiere el extra [embeddings]). |
| `--modelo-embeddings` | NOMBRE |  | Modelo de sentence-transformers para --semantico. |
| `--seed` | SEED | 42 | Seed para la detección de comunidades (reproducibilidad). |
| `--profile-graph` | reply \| mention \| rt \| qt \| follow |  | Grafo cuyas comunidades se usan para el perfil emocional. Por defecto, el primer grafo de autores con comunidades. |
| `--export-dir` | EXPORT_DIR |  | Directorio para exportar GEXF + CSVs por grafo (Gephi) y el perfil por comunidad. |
| `--top` | TOP | 10 | Cantidad de nodos (y de tipos de emoción por comunidad) a mostrar en los resúmenes. |

## `emoparse follows`

Pide a la fuente a quién sigue cada cuenta del corpus y persiste como grafo 'follow' las aristas internas al corpus. Habilita el análisis de comunidades y cliques por seguimiento en `emoparse network` y en la tab Red.

| Opción | Valor | Default | Qué hace |
|---|---|---|---|
| `--db` | DB | requerido | Path a la DB SQLite del run. |
| `--source` | bluesky \| csv \| jsonl \| mastodon \| x_api | requerido | Fuente desde la que consultar el seguimiento. |
| `--handles` | HANDLES |  | Archivo con un handle por línea. Necesario cuando el corpus está seudonimizado: la DB guarda alias, que no se pueden consultar en la plataforma. |
| `--pseudonymize` |  |  | Escribe las aristas con los alias de --salt, para que el grafo quede en los mismos términos que un corpus seudonimizado. |
| `--salt` | SALT |  | Archivo de sal de la seudonimización (el mismo que usó `acquire --pseudonymize`). |
| `--seed` | SEED | 42 | Seed para la detección de comunidades (reproducibilidad). |
| `--max-follows` | N | 5000 | Tope de seguidos consultados por cuenta (default 5000). |
| `--rehacer` |  |  | Descarta el grafo persistido y vuelve a consultar todas las cuentas. Sin esta flag, se reanuda: solo se consultan las que todavía no tienen aristas. |
| `--timeout` | TIMEOUT | 20.0 | Timeout HTTP por request (segundos), si la fuente lo usa. |

## `emoparse eval`

Evaluación de validez del análisis emocional.

| Opción | Valor | Default | Qué hace |
|---|---|---|---|
| `--db` | DB |  | DB del run a evaluar (para --golden, --make-sample, --control). |
| `--golden` | GOLDEN |  | Golden set (.jsonl o directorio de .jsonl). |
| `--make-sample` |  |  | Exporta planilla de anotación a ciegas (--out). |
| `--n` | N | 300 | Tamaño de la muestra de anotación. |
| `--seed` | SEED | 42 | Seed del muestreo (reproducibilidad). |
| `--agreement` | AGREEMENT |  | CSV con las planillas completadas (columna `anotador` + columnas de anotación). |
| `--control` |  |  | Reporta la tasa de detección del run (corpus de control → tasa esperada ≈ 0). |
| `--out` | OUT |  | Archivo de salida (reporte .md o planilla .csv). |

## `emoparse app`

Inicia el servidor Streamlit y abre el dashboard en el navegador. Equivalente a: streamlit run src/emoparse/app/__main__.py

| Opción | Valor | Default | Qué hace |
|---|---|---|---|
| `--port` | PORT |  | Puerto en el que escucha Streamlit (default: 8501). |
| `--no-browser` |  |  | No abrir el navegador automáticamente al iniciar. |
