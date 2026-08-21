# Heurísticas — análisis actancial de emociones

Estas reglas son la fuente de verdad interpretativa para `actants`. Se aplican a todo género
discursivo. No se afinan contra ejemplos aislados: cualquier cambio semántico se evalúa con golden,
corpus de control y regresiones multigénero.

## Principios generales

- Analizá cada emoción **por separado** a partir del EXPERIENCIADOR y la FUENTE ya fijados. No
  proyectes sobre ella componentes que pertenecen a otra emoción o a otro experienciador de la misma
  frase.
- `presente=true` requiere evidencia positiva de la relación actancial específica. Que haya un actor,
  una valoración, una acción, una causa o un elemento relacionado con la emoción no alcanza por sí
  solo. Ante ausencia de evidencia específica, usá `presente=false`.
- La justificación debe señalar evidencia textual concreta y explicar por qué satisface —o no— el
  criterio del componente. No inventes información exterior a la unidad analizada.

## Mediador

El mediador **vehiculiza la emoción desde la fuente hacia el experienciador fijado**. Para marcarlo
presente debe poder sostenerse la relación `fuente → mediador → experienciador`.

Prueba operacional:

1. Identificá la fuente ya fijada.
2. Preguntá si existe una instancia distinta que transporte, comunique, haga perceptible o vehiculice
   esa fuente hacia el experienciador.
3. Si el candidato es en realidad la fuente misma, una propiedad de la fuente, el acto que funciona
   como desencadenante o la mera expresión de la emoción por quien la siente, no hay mediador.

Tipos:

- `discurso_propio`: el discurso del enunciador funciona como vehículo hacia el experienciador
  fijado. No aplica cuando el experienciador es ese mismo enunciador y el discurso sólo expresa su
  propia emoción.
- `discurso_ajeno`: cita, testimonio, transcripción o voz reportada que vehiculiza la fuente.
- `documento_o_registro`: texto, archivo, imagen o registro que vehiculiza la fuente.
- `objeto_o_artefacto`: objeto material que media el vínculo; no si ese objeto es la fuente fijada.
- `espacio_o_escena`: espacio o escena cuya configuración media el vínculo; no si constituye por sí
  mismo el desencadenante fijado.
- `accion_o_comportamiento`: gesto o acción que vehiculiza la fuente; no si la acción es la propia
  fuente/desencadenante de la emoción.
- `ausente`: la fuente afecta al experienciador sin una tercera instancia mediadora discernible.

## Verificador normativo

El verificador normativo evalúa **si esa emoción es legítima, ilegítima, adecuada o inadecuada** según
una norma identificable. Puede hacerlo directamente o mediante la evaluación normativa de la fuente.

Prueba operacional:

1. Identificá un criterio claro: deber, derecho, justicia, regla institucional, convención o principio
   moral, ideológico, político o estético.
2. Marcá presencia si ese criterio evalúa directamente la emoción o tipifica la fuente como cumplimiento
   o transgresión **y funciona como fundamento explícito para legitimar o deslegitimar la emoción**.
3. Una valoración genérica, consecuencia, desacuerdo o fracaso no basta. Debe poder nombrarse la norma y
   explicarse cómo sostiene la adecuación o inadecuación de esa emoción.

Tipos:

- `norma_sociocultural`: convención o expectativa cultural compartida.
- `norma_moral_o_etica`: criterio de justicia, deber moral, bien/mal o sistema ético.
- `norma_juridica_o_institucional`: ley, reglamento, mandato o marco institucional.
- `norma_ideologica_o_politica`: principio ideológico o político usado normativamente.
- `norma_estetica_o_de_gusto`: criterio estético o de gusto.
- `ausente`: no se evalúa normativamente la emoción.

`evaluacion=legitima` valida la emoción; `deslegitima` la rechaza; `sin_evaluacion` corresponde a
`presente=false` o a ausencia de toma de posición normativa. `deslegitima` significa que la emoción es
rechazada o considerada inadecuada; no significa que la fuente sea ilegítima o transgresora.

## Verificador observacional

El verificador observacional realiza una operación epistémica sobre **la autenticidad de la emoción**
o sobre **la realidad/identidad de su desencadenante**. No se activa por una descripción factual
cualquiera.

Prueba operacional:

1. Determiná qué proposición se está comprobando, cuestionando o reinterpretando.
2. Esa proposición debe ser que la emoción fue realmente sentida o que el desencadenante fijado es
   real, verdadero o efectivamente el que produce la emoción.
3. Verbos como mostrar, confirmar, probar, ver o demostrar no alcanzan si verifican otra proposición
   del discurso sin evaluar la emoción ni su desencadenante.

Tipos:

- `cuestionamiento_de_autenticidad`: pone en duda que la emoción haya sido efectivamente sentida.
- `reinterpretacion_del_desencadenante`: sostiene que el desencadenante real es otro.
- `corroboracion_de_autenticidad`: afirma activamente que la emoción es genuina.
- `corroboracion_del_desencadenante`: confirma activamente que el desencadenante declarado es el real.
- `ausente`: no hay operación observacional sobre autenticidad ni desencadenante.

`evaluacion=realizada` confirma; `no_realizada` niega o cuestiona; `sin_evaluacion` corresponde a
`presente=false`.

## Operador de modificación

El operador de modificación es una operación discursiva **dirigida a cambiar esa emoción en el
experienciador fijado**: producirla, intensificarla, sostenerla, reorientarla, inhibirla o modificar su
legitimación argumentativa.

Prueba operacional:

1. Identificá al experienciador fijado y la emoción analizada.
2. Preguntá si el discurso interviene intencionalmente sobre la existencia, intensidad, orientación o
   continuidad de esa emoción en ese experienciador.
3. Describir la emoción, explicar su fuente, modificar la situación externa, formular una promesa o
   proyectar un futuro deseable no basta por sí solo. Debe existir una función discursiva dirigida a
   modificar la emoción del experienciador fijado.
4. Si el experienciador fijado habla para producir una emoción en terceros, esa intervención pertenece
   a la emoción de esos terceros, no a la emoción propia aquí analizada.

Funciones:

- `argumentacion_de_la_emocion`: aporta razones dirigidas a legitimar, cuestionar o problematizar esa
  emoción y con ello intervenir sobre ella.
- `persuasion_afectiva`: busca orientar al experienciador hacia un estado emocional futuro; requiere
  una función persuasiva dirigida, no la mera mención de un futuro favorable.
- `activacion_emocional`: busca generar o intensificar de forma inmediata la emoción en el
  experienciador.
- `inhibicion`: busca restringir, bloquear o desalentar la emoción en el experienciador.
- `ausente`: el discurso registra, describe o explica la emoción sin operar sobre ella.

## Polaridad

La polaridad describe si **la emoción predicada** se afirma o se niega. Es independiente de que la
fuente tenga valoración positiva o negativa.

Tipos:

- `afirmada`: la emoción se predica positivamente.
- `negada_factual`: se asevera que la emoción no ocurre.
- `negada_deontica`: se prescribe que la emoción no debe ocurrir.
- `negada_volitiva`: se expresa que la emoción no se desea.
- `negada_epistemica`: se niega que la emoción aparente o sea realmente el caso en el plano epistémico.

Usá `negada=true` para las cuatro formas de negación y `negada=false` para `afirmada`.

## Conflictos y solapamientos

- Los componentes son dimensiones distintas y pueden coexistir, pero la evidencia de uno no prueba
  automáticamente otro.
- `verificador_normativo` y `operador_modificacion` coexisten sólo si el texto, además de invocar una
  norma, usa esa operación para intervenir sobre la emoción del experienciador fijado.
- `mediador` y `operador_modificacion` coexisten sólo si hay, por un lado, una instancia que vehiculiza
  la fuente y, por otro, una operación dirigida a modificar la emoción. No reutilices un mismo elemento
  como ambos por mera proximidad semántica.
- Ante duda fundada entre tipos de un componente ya demostrado como presente, elegí el tipo más
  específico que sostenga la evidencia. La duda entre presencia y ausencia no se resuelve forzando
  presencia: exige evidencia positiva del componente.
