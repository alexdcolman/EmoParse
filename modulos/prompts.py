# prompts.py

PROMPT_RESUMIR_DISCURSO = (
    "Título del discurso: <<TITULO>>\n"
    "Fecha: <<FECHA>>\n\n"
    "Se presentan los resúmenes parciales de un discurso político extenso. "
    "Redactá un resumen final coherente, fluido y preciso, integrando todos los resúmenes parciales. "
    "Resaltá los temas clave y mantené el tono original. "
    "Evitá generalidades vacías, frases genéricas o repeticiones. Escribí en español claro:\n\n"
    "<<RESUMENES_PARCIALES>>"
)

PROMPT_RESUMIR_FRAGMENTO = (
    "Resumí en español el siguiente fragmento de un discurso político. "
    "Conservá el sentido general, las ideas principales y el tono del discurso. "
    "No inventes información, usá lenguaje claro y preciso, evitando repeticiones:\n\n"
    "<<FRAGMENTO>>"
)

PROMPT_TIPO_DISCURSO = (
    "Estás analizando un discurso. Tu tarea es identificar el tipo de discurso y justificarlo.\n"
    "### Resumen del discurso:\n<<RESUMEN>>\n\n"
    "### Fragmentos clave:\n<<FRAGMENTOS>>\n\n"
    "Diccionario conceptual:\n<<DICCIONARIO>>\n"
)

PROMPT_LUGAR = (
    "Identificá desde dónde se pronunció este discurso (ciudad, provincia, país si se puede inferir).\n\n"
    "Si no se menciona la ciudad, inferí de acuerdo al evento, institución o nombre de exposición. Para eso, utilizá solamente el título del discurso y focalizá en la información que brinda.\n\n"
    "Solo considerá información que indique el lugar del discurso.\n\n"
    "### Título:\n<<TITULO>>\n\n"
    "### Resumen:\n<<RESUMEN>>\n\n"
    "### Fragmentos clave:\n<<FRAGMENTOS>>\n"
)

PROMPT_ENUNCIACION = (
    "Estás analizando un discurso. A partir del resumen y los fragmentos seleccionados, realizá las siguientes tareas:\n\n"
    "1. Identificá el **enunciador global**: indicá quién habla o produce el discurso, con base en los fragmentos disponibles. Siempre justificá con marcas o inferencias relevantes.\n"
    "2. Identificá los **enunciatarios globales**, según el tipo de discurso identificado y los 'tipos_de_destinatarios' del diccionario conceptual. Los enunciatarios globales son a quién o a quiénes se dirige el discurso. Clasificá cada enunciatario según las categorías del diccionario conceptual y justificá siempre cada caso con atención a las huellas enunciativas (apelaciones, pronombres, campos léxicos, etc.).\n"
    "⚠️ No generalices: no supongas que el destinatario es 'la población' o 'la ciudadanía' a menos que sea explícito o claramente inferible. Prestá especial atención a apelaciones directas, pluralidades construidas o formas de interpelación indirectas.\n"
    "⚠️ Identificá **un solo enunciatario por cada tipo definido en el diccionario conceptual**. Siempre debe ser el más general (ej: 'la oposición política', no nombres propios) y adecuado\n"
    "⚠️ Es muy importante que no repitas tipos de enunciatarios, ni inventes categorías nuevas.\n"
    "⚠️ Siempre justificá en el ítem 'justificación'.\n\n"
    "### Resumen:\n<<RESUMEN>>\n\n"
    "### Fragmentos clave del discurso:\n<<FRAGMENTOS>>"
    "\n\nDiccionario conceptual:\n<<DICCIONARIO>>\n\n"
)

PROMPT_IDENTIFICAR_ACTORES = (
    "Tarea: identificá todos los actores representados en la frase objetivo, ya sean explícitos o inferidos, excepto el enunciador y los enunciatarios. Jamás agregues actores que no estén referidos léxica o sintácticamente en la frase objetivo.\n\n"
    "Datos disponibles:\n"
    "- Resumen global del discurso: {resumen_global}\n"
    "- Fecha del discurso: {fecha}\n"
    "- Lugar del discurso: {lugar_justificacion}\n"
    "- Tipo de discurso: {tipo_discurso}\n"
    "- Enunciador: {enunciador}\n"
    "- Enunciatarios: {enunciatarios}\n"
    "- Frase objetivo a analizar: \"{frase}\"\n"
    "- Frases de contexto (anteriores y posteriores): {frases_contexto}\n"
    "- Reglas de inferencia para identificar actores: {heuristicas}\n"
    "- Ontología de actores: {ontologia}\n\n"
    "Criterios:\n"
    "- Solo actores explícitos o inferidos claros.\n"
    "- No incluir enunciador ni enunciatarios.\n"
    "- Usar únicamente categorías de la ontología.\n\n"
    "Formato de salida: lista JSON, cada actor como objeto con claves:\n"
    '  "actor": "...", "tipo": "...", "modo": "explícito" o "inferido", "regla_de_inferencia": "..." (opcional si modo explícito)\n\n'
    "⚠️ Devolver solo la lista JSON válida. Nada más."
)

PROMPT_VALIDAR_ACTORES = (
    "Tarea:\n"
    "Analizá si el siguiente actor mencionado en una frase representa a un ser humano individual, un grupo humano o una institución conformada por humanos.\n\n"
    "Frase:\n\"<<FRASE>>\"\n\n"
    "Actor identificado:\n\"<<ACTOR>>\"\n\n"
    "Ontología de actores válidos:\n<<ONTOLOGIA>>\n\n"
    "Evaluación:\n"
    "¿Este actor corresponde a alguno de los tipos válidos definidos en la ontología? Respondé sólo con \"Válido\" si cumple con los criterios, o \"Excluido\" si no lo cumple. No agregues explicaciones."
)