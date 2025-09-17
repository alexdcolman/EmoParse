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
    "Si no se menciona la ciudad, inferí de acuerdo al evento, institución o nombre de exposición. Para eso, utilizá solamente el título del discurso y focalizá en la información que brinda.\n"
    "Si el campo 'provincia' no aplica, podés agregar 'estado' o 'region' según el caso. En caso de no saber, indicá 'no aplica'.\n\n"
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
    "Analizá si el siguiente actor mencionado en una frase representa a un ser humano individual, un grupo humano o una institución conformada por humanos. Los nombres de grupos humanos pueden ser míticos.\n\n"
    "Frase:\n\"{frase}\"\n\n"
    "Actor identificado:\n\"{actor}\"\n\n"
    "Ontología de actores válidos:\n{ontologia}\n\n"
    "Evaluación:\n"
    "¿Este actor corresponde a alguno de los tipos válidos definidos en la ontología? Respondé sólo con \"Válido\" si cumple con los criterios, o \"Excluido\" si no lo cumple. No agregues explicaciones."
)

PROMPT_DETECCION_EMOCIONES = (
    "Título del discurso: {titulo}\n"
    "Resumen global del discurso:\n{resumen_global}\n\n"
    "Fecha: {fecha} | Lugar: {lugar_justificacion} | Tipo de discurso: {tipo_discurso}\n"
    "Enunciador: {enunciador}\n"
    "Enunciatarios: {enunciatarios}\n"
    "Actores: {actores}\n\n"
    "Frase a analizar:\n{frase}\n\n"
    "Contexto (frases anteriores y posteriores):\n{frases_contexto}\n\n"
    "Heurísticas a considerar para identificar emociones:\n{heuristicas}\n\n"
    "Ontología de modos de existencia:\n{ontologia}\n\n"
    "Tarea: Identificá TODAS las emociones discursivas en esta frase, atribuidas a:\n"
    "- Enunciador\n"
    "- Enunciatarios\n"
    "- Actores de la frase\n\n"
    "Para cada emoción, especificá:\n"
    "- Experiencador: instancia que experimenta la emoción identificada (enunciador, enunciatario específico o actor)\n"
    "- Tipo de emoción\n"
    "- Modo de existencia (realizada, potencial, actual, virtual)\n"
    "- Justificación breve basada en la frase y contexto\n\n"
    "Respondé en formato JSON válido.\n"
    "No inventes experienciadores. Sólo considerá actores o instancias que estén identificadas como enunciador, enunciatarios o actores."
)

PROMPT_EMOCIONES_ENUNCIADOR = (
    "Título del discurso: {titulo}\n"
    "Resumen global del discurso:\n{resumen_global}\n\n"
    "Fecha: {fecha} | Lugar: {lugar_justificacion} | Tipo de discurso: {tipo_discurso}\n"
    "Enunciador: {enunciador}\n"
    "Enunciatarios: {enunciatarios}\n"
    "Actores: {actores}\n\n"
    "Frase a analizar:\n{frase}\n\n"
    "Contexto (frases anteriores y posteriores):\n{frases_contexto}\n\n"
    "Heurísticas a considerar para identificar emociones:\n{heuristicas}\n\n"
    "Ontología de modos de existencia:\n{ontologia}\n\n"
    "Tarea: Identificá TODAS las emociones discursivas atribuibles EXCLUSIVAMENTE al ENUNCIADOR en la frase a analizar.\n\n"
    "Para cada emoción, especificá:\n"
    "- Enunciador (conforme al enunciador ya definido: {enunciador})\n"
    "- Tipo de emoción\n"
    "- Modo de existencia (realizada, potencial, actual, virtual)\n"
    "- Justificación breve basada en la frase y contexto\n\n"
    "Respondé en formato JSON válido."
)

PROMPT_EMOCIONES_ENUNCIATARIOS = (
    "Título del discurso: {titulo}\n"
    "Resumen global del discurso:\n{resumen_global}\n\n"
    "Fecha: {fecha} | Lugar: {lugar_justificacion} | Tipo de discurso: {tipo_discurso}\n"
    "Enunciador: {enunciador}\n"
    "Enunciatarios: {enunciatarios}\n"
    "Actores: {actores}\n\n"
    "DICCIONARIO de tipos de enunciatarios:\n{diccionario}\n\n"
    "Frase a analizar:\n{frase}\n\n"
    "Contexto (frases anteriores y posteriores):\n{frases_contexto}\n\n"
    "Heurísticas a considerar para identificar emociones:\n{heuristicas}\n\n"
    "Ontología de modos de existencia:\n{ontologia}\n\n"
    "Tarea: Identificá TODAS las emociones discursivas atribuibles a los ENUNCIATARIOS en la frase a analizar.\n\n"
    "Para cada emoción, especificá:\n"
    "- Enunciatario específico (conforme a cada uno de los enunciatarios proporcionados, si correspondiera identificar emoción: {enunciatarios})\n"
    "- Tipo de emoción\n"
    "- Modo de existencia (realizada, potencial, actual, virtual)\n"
    "- Justificación breve basada en la frase y contexto\n\n"
    "Respondé en formato JSON válido.\n"
    "Sólo considerá las emociones que se infieren de la frase a analizar, correspondientes a los enunciatarios proporcionados. No identifiques emociones del enunciador ni de los actores bajo ninguna circunstancia para este prompt.\n"
    "Sé exhaustivo en la identificación de las emociones de los enunciatarios. Considerá qué emociones puede generar el discurso de la frase analizar en los enunciatarios identificados.\n"
    "IMPORTANTE: Cuando atribuyas emociones a los enunciatarios, recordá que casi siempre suelen ser POTENCIALES, salvo que la frase indique que efectivamente ellos ya expresaron o realizaron esa emoción."
)

PROMPT_EMOCIONES_ACTORES = (
    "Título del discurso: {titulo}\n"
    "Resumen global del discurso:\n{resumen_global}\n\n"
    "Fecha: {fecha} | Lugar: {lugar_justificacion} | Tipo de discurso: {tipo_discurso}\n"
    "Enunciador: {enunciador}\n"
    "Enunciatarios: {enunciatarios}\n"
    "Frase a analizar:\n{frase}\n\n"
    "Actores en la frase:\n{actores}\n\n"
    "Contexto (frases anteriores y posteriores):\n{frases_contexto}\n\n"
    "Heurísticas a considerar para identificar emociones:\n{heuristicas}\n\n"
    "Ontología de modos de existencia:\n{ontologia}\n\n"
    "Tarea: Identificá TODAS las emociones discursivas atribuibles a los ACTORES mencionados en la frase a analizar.\n\n"
    "Para cada emoción, especificá:\n"
    "- Actor concreto (conforme a cada uno de los actores proporcionados, si correspondiera identificar emoción: {actores})\n"
    "- Tipo de emoción\n"
    "- Modo de existencia (realizada, potencial, actual, virtual)\n"
    "- Justificación breve basada en la frase y contexto\n\n"
    "Respondé en formato JSON válido.\n"
    "Sólo considerá las emociones de los actores proporcionados en la lista de actores en la frase a analizar. No identifiques emociones del enunciador ni de los enunciatarios bajo ninguna circunstancia para este prompt. Tampoco consideres emociones que sólo aparezcan en las frases de contexto. No identifiques emociones de actores que no sean los siguientes: {actores}. Ojo: puede que no haya actores identificados en esta frase. En ese caso, ignorá este prompt."
)

PROMPT_FORIA = (
    "Recorte de discurso: {recorte_id}\n"
    "Experienciador: {experienciador}\n"
    "Tipo de emoción: {tipo_emocion}\n"
    "Frase: {frase}\n"
    "Justificación previa de la emoción: {justificacion}\n\n"
    "Tarea: Determinar la FORIA (carácter fórico) de la emoción identificada.\n"
    "Valores posibles:\n"
    "Eufórico\n"
    "Disfórico\n"
    "Afórico\n"
    "Ambifórico\n\n"
    "Heurísticas: {heuristicas}\n"
    "Ontología: {ontologia}\n\n"
    "Respondé en formato JSON válido."
)

PROMPT_DOMINANCIA = (
    "Recorte de discurso: {recorte_id}\n"
    "Experienciador: {experienciador}\n"
    "Tipo de emoción: {tipo_emocion}\n"
    "Frase: {frase}\n"
    "Justificación previa de la emoción: {justificacion}\n\n"
    "Tarea: Determinar la DOMINANCIA de la emoción identificada para el experienciador.\n"
    "Valores posibles:\n"
    "Corporal\n"
    "Cognoscitiva\n"
    "Mixta\n\n"
    "Heurísticas: {heuristicas}\n"
    "Ontología:\n{ontologia}\n\n"
    "Respondé en formato JSON válido."
)

PROMPT_INTENSIDAD = (
    "Recorte de discurso: {recorte_id}\n"
    "Experienciador: {experienciador}\n"
    "Tipo de emoción: {tipo_emocion}\n"
    "Frase: {frase}\n"
    "Justificación previa de la emoción: {justificacion}\n\n"
    "Tarea: Determinar la INTENSIDAD de la emoción identificada.\n"
    "Valores posibles:\n"
    "Alta\n"
    "Baja\n"
    "Neutra/Ambivalente\n\n"
    "Heurísticas: {heuristicas}\n"
    "Ontología:\n{ontologia}\n\n"
    "Respondé en formato JSON válido."
)

PROMPT_FUENTE = (
    "Recorte de discurso: {recorte_id}\n"
    "Experienciador: {experienciador}\n"
    "Tipo de emoción: {tipo_emocion}\n"
    "Frase: {frase}\n"
    "Justificación previa de la emoción: {justificacion}\n\n"
    "Tarea: Identificar la FUENTE de la emoción.\n"
    "- fuente: actor, objeto, situación, experiencia o espacio CONCRETO que produce la emoción.\n"
    "- tipo_fuente: clase de fuente según la ontología.\n"
    "- justificacion: breve explicación.\n\n"
    "Heurísticas: {heuristicas}\n"
    "Ontología:\n{ontologia}\n\n"
    "Respondé en formato JSON válido.\n"
    "IMPORTANTE: la fuente es aquello que desencadena una emoción. Es distinta del experienciador, que es quien siente la emoción. No confundas fuente con experienciador. La fuente identificada debe ser distinta del experienciador suministrado.\n"
    "Cuando identifiques la fuente, es necesario que identifiques la entidad concreta que desencadena la emoción. No devuelvas deícticos como 'yo' o 'nosotros'. Cuando identifiques tipo_fuente, corresponde a la clase de fuente según la ontología. No confundas ambas cuestiones"
)