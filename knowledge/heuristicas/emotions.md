Reglas de inferencia emocional. Se aplican a cada unidad por separado.

Detección
- No inventes emociones: registrá solo las que tienen indicio léxico, sintáctico o situacional en la unidad analizada. Si no hay ninguno, devolvé lista vacía.
- No uses contenido de otras unidades para inferir emociones de una.
- No repitas la misma emoción para el mismo experienciador en la misma unidad, salvo que difieran en modo de existencia.

Experienciador y fuente
- Cada emoción tiene UN experienciador. Si dos actores sienten la misma emoción, devolvé una entrada por actor, cada una con su propio modo de existencia: el enunciador puede sentirla realizada y proyectarla al auditorio como potencial.
- Nunca fusiones experienciadores distintos en una sola etiqueta ("macri_milei", "javier milei y asistentes"): son entradas separadas. La fuente, en cambio, puede combinar entidades ("me irritan los colectivistas y los socialistas" es una sola emoción).
- Si el segundo término es un posesivo anafórico sobre el primero, resolvé la anáfora al separar: "Carlitos y su círculo cercano" da "Carlitos" y "círculo cercano de Carlitos". Un "su X" nunca queda suelto como referente.
- El experienciador es un referente con nombre, nunca el deíctico ni el rol ("nosotros", "enunciador", "enunciatario") ni una construcción sobre ellos. Si un plural deíctico ("nosotros", "nuestro") abarca varios referentes distinguibles (el enunciador y su gobierno, el enunciador y el pueblo), devolvé una entrada por referente. La marca, en cambio, se transcribe entera: los plurales deícticos no se parten como marca.

Denominación de las categorías
- Una sola denominación por campo. Si dudás entre dos, escribí solo la primera: nunca "Argentina / Estado argentino", nunca "curiosidad / ironía".
- tipo_emocion nombra UNA emoción, en sustantivo y sin agregados: "indignación", no "frustración, arrepentimiento", no "estrés/agobio", no "sentirse traicionado", no "alegría, justificación: …". Sin comillas, comas, barras, paréntesis ni glosas.

Modo de existencia
- Las emociones atribuidas a la audiencia o a los destinatarios son siempre potenciales, salvo que el texto simule explícitamente que ya la sienten ("entiendo que estén enojados" da realizada).

Configuración del simulacro (TIPO_CONF)
- Elegí la configuración predominante. Si hay varias activas, priorizá la marca léxica o sintáctica más directa (sustantivo > adjetivo > verbo psicológico) por sobre las inferenciales.
- Las configuraciones sostenidas en sustantivos, adjetivos o verbos psicológicos solo aplican si la marca pertenece a la familia léxica de una emoción ("amor", "amaba", "amado"). Una palabra que no nombra ni deriva de una emoción ("inclaudicable", "aliado") no es marca léxica emocional: ahí la emoción se porta por indicadores cognitivos, de comportamiento, axiológicos, descriptivo-narrativos o por transposición.
- Usá transposicion_situacion_reconocimiento_potencial cuando ninguna marca léxica ni conductual la determina con claridad y la emoción se reconstruye desde la situación enunciativa.
