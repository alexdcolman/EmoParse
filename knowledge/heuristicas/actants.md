# Heurísticas — análisis actancial de emociones

Estas heurísticas guían al agente que identifica la configuración
actancial de cada emoción: mediador, verificador normativo,
verificador observacional y operador de modificación. Son
recomendaciones generales aplicables a todo género discursivo;
afinen según el corpus si fuera necesario.

## Principios generales

- Una misma frase puede contener emociones con configuraciones
  actanciales distintas. Analizá cada emoción **por separado**, sin
  proyectar la configuración de una sobre las demás.
- Cuando un componente no esté presente en la emoción analizada,
  declarálo explícitamente con `presente=false` y completá los
  campos asociados con valores de ausencia. Evitá forzar la
  presencia de un componente solo porque "parece haber algo
  relacionado".
- La justificación debe **citar elementos del texto**. Si no se
  pueden citar elementos concretos, eso es buen indicio de que el
  componente está ausente.

## Mediador

- El mediador no es la *fuente* de la emoción. La fuente es lo que
  la origina; el mediador es lo que la **vehiculiza** o
  **transporta** hacia el experienciador.
- `discurso_propio` aplica típicamente cuando el discurso del
  enunciador busca producir una emoción en su destinatario: el
  propio enunciado funciona como vehículo afectivo.
- `discurso_ajeno` aplica cuando la emoción se vehiculiza vía cita,
  testimonio, transcripción de otra voz.
- `documento_o_registro` aplica para archivos, textos, imágenes,
  registros materiales. Un historiador que comenta documentos
  emocionalmente cargados usualmente tiene a esos documentos como
  mediadores.
- `objeto_o_artefacto`, `espacio_o_escena`, `accion_o_comportamiento`
  son mediadores no discursivos, útiles para discursos narrativos
  o descriptivos con anclaje sensible.
- `ausente`: el vínculo entre fuente y experienciador es directo,
  sin intermediación discernible. Caso típico: una emoción dicha en
  primera persona sin vehículo externo.

## Verificador normativo

- Se distingue del observacional en que **invoca una norma**
  (cultural, moral, legal, ideológica, estética) para evaluar la
  emoción.
- El verificador normativo no necesariamente *afirma* la norma:
  puede invocarla solo para deslegitimar la emoción.
- Si la operación pone en duda la legitimidad cultural de un
  *tipo* de emoción ("los celos son malos") o su adecuación a una
  situación ("no deberías estar triste por eso"), hay verificador
  normativo presente.
- `evaluacion=legitima` cuando el verificador valida la emoción;
  `deslegitima` cuando la rechaza; `sin_evaluacion` cuando
  `presente=false` o el discurso no toma posición clara.

## Verificador observacional

- Se distingue del normativo en que **no invoca una norma**, sino
  que evalúa la **autenticidad** de la emoción o la **veracidad**
  de su desencadenante.
- `cuestionamiento_de_autenticidad`: el discurso pone en duda que
  la emoción haya sido efectivamente sentida ("no parecías
  enojado", "te hacés el indignado").
- `reinterpretacion_del_desencadenante`: el discurso propone que
  el desencadenante real es distinto del declarado ("lo que en
  realidad te molesta no es esto sino aquello").
- `corroboracion_de_autenticidad` y
  `corroboracion_del_desencadenante`: el discurso afirma que la
  emoción o su desencadenante son auténticos. Aplican cuando hay
  una operación discursiva activa de corroboración, no por mera
  ausencia de cuestionamiento.

## Operador de modificación

- No basta con que una emoción exista para que haya operador de
  modificación. El operador implica una **operación discursiva
  dirigida** a modificar la emoción de un experienciador.
- `argumentacion_de_la_emocion`: el discurso aporta razones para
  legitimar, cuestionar o problematizar la emoción
  argumentativamente.
- `persuasion_afectiva`: el discurso proyecta un horizonte
  emocional **futuro** deseable o esperado en el experienciador.
  Implica anticipación de una emoción que aún no se realiza
  ("si confiás en mí, vas a sentirte tranquilo").
- `activacion_emocional`: el discurso busca generar la emoción
  como efecto intencional inmediato y definido ("¡tenés que
  indignarte!", apelaciones a la indignación, miedo, orgullo
  inmediato).
- `inhibicion`: el discurso restringe, bloquea o deslegitima la
  emoción de un experienciador.
- `ausente`: el discurso registra o describe la emoción pero no
  opera sobre ella.

## Conflictos y solapamientos

- `verificador_normativo` y `operador_modificacion` pueden coexistir.
  Una argumentación que invoca una norma para deslegitimar una
  emoción combina ambas dimensiones: el verificador es la norma
  invocada, el operador es la argumentación que la usa.
- `mediador` puede coexistir con `operador_modificacion`. Si el
  discurso busca activar una emoción usándose a sí mismo como
  vehículo, hay mediador (`discurso_propio`) y operador
  (`activacion_emocional`) presentes.
- Ante duda fundada entre dos categorías de un mismo componente,
  elegí la más específica que el texto sostenga literalmente y
  declará la incertidumbre en la justificación.
