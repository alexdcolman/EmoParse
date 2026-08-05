# Manual de anotación de emociones — EmoParse

Este manual fija la consigna del golden set. La anotación es **independiente y a ciegas**: trabajá sin mirar las salidas de EmoParse ni anotaciones anteriores. Podés consultar este manual, `docs/CONCEPTOS.md`, `knowledge/emociones.json` para los modos de existencia y `knowledge/catalogo_normalizacion_emociones.json` para escribir la etiqueta canónica de la emoción.

## Unidad de trabajo

Cada fila contiene una unidad textual completa:

- una frase o párrafo en discursos y artículos, según la unidad declarada por el género;
- un post completo en el género `tuit`.

La columna `contexto`, cuando tenga contenido, sirve únicamente para desambiguar la unidad. No anotes una emoción que aparezca solo en el contexto y no esté construida por el `texto` de la fila.

No cambies `id_muestra`, `genero`, `codigo`, `unit_idx`, `contexto` ni `texto`.

## Metadata de la pasada

Completá en todas las filas:

- `anotador`: `autor` para el golden v2;
- `pasada`: `1` en la primera anotación y `2` en la reanotación posterior;
- `fecha_anotacion`: fecha efectiva de esa fila en formato `AAAA-MM-DD`.

El comando de congelamiento toma esta metadata de la planilla. Sus opciones
`--anotador`, `--pasada` y `--fecha` solo se usan para sobrescribir un mismo valor
en todas las filas.

## Decisión inicial

Completá `hay_emocion` con `si` o `no`.

Una emoción es un estado afectivo atribuible a un actor concreto, manifiesto o inferible en la unidad. Puede aparecer mediante una denominación explícita, una construcción psicológica, una conducta, una situación narrativa o una marca tecnodiscursiva.

No anotes como emoción:

- una valoración axiológica sin afecto reconstruible;
- un estado físico sin lectura afectiva en la unidad;
- una emoción presente únicamente en el contexto;
- una reacción que dependa solo de conocimiento externo no activado por el texto.

Si `hay_emocion` es `no`, dejá vacíos todos los campos `emocion_*`.

## Emociones de la unidad

Podés anotar hasta tres emociones. Ordenalas por saliencia analítica: la principal en `emocion_1_*`, luego `emocion_2_*` y `emocion_3_*`. No dejes un slot intermedio vacío.

Para cada emoción completá los cinco campos:

### Experienciador

Quién experimenta la emoción. Usá el referente más concreto que permita la unidad: un nombre, colectivo, institución, pronombre deíctico pertinente o handle. Evitá `el hablante` o `el enunciador` cuando la autoría permita identificarlo mejor.

### Tipo

Escribí la clave canónica en minúsculas de `knowledge/catalogo_normalizacion_emociones.json`. Los aliases del catálogo sirven para decidir qué clave corresponde, pero en la planilla debe quedar el nombre canónico. La herramienta de evaluación no canonicaliza la anotación humana.

### Fuente

Quién o qué desencadena la emoción en el experienciador: actor, evento, objeto, proceso o circunstancia. No es la marca lingüística ni el mediador. Usá `no identificado` cuando la unidad construya la emoción pero no permita determinar su fuente sin inventarla.

### Modo de existencia

Usá uno de estos valores:

- `realizada`: la emoción se expresa o representa efectivamente;
- `potencial`: se plantea como efecto futuro o pretendido sobre alguien;
- `actual`: está activada por el discurso, pero todavía no plenamente realizada;
- `virtual`: aparece como posibilidad, competencia o escenario imaginado.

### Foria

Usá uno de estos valores desde la perspectiva del experienciador:

- `euforico`;
- `disforico`;
- `aforico`;
- `ambiforico`;
- `indeterminado`.

Consultá `knowledge/foria.json` para distinguir los cuatro valores caracterizados;
`indeterminado` se reserva para los casos en que la unidad no aporta información
suficiente para decidir la foria.

## Casos difíciles

- **Ironía**: anotá la emoción efectivamente comunicada, no la lectura literal aislada.
- **Discurso referido o cita**: la emoción del fragmento citado pertenece al actor citado. El autor de la unidad puede construir además otra emoción frente a esas palabras.
- **Emoción atribuida**: en «quieren que tengamos miedo», el miedo corresponde al colectivo designado por `nosotros`, aunque sea proyectado por otro actor.
- **Fuente y experienciador coordinados**: mantené una sola emoción cuando se trata del mismo simulacro con varios desencadenantes; separá emociones cuando cambie el experienciador.
- **Plurales deícticos**: `nosotros` o `ustedes` son válidos si el texto no permite una resolución más concreta.
- **Emojis y otras marcas tecnodiscursivas**: interpretalos en relación con el blanco, el contexto del post y el resto de las marcas de la unidad.
- **Más de tres emociones**: conservá las tres más salientes y explicá la reducción en `dudas_comentarios`.

## Dudas

Usá `dudas_comentarios` para registrar ambigüedad, alternativas plausibles o decisiones difíciles. No dejes una fila sin resolver por esa duda: anotá tu mejor lectura y explicala brevemente.

## Segunda pasada

Entre dos y cuatro semanas después se genera una planilla nueva de 30 unidades. No mires la primera anotación. Usá exactamente esta misma consigna y completá `pasada=2`. Las dos pasadas se comparan como dos codificadores distintos para estimar confiabilidad intraanotador.
