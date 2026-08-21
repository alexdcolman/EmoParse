Reglas heurísticas para la evaluación de coherencia del simulacro emocional:

El juez no vuelve a detectar la emoción ni reabre dimensiones excluidas por el contrato. Corrobora únicamente errores sustantivos en los campos corregibles del simulacro, usando la frase objetivo, sus marcas textuales y su contexto inmediato.

1. **Umbral de corrección**
   - Partí de una presunción de coherencia: `coherente=false` exige una contradicción sustantiva, directa y suficientemente demostrable con la evidencia disponible, además de una corrección materialmente distinta del valor actual.
   - No busques activamente una alternativa mejor. La tarea es detectar errores claros, no reanalizar el simulacro desde cero. Si dos lecturas siguen siendo razonablemente compatibles con la frase y la ventana, conservá la existente y marcá `coherente=true`.
   - Dos formulaciones que refieren razonablemente a la misma entidad o situación NO constituyen un error. No corrijas artículos, mayúsculas, guiones bajos, abreviaciones, alias, paráfrasis equivalentes ni diferencias razonables de granularidad.
   - No reemplaces un valor correcto sólo por una formulación que te parezca más precisa, más canónica o más elegante. Ante duda entre dos lecturas compatibles, conservá la existente.

2. **Experienciador y fuente**
   - Verificá que el experienciador y la fuente correspondan a la emoción concreta que se juzga, no al tono global de la frase.
   - Usá `Marca experienciador` y `Marca fuente` como evidencia textual prioritaria del análisis. La sintaxis local y las marcas explícitas pesan más que una reinterpretación global del tono o del tema. La inferencia puede ser más explícita o canónica que la marca sin estar equivocada.
   - La fuente es aquello que desencadena la emoción; puede ser un evento, una medida, una situación o un actor. No es automáticamente el experienciador, el destinatario, el autor de una cita ni el agente que causó ese evento o medida.
   - El agente responsable de una fuente no pasa por eso a ser experienciador de la emoción.
   - Prestá especial atención a retomas, discurso referido, citas e ironía. En discurso referido, no reasignes la emoción al orador actual sólo porque reproduzca, comente o adhiera a lo dicho por otra voz. La tercera persona o la descripción de un estado ajeno tampoco convierten por sí solas una emoción en `inducida_proyectada`.
   - Una denominación afectiva explícita de un actor —por ejemplo, llamarlo "pesimista"— es evidencia para atribuirle esa emoción cuando el contexto la sostiene. El desacuerdo del orador con ese actor no transfiere automáticamente la emoción al orador.
   - Una fuente debe poder reconstruirse desde la frase o el contexto disponible. No la sustituyas por un tema general del discurso ni por un sinónimo equivalente.

3. **Tipo de emoción y modo de existencia**
   - Marcá incoherencia sólo cuando el tipo de emoción contradiga claramente la evidencia disponible, no por preferir una etiqueta cercana ni por elegir la emoción que mejor describa el tono global.
   - Una misma frase, contraste temporal o secuencia puede sostener más de una emoción a la vez. La presencia de satisfacción, orgullo, alivio u optimismo no invalida automáticamente una emoción negativa ligada a otro segmento, actor o momento de la misma unidad.
   - No sustituyas una emoción upstream sólo porque otra etiqueta también sea plausible. Para corregir `tipo_emocion`, la etiqueta actual debe resultar incompatible con la evidencia, no meramente menos saliente.
   - Revisá el modo de existencia cuando haya una contradicción clara entre emoción realizada, actual, potencial, virtual o inducida/proyectada y la forma en que el discurso la presenta.
   - `inducida_proyectada` corresponde cuando el discurso induce, prescribe o proyecta la emoción sobre otro actor; no por el solo hecho de que el experienciador esté en tercera persona, sea un colectivo o aparezca como afectado por una situación.

4. **Temporalidad**
   - Corregí la temporalidad únicamente cuando el anclaje temporal sea inequívoco y el valor asignado resulte incompatible con la frase o su ventana.
   - No conviertas diferencias interpretativas finas en errores sustantivos.

5. **Actantes**
   - Revisá sólo los actantes declarados como corregibles por el contrato.
   - Mediador: exige una instancia diferenciable de fuente y experienciador que vehiculice la relación emocional.
   - Verificador normativo: la evaluación legitima/deslegitima refiere a la emoción, no a si la fuente es legítima o transgresora. `deslegitima` sólo cuando la emoción misma es rechazada, presentada como injustificada, inadecuada o excesiva; condenar la fuente no deslegitima automáticamente la emoción.
   - Verificador observacional: atiende a operaciones que confirman o niegan autenticidad o desencadenante.
   - Operador de modificación: exige una intervención discursiva orientada a transformar el estado emocional.
   - Polaridad no es valencia afectiva. Una emoción negativa, como indignación o miedo, puede estar `afirmada`. Usá polaridad negada sólo cuando la predicación de la propia emoción esté efectivamente negada o modalizada negativamente; no la infieras del carácter negativo de la emoción, de una consecuencia adversa, de una amenaza, de pobreza/daño ni de la condena de su fuente.

6. **Criterio de confianza**
   - Alta: sólo cuando el veredicto está directamente sostenido por una marca, relación sintáctica o contradicción inequívoca.
   - Media: el veredicto es razonable pero requiere alguna inferencia contextual.
   - Baja: la unidad es fragmentaria o varias lecturas siguen siendo razonables.
   - Si para declarar `coherente=false` necesitás una reconstrucción discutible del tono, del referente o de la intención, no corresponde confianza alta; ante lecturas alternativas compatibles, preferí `coherente=true`.

7. **Issues y sugerencias**
   - Si el simulacro es coherente, no propongas correcciones.
   - Si es incoherente, identificá el problema sustantivo de forma breve y proponé sólo correcciones cuyo campo y valor puedas sostener.
   - Proponé cada campo como máximo una vez. No emitas correcciones contradictorias o duplicadas para el mismo campo.
   - La sugerencia debe cambiar realmente el análisis: no propongas una variante superficial o equivalente del valor existente.
   - No corrijas terminología menor ni diferencias estilísticas.
