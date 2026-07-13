# Manual de anotación de emociones — EmoParse

Consigna para anotadores humanos. Cada anotador trabaja **solo, sin ver las
anotaciones de otros ni las salidas del sistema** (anotación independiente
a ciegas). Ante la duda, anotá tu mejor lectura y dejá constancia en
`dudas_comentarios`.

## Unidad de trabajo

Cada fila de la planilla es una unidad textual (una frase de discurso o un
post completo). La columna `contexto` (si está) muestra a qué responde el
post: usala **solo para entender** la unidad; las emociones se anotan
únicamente si están en el `texto` de la fila.

## Qué es una emoción anotable

Un estado afectivo atribuible a un actor concreto (el **experienciador**),
manifiesto o inferible en la unidad. Incluye:
- Explícitas: "tengo miedo", "nos llena de orgullo".
- Inferibles por conducta o situación: "temblaba frente al juez" → miedo.
- Portadas por marcas no verbales en posts: 😡, MAYÚSCULAS sostenidas,
  "jajaja" (sí, la risa cuenta), signos repetidos.

NO anotar: valoraciones puramente axiológicas sin afecto ("es una medida
incorrecta"), estados físicos ("cansado" salvo hartazgo expresivo), ni
emociones que solo aparecen en el contexto.

## Cómo completar la planilla

1. `hay_emocion`: `si` o `no`. Si es `no`, dejá el resto vacío.
2. Hasta tres emociones por unidad (las más salientes). Para cada una:
   - `experienciador`: quién la siente, con el referente más concreto
     posible ("el presidente", "los jubilados", "@cuenta", "autor del post").
     NUNCA "el enunciador" a secas si podés decir quién es.
   - `tipo`: nombre concreto en minúsculas (miedo, alegría, indignación,
     bronca, orgullo, tristeza, esperanza, burla, hartazgo...). Usá el
     nombre que te salga natural: la comparación normaliza sinónimos.
   - `foria`: `euforico` (vivida como positiva por el experienciador),
     `disforico` (negativa), `ambiforico` (ambas a la vez),
     `indeterminado`.
3. `dudas_comentarios`: libre.

## Casos difíciles (criterios)

- **Ironía**: anotá la emoción efectivamente comunicada, no la literal.
  "Genial, otro aumento 🙄" → fastidio/indignación, no alegría.
- **Discurso referido / citas**: si la unidad reproduce palabras de otro,
  la emoción del texto citado pertenece a su autor original; el autor de
  la unidad puede tener OTRA emoción sobre lo citado (burla, indignación).
  Anotá cada una con su experienciador.
- **Emociones atribuidas**: "quieren que tengamos miedo" → el miedo es del
  "nosotros" (atribuido/proyectado), no del que habla; si además se lee
  indignación del hablante, anotala aparte.
- **Plurales deícticos**: "nosotros" o "ustedes" son experienciadores
  válidos tal cual; no los descompongas.
- **Emojis ambiguos**: 😂 puede ser risa compartida (eufórica) o burla
  (disfórica): decidí por el blanco. 😭 puede ser pena o conmoción positiva.

## Tiempo estimado

30–45 segundos por unidad. Si una unidad te lleva más de dos minutos,
anotá tu mejor lectura, marcá la duda y seguí.
