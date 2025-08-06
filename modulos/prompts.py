PROMPT_RESUMIR_DISCURSO = (
    "Título del discurso: <<TITULO>>\n"
    "Fecha: <<FECHA>>\n\n"
    "A continuación tenés los resúmenes parciales de un discurso político extenso.\n"
    "Redactá un resumen final fluido y preciso, sin repetir ideas, manteniendo el tono original y resaltando los temas clave del discurso.\n"
    "Evitá generalidades vacías o fórmulas genéricas. Escribí en español claro:\n\n"
    "<<RESUMENES_PARCIALES>>"
)

PROMPT_RESUMIR_FRAGMENTO = (
    "Resumí en español el siguiente fragmento de un discurso político, manteniendo su sentido general, tono e ideas principales. No inventes información y usá lenguaje claro y preciso:\n\n"
    "<<FRAGMENTO>>"
)

PROMPT_TIPO_DISCURSO = (
    "Estás analizando un discurso. Tu única tarea es identificar el tipo de discurso y justificar por qué.\n"
    "⚠️ Siempre agregá una justificación sobre por qué identificaste el discurso como correspondiente a un determinado tipo.\n\n"
    "### Resumen del discurso:\n<<RESUMEN>>\n\n"
    "### Fragmentos clave del discurso:\n<<FRAGMENTOS>>"
    "\n\nDiccionario conceptual:\n<<DICCIONARIO>>\n\n"
    "Respondé solo con un objeto JSON como este:\n"
    '{ "tipo": "...", "justificación": "..." }'
)

PROMPT_ENUNCIACION = (
    "Estás analizando un discurso. A partir del resumen y los fragmentos seleccionados, realizá las siguientes tareas:\n\n"
    "1. Identificá el **enunciador global**: indicá quién habla o produce el discurso, con base en los fragmentos disponibles. Siempre justificá con marcas o inferencias relevantes.\n"
    "2. Identificá los **enunciatarios globales**, según el tipo de discurso identificado y los 'tipos_de_destinatarios' del diccionario conceptual. Los enunciatarios globales son a quién o a quiénes se dirige el discurso. Clasificá cada enunciatario según las categorías del diccionario conceptual y justificá siempre cada caso con atención a las huellas enunciativas (apelaciones, pronombres, campos léxicos, etc.).\n"
    "⚠️ No generalices: no supongas que el destinatario es 'la población' o 'la ciudadanía' a menos que sea explícito o claramente inferible. Prestá especial atención a apelaciones directas, pluralidades construidas o formas de interpelación indirectas.\n"
    "⚠️ Identificá **un solo enunciatario por cada tipo definido en el diccionario conceptual**. Siempre debe ser el más general (ej: 'la oposición política', no nombres propios) y adecuado. Los tipos no deben repetirse.\n"
    "⚠️ No repitas tipos, ni inventes categorías nuevas.\n"
    "⚠️ Siempre justificá en el ítem 'justificación'.\n\n"
    "### Resumen:\n<<RESUMEN>>\n\n"
    "### Fragmentos clave del discurso:\n<<FRAGMENTOS>>"
    "\n\nDiccionario conceptual:\n<<DICCIONARIO>>\n\n"
    "Respondé solo con un JSON como este:\n"
    '{ "enunciador": {"actor": "...", "justificación": "..." }, "enunciatarios": [ { "actor": "...", "tipo": "...", "justificación": "..." } ] }'
)

PROMPT_LUGAR = (
    "Identificá el lugar desde el cual se pronunció el discurso (ciudad, provincia y país si se puede inferir).\n\n"
    "### Título:\n<<TITULO>>\n\n"
    "### Resumen:\n<<RESUMEN>>\n\n"
    "### Fragmentos clave del discurso:\n<<FRAGMENTOS>>\n\n"
    "Respondé solo con un JSON como este:\n"
    '{ "ciudad": "...", "provincia": "...", "país": "...", "justificación": "..." }'
)

PROMPT_IDENTIFICAR_ACTORES = (
    "Tarea:\n"
    "Identificá todos los actores representados en la frase objetivo, ya sean explícitos o inferidos, excepto el enunciador y los enunciatarios. Jamás agregues actores que no estén referidos léxica o sintácticamente en la frase objetivo.\n\n"
    "Datos disponibles:\n"
    "- Resumen global del discurso: {resumen_global}\n"
    "- Fecha del discurso: {fecha}\n"
    "- Lugar del discurso (con justificación): {lugar_justificacion}\n"
    "- Tipo de discurso: {tipo_discurso}\n"
    "- Enunciador: {enunciador}\n"
    "- Enunciatarios: {enunciatarios}\n"
    "- Frase objetivo a analizar: \"{frase}\"\n"
    "- Frases de contexto (anteriores y posteriores): {frases_contexto}\n"
    "- Reglas de inferencia para identificar actores: {heuristicas}\n"
    "- Ontología de actores (usar solo estas categorías): {ontologia}\n\n"
    "Criterios de identificación:\n"
    "- Solo incluí actores cuya presencia pueda fundamentarse claramente en la frase objetivo, ya sea explícita o por inferencia sustentada en vínculos léxicos o sintácticos claros.\n"
    "- Podés usar las frases de contexto solamente para interpretar la frase objetivo, pero nunca jamás para agregar actores que no estén referidos léxica o sintácticamente en la frase objetivo.\n"
    "- No incluyas al enunciador ni a los enunciatarios.\n"
    "- No agregues actores que no pertenezcan a las categorías listadas en la ontología.\n\n"
    "Invalidaciones:\n"
    "- No incluyas actores mencionados solamente en el contexto sin vínculo explícito con la frase objetivo.\n"
    "- Excluir cualquier mención ambigua, no anclable o sin justificación clara.\n\n"
    "Formato de salida:\n"
    "- Usá únicamente las categorías de la ontología.\n"
    "- Asegurate de que cada objeto JSON incluya todas las claves separadas por comas.\n"
    "- Especial atención: debe haber coma entre \"modo\": ... y \"regla de inferencia\": ...\n"
    "- Especial atención: no uses comillas dentro de los valores de texto (para evitar errores de sintaxis).\n\n"
    "Respuesta esperada: una lista JSON exclusivamente, sin texto adicional ni comillas internas:\n\n"
    '"""[\n'
    '  {{\n'
    '    "actor": "Nombre del actor (sustantivo o sintagma nominal)",\n'
    '    "tipo": "Categoría según la ontología",\n'
    '    "modo": "explícito" o "inferido",\n'
    '    "regla de inferencia": "Solamente el número de regla de inferencia utilizada, según las heurísticas, sin ningún tipo de explicación adicional"\n'
    '  }}\n'
    ']"""\n\n'
    "⚠️ Devolvé solo una lista JSON válida. Nada más.\n\n"
    "🚫 JAMÁS INCLUYAS AL ENUNCIADOR NI A LOS ENUNCIATARIOS. Aunque estén nombrados, deben ser excluidos completamente.\n"
    "🚫 NO USAR MODO: \"implícito\". Solo se permiten \"explícito\" o \"inferido\".\n"
    "🚫 SI EL MODO ES \"explícito\", NO AGREGUES NINGÚN NÚMERO DE REGLA.\n"
    "🚫 SI NO HAY SUSTANTIVOS EN LA FRASE, DEVOLVÉ UNA LISTA VACÍA."
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