# Golden set v2 de autor, multigénero

Estado: infraestructura preparada; las anotaciones todavía no están incorporadas.

El tamaño se define según la unidad de análisis de cada género:

- `tuit`: 200 posts;
- `articulo_periodistico`: 80 párrafos;
- `discurso_presidencial`: 200 frases.

Un párrafo periodístico suele contener varias frases y exige más lectura que un post o una frase de
discurso. El corpus de artículos se congela sobre hasta 30 notas para conservar diversidad sin
inflar la muestra manual.

Cada línea JSONL representa una unidad e incluye:

```json
{
  "id_muestra": "u0001",
  "codigo": "...",
  "unit_idx": 0,
  "genero": "tuit",
  "anotadores": ["autor"],
  "fecha": "2026-08-03",
  "pasadas": [1],
  "texto": "...",
  "contexto": "...",
  "emociones": [
    {
      "experienciador": "...",
      "tipo_emocion": "...",
      "fuente": "...",
      "modo_existencia": "realizada",
      "foria": "disforico"
    }
  ],
  "dudas_comentarios": ""
}
```

`emociones: []` declara explícitamente una unidad sin emociones.

## 0. Preparar tres bases de origen ad hoc

El golden v2 no reutiliza runs históricos. Se construyen tres corpus locales nuevos y tres bases
separadas, una por género:

```text
data/golden_v2/source/tuit.jsonl
runs/golden_v2/tuit.sqlite

data/golden_v2/source/articulo_periodistico.csv
runs/golden_v2/articulo_periodistico.sqlite

data/golden_v2/source/discurso_presidencial.csv
runs/golden_v2/discurso_presidencial.sqlite
```

El script `scripts/prepare_golden_v2_corpora.sh` realiza una adquisición local y reproducible por
archivos congelados:

- 240 posts públicos en español obtenidos de Bluesky mediante una búsqueda configurable
  (`Milei` por defecto);
- hasta 30 artículos recientes de Página/12;
- 24 discursos de Casa Rosada.

Después ejecuta `emoparse run --prepare-only` para ingerir y segmentar cada corpus sin ejecutar
stages ni cargar modelos. La validación exige al menos 200 posts, 80 párrafos periodísticos y 200
frases presidenciales. Los artículos y discursos deben provenir de entre 15 y 30 textos; el corpus
de tuits debe incluir al menos 15 autores. Los textos adquiridos y las bases permanecen locales y no
se incorporan al repositorio ni a paquetes de actualización.

```bash
bash scripts/prepare_golden_v2_corpora.sh
```

El resultado se registra en `runs/golden_v2/manifest_preparacion.json`. Recién después de aprobar
esta preparación se ejecuta el pipeline real sobre cada base con `--resume`.

## 1. Crear una planilla ciega por género

Tuits, 200 posts distintos:

```bash
emoparse eval \
  --db runs/golden_v2/tuit.sqlite \
  --make-sample \
  --n 200 \
  --seed 42 \
  --min-textos 200 \
  --max-por-texto 1 \
  --out evals/golden/v2/tuit_pasada1.csv
```

Artículos, 80 párrafos distribuidos entre al menos 20 notas:

```bash
emoparse eval \
  --db runs/golden_v2/articulo_periodistico.sqlite \
  --make-sample \
  --n 80 \
  --seed 42 \
  --min-textos 20 \
  --max-por-texto 4 \
  --out evals/golden/v2/articulo_periodistico_pasada1.csv
```

Discursos, 200 frases distribuidas entre al menos 15 discursos:

```bash
emoparse eval \
  --db runs/golden_v2/discurso_presidencial.sqlite \
  --make-sample \
  --n 200 \
  --seed 42 \
  --min-textos 15 \
  --max-por-texto 14 \
  --out evals/golden/v2/discurso_presidencial_pasada1.csv
```

La planilla no contiene salidas del modelo. La estratificación utiliza internamente unidades con y
sin detecciones para asegurar cobertura, pero no revela el estrato.

## 2. Congelar la primera pasada

```bash
emoparse eval \
  --freeze-sample evals/golden/v2/<genero>_pasada1.csv \
  --out evals/golden/v2/<genero>.jsonl
```

El comando toma `anotador`, `pasada` y `fecha_anotacion` de cada fila. También valida que todas las
emociones tengan tipo, experienciador, fuente, modo y foria, y que las unidades neutras no contengan
slots completados. Las opciones `--anotador`, `--pasada` y `--fecha` permiten sobrescribir esa
metadata para toda la planilla cuando sea necesario.

## 3. Preparar la reanotación

Entre dos y cuatro semanas después:

```bash
emoparse eval \
  --make-retest evals/golden/v2/<genero>_pasada1.csv \
  --n 30 \
  --seed 20260803 \
  --out evals/golden/v2/<genero>_pasada2.csv
```

El comando conserva los identificadores y textos, elimina las respuestas y cambia `pasada` a `2`.

## 4. Medir la confiabilidad intraanotador

Concatenar ambas pasadas solo para las 30 unidades compartidas, conservando `anotador`, `pasada` e
`id_muestra`, y ejecutar:

```bash
emoparse eval \
  --agreement evals/golden/v2/<genero>_acuerdo.csv \
  --out evals/golden/v2/<genero>_acuerdo.md
```

El reporte calcula alpha para presencia de emoción, tipo, experienciador, fuente, modo de existencia
y foria. Los tres slots se comparan en su orden de saliencia.

## 5. Línea de base multigénero

`--db` puede repetirse; cada run se asocia al género persistido en `runs.config`:

```bash
emoparse eval \
  --golden evals/golden/v2 \
  --por-genero \
  --db runs/golden_v2/tuit.sqlite \
  --db runs/golden_v2/articulo_periodistico.sqlite \
  --db runs/golden_v2/discurso_presidencial.sqlite \
  --persist-report \
  --golden-version v2 \
  --out evals/golden/v2/linea_base.md
```

La línea de base es una referencia comparativa. No constituye por sí sola un umbral de validez ni
bloquea cambios.

## 6. Pruebas de modelos

Las pruebas posteriores reutilizan los mismos corpus fuente, IDs, segmentación y contextos
congelados del golden. Para cada modelo o routing se crea una copia independiente de la base de
preparación y un run propio. Nunca se ejecuta inferencia sobre la base que conserva la preparación
del golden ni sobre las planillas o JSONL de anotación manual.

La tab **Comparar modelos** abre esas SQLite independientes y comprueba primero que la firma del
corpus coincida antes de calcular acuerdo o resultados comparados.
