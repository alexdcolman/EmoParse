# emoparse.acquisition

Adquisición de corpus con arquitectura source-adapter. Hay dos familias independientes:

- **Discursos y documentos largos** (`SourceAdapter` → `DiscursoRecord` → CSV). Cada registro
  corresponde a un documento y se adquiere con `emoparse scrape`.
- **Posts** (`PostSourceAdapter` → `PostRecord` → JSONL). Conservan estructura conversacional,
  circulación y metadata de plataforma y se adquieren con `emoparse acquire`.

Los adapters normalizan los campos que EmoParse consume y, cuando la fuente lo permite, conservan
una capa `raw` para auditoría y reprocesamiento. La persistencia es incremental e idempotente por URL
en discursos y por id en posts.

## Discursos y documentos largos

`DiscursoRecord` contiene `codigo`, `url`, `titulo`, `fecha`, `contenido`, `fuente`, metadata
normalizada adicional en `extras` y un `raw` estructurado opcional. `raw` no participa de la igualdad
del registro y puede contener diccionarios y listas; `CsvAppender` lo serializa como JSON estable en
la celda correspondiente.

Fuentes registradas:

| id | Qué adquiere | Salida |
|---|---|---|
| `casarosada` | discursos publicados por Casa Rosada | CSV |
| `pagina12` | artículos públicos de Página/12 | CSV |

`emoparse scrape --max N` cuenta registros efectivamente extraídos, aceptados y escritos. Una URL
fallida, vacía, filtrada o ya presente en el CSV no consume el tope. Cada fuente puede además excluir
del conteo documentos auxiliares que preserve por trazabilidad.

### Página/12 V4

El adapter identifica el documento editorial antes de normalizarlo. `contenido` contiene solamente
las unidades textuales del documento; metadata, paratexto y estructura fuente se preservan fuera del
cuerpo.

Campos normalizados relevantes: `codigo`, `url`, `titulo`, `fecha`, `contenido`, `fuente`, `medio`,
`idioma`, `seccion`, `volanta`, `subtitulo`, `autoria`, `agencia`, `epigrafe`, `scrape_mode`,
`tipo_documento`, `subtipo_articulo` y `subtipo_fuente`.

`raw` usa el snapshot `emoparse.pagina12.raw.v2` y conserva, entre otros elementos:

- URL solicitada y canónica;
- procedencia y diagnóstico del descubrimiento;
- story ANS y JSON-LD identificados;
- metadata del `<head>` y paratexto DOM;
- procedencia de cada campo normalizado;
- clasificación de elementos incluidos y excluidos del cuerpo;
- subtipo Arc exacto;
- estructura completa del live blog cuando corresponde.

El descubrimiento usa feeds RSS de secciones y, cuando no se selecciona una sección de forma
explícita, puede completar con el sitemap oficial. `--section` puede repetirse o recibir valores
separados por coma. Entre las secciones disponibles están `el-pais`, `economia`, `sociedad`,
`deportes`, `el-mundo`, `cultura`, `universidad`, `ciencia`, `psicologia`, `ajedrez`, `la-ventana`,
`dialogos`, `hoy`, `plastica` y `cartas-de-lectores`. Los alias `espectaculos` y
`cultura-y-espectaculos` resuelven a `cultura`: Página/12 presenta esa zona como Cultura, mientras el
feed activo está rotulado como Espectáculos. La procedencia real del feed queda preservada en `raw`.

Los subtipos públicos son:

- `static`: artículos convencionales. Incluye subtipos Arc estáticos como `web` y `opinion`;
- `lbp_article`: live blogs de Arc XP.

`--subtype` puede repetirse o recibir valores separados por coma. Si se omite, se aceptan ambos
subtipos. Si se especifica, sólo se persisten artículos de los subtipos solicitados y los demás no
consumen `--max`.

En un `lbp_article`, el cuerpo se normaliza en este orden:

1. introducción textual del artículo padre;
2. titular de cada actualización;
3. texto legítimo de cada actualización;
4. orden editorial de `LBPList`.

Las entradas de `LBPList` se aceptan como actualizaciones cuando su subtipo fuente es `lbp_update`.
IDs, fechas, titulares, autores, fronteras entre updates y la estructura ANS original permanecen en
`raw`. Bylines aisladas, `raw_html`, embeds, media, contactos y recirculación no se incorporan
automáticamente a `contenido`.

Ejemplos:

```bash
emoparse scrape \
  --source pagina12 \
  --output data/pagina12.csv \
  --section economia \
  --section cultura \
  --subtype static \
  --max 20

emoparse scrape \
  --source pagina12 \
  --output data/pagina12_mixto.csv \
  --section el-pais,economia,sociedad \
  --subtype static,lbp_article \
  --max 20
```

## Fuentes de posts

| id | Qué es | Credenciales |
|---|---|---|
| `bluesky` | API de Bluesky (AT Protocol) | `BLUESKY_HANDLE` + `BLUESKY_APP_PASSWORD` (App Password; nunca la contraseña principal) |
| `mastodon` | API pública de una instancia de Mastodon | sin credenciales para hashtags, hilos y feeds públicos; `MASTODON_ACCESS_TOKEN` para búsquedas que la instancia restrinja. Instancia vía `MASTODON_INSTANCE` (default `mastodon.social`) |
| `x_api` | API oficial de X, v2 | `X_BEARER_TOKEN` |
| `jsonl` | importa dumps JSONL normalizados o en formatos reconocidos | — |
| `csv` | importa datasets tabulares mediante un mapping explícito | — |

`emoparse acquire` trabaja en uno de tres modos mutuamente excluyentes:

- `--query`: búsqueda por texto, hashtag u operadores admitidos por la fuente;
- `--user`: posts de una cuenta;
- `--thread`: conversación completa a partir de un post raíz.

Con `--query`, `--min-conv-posts N` expande cada conversación candidata y conserva sólo las que
tienen al menos N posts; `--max-convs M` limita la cantidad de conversaciones que pasaron ese
filtro. `--max` se aplica sobre posts efectivamente escritos, después del filtrado por fecha y del
dedupe por id.

Opciones adicionales:

- `--with-media`: descarga imágenes adjuntas a `<out>_media/` y agrega `path_local` a la entrada de
  media correspondiente;
- `--with-author-profile`: completa `autor_bio`, `autor_seguidores`, `autor_siguiendo` y
  `autor_verificado` mediante una llamada extra por autor cuando la fuente lo soporta. Bluesky y
  Mastodon declaran actualmente esa capacidad;
- `--pseudonymize`: reemplaza handles antes de escribir y conserva la sal en `<out>.salt`.

Ejemplos:

```bash
emoparse acquire --source bluesky --query "#tarifazo" --lang es \
  --from 2026-05-01 --max 500 --out data/tarifazo.jsonl

emoparse acquire --source bluesky --thread "at://did:plc:.../app.bsky.feed.post/xyz" \
  --out data/hilo.jsonl

emoparse acquire --source mastodon --user usuario@instancia.example \
  --max 200 --with-author-profile --out data/cuenta.jsonl

emoparse acquire --source bluesky --query "Milei" \
  --min-conv-posts 3 --max-convs 20 --out data/conversaciones.jsonl

emoparse acquire --source csv --input dataset_ajeno.csv \
  --mapping mapping.json --query "" --out data/corpus.jsonl
```

El JSONL resultante se analiza con:

```bash
emoparse run --genre tuit --input data/corpus.jsonl
```

En Mastodon, los handles de cuentas locales de la instancia se califican como `usuario@dominio`, de
modo que no colisionen entre instancias en un corpus mixto. Las cuentas remotas ya llegan calificadas
por la API.

## Formato JSONL normalizado

Un post por línea. Campos principales:

- obligatorios: `id`, `plataforma`, `autor_handle`, `texto` - vacío sólo en reposts puros;
- opcionales de identificación y conversación: `autor_display`, `fecha`, `lang`, `tipo`,
  `conversacion_id`, `en_respuesta_a`, `cita_a`, `reposteo_a`, `url`;
- opcionales de perfil: `autor_bio`, `autor_seguidores`, `autor_siguiendo`, `autor_verificado`;
- circulación y media: `metricas`, `media`;
- `raw`: objeto crudo de la fuente cuando el adapter lo conserva.

`tipo` usa `original`, `reply`, `quote` o `repost`. Las referencias conversacionales pueden apuntar
a posts que no formen parte del corpus adquirido.

## Seudonimización (`--pseudonymize`)

Reemplaza cada handle por un alias estable `u_<hash>` derivado de una sal local guardada en
`<out>.salt` con permisos restrictivos. Un mismo autor conserva el mismo alias, por lo que hilos,
menciones y redes siguen siendo relacionables. La seudonimización borra `autor_display`, bio, URL y
`raw`, y reescribe las `@menciones` que correspondan a handles ya vistos durante la sesión.

La sal permite rederivar los alias y no debe publicarse con el corpus. La seudonimización tampoco
elimina nombres propios presentes en el texto libre, imágenes ni datos que el propio post reproduzca.

## Términos de uso y ética

- Respetar los términos y límites de acceso de cada plataforma o sitio. No eludir muros de pago ni
  restricciones técnicas de acceso.
- Adquirir sólo contenido público y el volumen necesario para la investigación.
- Mantener los corpus crudos de medios y redes en almacenamiento local salvo que exista una base
  jurídica y ética clara para redistribuirlos.
- En corpus de posts, considerar que handles, perfiles y texto pueden constituir datos personales.
  Para publicación, preferir ids, corpus seudonimizados o extractos estrictamente necesarios.
- Evitar corpus centrados en cuentas de personas no públicas sin evaluación ética previa.

## Contexto externo del golden v2

`scripts/build_golden_v2_tuit_context.py` es un piloto acotado de 7.1. Parte del JSONL de tuits
congelado y adquiere las referencias salientes de Bluesky mediante `getPosts`, en lotes de hasta 25
URIs. Sigue la cadena de padres hasta cinco niveles y conserva por separado raíz, padre directo,
antecedentes, cita y repost.

Los archivos se escriben bajo `data/golden_v2/context/` y no se versionan. El corpus origen no se
modifica. Las respuestas posteriores al post analizado quedan fuera del alcance porque no forman
parte del contexto disponible al momento de publicación.
