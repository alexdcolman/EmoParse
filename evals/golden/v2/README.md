# Golden set v2 de autor, multigénero

Estado: infraestructura preparada; las anotaciones todavía no están incorporadas. El componente
`articulo_periodistico` fue reconstruido y adoptado el 2026-08-19 con Página/12 V4.

El tamaño se define según la unidad de análisis de cada género:

- `tuit`: 200 posts;
- `articulo_periodistico`: exactamente 80 párrafos;
- `discurso_presidencial`: 200 frases.

El género periodístico mantiene `parrafo` como unidad. Para reconstruirlo se adquieren tantos
artículos actuales como hagan falta para obtener exactamente 80 unidades finales; no se fija una
cantidad histórica de notas ni se preservan URLs anteriores como baseline.

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

La preparación vigente conserva dos componentes ya construidos: el corpus de posts y el corpus de
discursos presidenciales. El tramo periodístico del script
`scripts/prepare_golden_v2_corpora.sh` documenta la preparación anterior y **no gobierna la
reconstrucción post Página/12 V4**. No ejecutar ese tramo para fijar otra vez una cantidad histórica
de artículos.

El componente `articulo_periodistico` vigente se reconstruyó desde cero con Página/12 V4: 12
artículos `static` nuevos, dos por cada una de las seis secciones generales, produjeron 142 párrafos
preparados sin LLM. La muestra adoptada contiene exactamente 80 unidades `parrafo`, con seed
`20260819`, y su contexto intradocumental fue regenerado sobre esas mismas 80 unidades. No se usó el
corpus histórico para comparar, filtrar ni seleccionar la muestra. `lbp_article` queda reservado para
un pipeline específico posterior.

Los textos adquiridos y las bases permanecen locales y no se incorporan al repositorio ni a paquetes
de actualización. Una vez aprobada la preparación de cada componente, el pipeline real se ejecuta
sobre una copia independiente de la base con `--resume`; nunca sobre la base de preparación del
golden.

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

Artículos, exactamente 80 párrafos. La muestra vigente se construyó sin `--min-textos` ni
`--max-por-texto`, sobre la base periodística V4 adoptada:

```bash
emoparse eval \
  --db runs/golden_v2/articulo_periodistico.sqlite \
  --make-sample \
  --n 80 \
  --seed 20260819 \
  --out evals/golden/v2/articulo_periodistico_pasada1.csv
```

No reutilizar los valores históricos `--min-textos 20` / `--max-por-texto 4`.

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
