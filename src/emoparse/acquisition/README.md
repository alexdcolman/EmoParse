# emoparse.acquisition

Adquisición de corpus con arquitectura source-adapter. Dos familias:

- **Discursos** (`SourceAdapter` → `DiscursoRecord` → CSV): documentos largos,
  uno por URL (p. ej. `casarosada`). Comando: `emoparse scrape`.
- **Posts** (`PostSourceAdapter` → `PostRecord` → JSONL): documentos cortos con
  estructura conversacional y metadatos de circulación. Comando:
  `emoparse acquire`.

## Fuentes de posts

| id | Qué es | Credenciales |
|---|---|---|
| `bluesky` | API de Bluesky (AT Protocol) | `BLUESKY_HANDLE` + `BLUESKY_APP_PASSWORD` (App Password; nunca la contraseña principal) |
| `x_api` | API oficial de X, v2 | `X_BEARER_TOKEN` (requiere tier de lectura pago; `/search/all` solo en tiers superiores) |
| `jsonl` | Importa dumps JSONL (normalizados o formato API v2) | — |
| `csv` | Importa datasets tabulares publicados | — |

Ejemplos:

```bash
emoparse acquire --source bluesky --query "#tarifazo" --lang es \
    --from 2026-05-01 --max 500 --out data/tarifazo.jsonl

emoparse acquire --source bluesky --thread "at://did:plc:.../app.bsky.feed.post/xyz" \
    --out data/hilo.jsonl

emoparse acquire --source csv --input dataset_ajeno.csv \
    --mapping mapping.json --query "" --out data/corpus.jsonl
```

El JSONL resultante se analiza con
`emoparse run --genre tuit --input data/corpus.jsonl`.

## Formato JSONL normalizado

Un post por línea. Campos obligatorios: `id`, `texto` (vacío solo en reposts
puros), `autor_handle`. Opcionales: `plataforma`, `autor_display`, `fecha`
(ISO-8601), `lang`, `tipo` (`original|reply|quote|repost`), `conversacion_id`,
`en_respuesta_a`, `cita_a`, `reposteo_a`, `url`, `metricas` (objeto), `media`
(lista de `{tipo, url, alt}`), `raw` (objeto crudo de la fuente).

## Términos de uso y ética

- **Respetar los términos de cada plataforma.** La API de X prohíbe eludir sus
  límites de acceso; Bluesky y Mastodon exponen APIs públicas pero sus datos
  siguen siendo enunciados de personas. Adquirir solo contenido público y solo
  el volumen necesario para la investigación (minimización).
- **Datos personales.** Un corpus de posts contiene datos personales en el
  sentido de las normas de protección de datos (RGPD, Ley 25.326). Buenas
  prácticas: no redistribuir corpus crudos; publicar solo ids ("dehidratado")
  o corpus seudonimizados; citar posts textualmente en publicaciones solo
  cuando sea necesario y considerando que el texto es re-buscable.
- **Cuentas sensibles.** Evitá construir corpus centrados en cuentas de
  personas no públicas sin evaluación ética previa.

## Seudonimización (`--pseudonymize`)

Reemplaza cada handle por un alias estable `u_<hash>` derivado de una **sal
local** (guardada en `<out>.salt`, permisos 600). Mismo autor → mismo alias:
hilos, menciones y redes se conservan. Cubre el handle del autor, borra
display/bio/url/raw y reescribe las `@menciones` del texto **a handles ya
vistos en la sesión de adquisición**.

Límites: no altera nombres propios en el texto libre, ni fotos, ni datos que
el propio post cite. Para publicar un corpus, la seudonimización es una capa
necesaria pero no suficiente: revisar caso por caso.

La sal permite re-derivar los alias: quien publique el corpus **no** debe
publicar el archivo `.salt`.
