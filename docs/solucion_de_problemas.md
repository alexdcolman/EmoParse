# Solución de problemas

Esta guía reúne errores frecuentes de ejecución. Los nombres de opciones y comandos completos están
en [`docs/comandos.md`](comandos.md). La arquitectura de backends, cache y persistencia está en
[`docs/arquitectura.md`](arquitectura.md).

## El modelo excede la ventana de contexto

`ContextLengthExceededError` puede aparecer en dos situaciones:

- el prompt ya ocupa la mayor parte de `context_length`;
- el modelo no cierra el JSON dentro de `max_tokens` y la generación termina por longitud.

El log muestra, cuando el backend lo informa, los tokens del prompt, la ventana y el presupuesto de
salida. Un prompt demasiado grande requiere revisar templates, heurísticas y bloques de contexto. Si
hay margen de entrada y falta espacio de salida, puede corresponder aumentar `max_tokens`.

Los batches con varias unidades se dividen a la mitad una vez ante este error. Una unidad individual
queda fallida y puede revisarse con `emoparse inspect` y reintentarse después.

## Falta memoria al cargar un modelo

Reducir `n_gpu_layers`, bajar `context_length` o elegir una cuantización más pequeña disminuye el uso
de VRAM. El routing puede asignar modelos distintos a las etapas. El runner libera el modelo anterior
cuando la etapa siguiente usa un alias incompatible.

## Una etapa usa un modelo inesperado

El routing se lee de `pipeline.stages` en `config.yaml`. Un override pasado por CLI rige para esa
ejecución. Para comprobar la configuración:

```bash
emoparse run --help
emoparse status --db runs/mi_run.sqlite
```

Los aliases declarados por stage deben existir en `models`. Una stage listada en el orden del pipeline
puede permanecer deshabilitada.

## Los resultados cambian entre corridas

La semilla mejora la reproducibilidad, pero el resultado también depende del backend, su versión, el
modelo y el hardware. Después de actualizar llama.cpp, `llama-cpp-python`, LM Studio o un archivo
GGUF conviene repetir el control correspondiente.

## El cache no produce hits

Comprobar `cache_enabled` en `config.yaml` y consultar:

```bash
emoparse stats --db runs/mi_run.sqlite
```

Un cambio en prompts, schemas, ontologías, recursos o imágenes modifica la clave. El cache de una
corrida anterior tampoco coincide cuando cambian el alias del modelo o la semilla.

## Algunas unidades quedan sin emociones

Una lista vacía es una salida válida cuando el texto no construye emociones. Un patrón sistemático de
omisiones se revisa sobre una muestra anotada. Conviene comprobar la evidencia textual, el género, las
heurísticas y la capacidad del modelo antes de modificar categorías.

`emotions_pass2` puede releer unidades con contexto previo en los géneros que la admiten. El género
`tuit` trabaja con una unidad por post y rechaza esa stage.

## El backend devuelve campos extra

Los schemas Pydantic rechazan campos no declarados. En un servidor compatible con OpenAI se usa JSON
Schema estricto cuando está disponible. Un backend nuevo debe respetar el schema exacto del agente.

## El tablero no encuentra una corrida

El tablero busca las bases dentro de `paths.runs_dir`, cuyo valor habitual es `./runs`. Abrirlo desde
la raíz del proyecto o definir la carpeta correcta:

```bash
emoparse app
```

También puede usarse la variable `EMOPARSE_RUNS_DIR` para señalar otro directorio.

## Una fuente web devuelve menos textos de los esperados

Las fuentes pueden cambiar su HTML, bloquear solicitudes o entregar resultados fuera del rango de
fechas. `emoparse scrape` registra descartes y errores en el log. Casa Rosada dispone de un fallback
con Selenium cuando está instalado el extra correspondiente:

```bash
pip install -e ".[scraping_selenium]"
```

Los corpus adquiridos se revisan antes de ejecutar modelos. `run --prepare-only` permite validar la
ingesta y la segmentación en una SQLite nueva.

## La base necesita una migración

No ejecutar una aplicación contra una base atrasada. Crear primero una copia de seguridad y usar el
comando de migración indicado por la versión instalada. La herramienta informa el esquema actual, el
requerido y la ruta exacta de la base.
