Reglas de inferencia emocional. Se aplican a cada unidad por separado.

Detección
- Registrá solo emociones con indicio léxico, sintáctico o situacional en la unidad. Si no hay evidencia, devolvé lista vacía.
- Una emoción mencionada, negada, ausente o contenida en discurso ajeno no se atribuye automáticamente al enunciador.
- La negación, ausencia o carencia de una emoción no licencia por sí sola otra emoción asociada u opuesta.
- No repitas la misma emoción para el mismo experienciador y modo de existencia.

Experienciador, fuente y marcas
- Cada emoción tiene un solo experienciador concreto. Si el emisor la siente, usá el referente indicado como Enunciador, no “hablante”, “autor” ni “enunciador”.
- `expm` y `fuem` son secuencias literales, breves y de la unidad actual. El contexto puede resolver `exp` o `fue`, pero nunca aporta marcas.
- Una matriz epistémica en primera persona (`creo que`, `pienso que`, `siento que`, `me parece que`) no convierte al enunciador en experienciador de la emoción predicada en la subordinada.
- Si una emoción léxicamente presente no tiene experienciador recuperable, usá `no identificado`; no la reasignes al emisor por defecto.
- Nunca fusiones experienciadores distintos. La fuente sí puede reunir varios desencadenantes coordinados.

Categorías y configuración
- `tipo_emocion` nombra una sola emoción canónica, en sustantivo y sin glosas, barras ni alternativas.
- Elegí una sola configuración. Priorizá la marca directa: sustantivo, adjetivo o verbo psicológico; las configuraciones inferenciales se usan cuando no hay marca léxica directa.
- Una predicación explícita `actor + verbo/estado emocional` conserva ese actor como experienciador; una matriz epistémica externa no cambia esa relación.
- Las emociones atribuidas a audiencia o destinatarios son potenciales salvo que la unidad las presente como ya realizadas.

Construcciones frecuentes
- `agradecer` porta gratitud; una emoción nombrada en su complemento puede ser solo contenido ajeno.
- `siento que + proposición` es epistémico/perceptivo y no crea por sí solo ansiedad, sorpresa ni otra emoción.
- `espero + proposición` y `ojalá` pueden portar una única esperanza o deseo del enunciador; no dupliques la misma lectura como interés ni como una segunda esperanza sin marca independiente.
- `estar + adjetivo afectivo` se clasifica por el adjetivo, no como comportamiento.
- Una condición que suspende la creencia hasta obtener pruebas puede realizar desconfianza, pero no toda forma futura de `creer` la expresa.
