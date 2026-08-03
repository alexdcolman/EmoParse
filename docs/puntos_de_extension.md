# Puntos de extensión de los géneros

EmoParse separa las decisiones teóricas propias de un género de la mecánica común del pipeline. Un
plugin de género declara su unidad de análisis, roles enunciativos, tipos de discurso, metadata de
entrada y contexto; los agentes consumen esas declaraciones sin preguntar por un `genre_id`
concreto.

## Descriptor `Genre`

Cada género se registra mediante una factory `() -> Genre` en el grupo de entry-points
`emoparse.genres`. El descriptor puede declarar:

- `unit` y `context_unit`: unidad textual y fuente de contexto circundante;
- `enunciation_roles`, `enunciatarios_por_tipo` y `roles_descripciones`;
- `tipos_discurso` y sus descripciones;
- stages inválidas, modelos y tamaños de batch propios;
- heurísticas adicionales por stage;
- un modelo Pydantic para la metadata específica del input;
- bloques de contexto derivados de esa metadata.

La definición del género vive en `src/emoparse/genres/`. Las ontologías y heurísticas permanecen en
`knowledge/`.

## Metadata tipada y bloques de contexto

`input_metadata_model` valida los campos propios del corpus en la ingesta. Los valores normalizados
se conservan dentro del JSON de input de cada discurso, sin convertir la tabla `discursos` en una
colección creciente de columnas específicas.

`input_metadata_display` asigna etiquetas legibles y `context_blocks` declara qué campos llegan a
qué stages. Cada bloque fija un presupuesto aproximado de tokens por stage para que agregar metadata
no infle los prompts de manera silenciosa.

```python
from pydantic import BaseModel, ConfigDict

from emoparse.genres import Genre, GenreContextBlock


class ArticuloCientificoMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    disciplina: str | None = None
    tipo_articulo: str | None = None
    seccion_paper: str | None = None


def get_genre() -> Genre:
    return Genre(
        genre_id="articulo_cientifico",
        display_name="Artículo científico",
        unit="parrafo",
        input_metadata_model=ArticuloCientificoMetadata,
        input_metadata_display={
            "disciplina": "Disciplina",
            "tipo_articulo": "Tipo de artículo",
            "seccion_paper": "Sección del paper",
        },
        context_blocks=(
            GenreContextBlock(
                name="contexto_academico",
                title="Contexto académico",
                fields=("disciplina", "tipo_articulo", "seccion_paper"),
                stage_token_budgets={
                    "summarizer": 120,
                    "metadata": 100,
                    "enunciation": 100,
                    "emotions": 80,
                },
            ),
        ),
        enunciation_roles=("lector_especializado",),
    )
```

El provider genérico:

1. revalida la metadata persistida con el modelo del género;
2. omite valores ausentes;
3. renderiza los campos con sus etiquetas;
4. recorta cada bloque según el presupuesto de la stage;
5. compone los bloques en la columna interna `contexto_genero`.

Actualmente `summarizer`, `metadata`, `enunciation` y `emotions` consumen esa columna. Cada prompt
aclara que el bloque sitúa la lectura y no sustituye la evidencia textual: en emociones, por
ejemplo, no autoriza a agregar afectos que la unidad no porta.

La cuenta de tokens es una aproximación conservadora e independiente del tokenizer del backend. El
límite real del modelo y el margen de generación siguen gobernados por la configuración del backend.

## Presentación y exportación de la metadata

Al crear un run, EmoParse conserva en `runs.config` un snapshot mínimo del género activo: su
identificador, nombre legible y la lista ordenada de campos declarados en
`input_metadata_display`. El snapshot no sustituye al plugin ni guarda el schema completo; permite
abrir y exportar un run aunque el plugin que lo produjo ya no esté instalado.

El tablero usa esa declaración de dos maneras:

- la tab **Revisión** muestra un bloque de datos propios del género y omite valores ausentes;
- la tab **Tabla**, en el nivel discursos, presenta esos campos con sus etiquetas legibles sin
  cambiar los nombres estables usados al descargar el CSV.

`emoparse export` mantiene los campos dentro de `discursos.csv` con el prefijo `input__` y agrega
`metadata_genero.csv` en formato largo. Cada fila contiene `codigo`, género, campo, etiqueta, valor
y un indicador `presente`. Los valores ausentes también se exportan, de modo que la cobertura de
una fuente puede medirse sin codificar columnas propias de un sitio o de un género en el exporter.
Las listas y objetos se serializan como JSON válido.

Los runs anteriores que no contienen el snapshot siguen abriéndose normalmente. En ese caso el
tablero conserva las columnas crudas de input y `metadata_genero.csv` se genera sin filas, sin
adivinar el género a partir de nombres de columnas.

## Qué no requiere modificar el núcleo

Un género nuevo no debería exigir ramas como `if genre_id == "..."` para:

- validar y persistir metadata propia;
- presentar esos campos con etiquetas legibles;
- inyectarlos en las cuatro stages que usan contexto global;
- restringir roles y tipos de discurso mediante schemas dinámicos;
- sumar heurísticas o ajustar batch sizes.

Los tests de contrato deben demostrar el mecanismo con un descriptor sintético adicional, sin crear
una implementación especial dentro del pipeline.

## Qué todavía puede requerir código

Hay extensiones que no son simples declaraciones:

- un adapter de adquisición para un sitio o una API nuevos;
- una unidad de fragmentación que no corresponda a frase, párrafo o documento;
- una stage nueva o un contrato de salida diferente;
- tablas persistentes para materialidad que no cabe en el input JSON;
- visualizaciones especializadas que no puedan expresarse como campos etiquetados.

El contexto conversacional, los tecnolingüísticos y la media de posts siguen dependiendo de
repositorios especializados, pero sus providers implementan una interfaz común:
`ContextBlockProvider`. Cada bloque dinámico declara nombre, columna interna, alcance
(`discurso` o `unidad`), stages consumidoras y presupuesto aproximado. La implementación concreta
permanece en `pipeline/post_context.py`; la mecánica de validación y recorte vive en
`pipeline/context_blocks.py`.

`prompt_overrides` se reserva para el caso excepcional en que cambie realmente el contrato o la
organización completa del prompt. Las reglas adicionales que conservan el mismo contrato deben
componerse mediante heurísticas, propiedades declarativas del género y bloques de contexto. El
género `tuit`, por ejemplo, ya usa el template base de `metadata` y `enunciation`: su vocabulario
cerrado, sus heurísticas y sus modos deterministas de enunciador y auditorio se insertan sin
duplicar el system prompt completo.

## Selectores sobre payloads

El archivo pasado a `emoparse run --select` admite tanto campos del input como paths sobre salidas
persistidas. Un campo con prefijo de stage, por ejemplo `metadata.tipo_discurso` o
`enunciation.enunciador.nombre`, se interpreta sobre el JSON producido por esa stage.

El alcance es dinámico: un filtro no afecta a su propia stage ni a las anteriores. Empieza a regir
antes de la primera stage posterior, cuando el productor ya está completo, y se combina en AND con
los demás filtros resolubles. Si el productor está deshabilitado o incompleto, o si ningún discurso
cumple la selección, el pipeline termina con un mensaje explícito.

Los payloads seleccionables se registran en `pipeline.payload_selection`. Agregar una nueva fuente
requiere declarar su tabla o join, la expresión del código de discurso, la columna JSON y el criterio
de completitud. La traducción de operaciones a `json_extract` vive en `pipeline.filter_sql` y se
comparte con las políticas declarativas de reintento.

El alcance calculado se persiste por stage en `stage_selector_scope`. `emoparse status` y la tab
Estado presentan `fuera` como una categoría distinta de `n/a`: lo primero fue excluido por una
decisión de corrida y puede procesarse después; lo segundo no pertenece al universo de la stage.
