# Diccionario de conceptos

*Categorías de análisis del discurso en el pipeline de EmoParse*

---

Este diccionario reúne las categorías semiótico-discursivas que organizan el funcionamiento de *EmoParse*. No es un glosario técnico del *software* (para eso está la documentación del repositorio) ni una exposición del marco teórico (para eso está el Trabajo Final): es una pieza intermedia, pensada para que quien lea una salida del sistema —un experienciador, una foria, un tipo de configuración— pueda recuperar de dónde viene esa categoría, qué nombra y bajo qué forma la volví computable.

Cada entrada tiene tres componentes: **procedencia** (la tradición de la que retomo el concepto), **sentido** (qué designa dentro del enfoque de *EmoParse*) y **operacionalización** (cómo esa noción se convierte en un campo, un valor de un conjunto cerrado o una etapa del *pipeline*). Las secciones siguen el recorrido de un discurso por el sistema: las nociones que fundan el enfoque, la escena enunciativa, los actores y sus marcas, la detección de la emoción, su caracterización, su configuración actancial y relacional, y las categorías del discurso nativo digital.

Cuando una entrada dice que un campo toma "uno de estos valores", se trata de una restricción que el sistema impone durante la generación del modelo de lenguaje, no de una recomendación. El conjunto de valores válidos está declarado de antemano y el modelo no puede devolver nada fuera de él. Así, la grilla categorial con la que el sistema lee permanece explícita, versionada y discutible, en lugar de quedar sedimentada de manera implícita, como en un clasificador entrenado.

---

## 1. Núcleo conceptual

### Emoción discursiva

La unidad de trabajo de todo el proyecto, y el concepto del que dependen los demás. Se distingue de la *emoción psíquica* —el estado corporal, afectivo o neurobiológico de un individuo—, cuya materialidad *EmoParse* no aborda ni pretende alcanzar. La emoción discursiva no nombra esa interioridad ni una expresión que la traduciría: nombra el *efecto* que se produce cuando una configuración de marcas, realizada en un discurso, es reconocida —por un sistema receptor situado en posición de observación— como portadora de una cierta cualificación afectiva. Si en un texto leo "el Papa está enojado", asigno una emoción ("enojo") a un actor ("el Papa"); esa asignación es una traducción metadiscursiva que opera sobre marcas observables. Cuando un modelo de lenguaje identifica una emoción en un texto, hace exactamente eso, y su salida es, en sentido estricto, una emoción discursiva, no un hallazgo sobre el estado mental de nadie. Toda la arquitectura del sistema se sostiene en esta distinción: lo que *EmoParse* produce son hipótesis de reconocimiento sobre configuraciones de formas, nunca mediciones de estados internos.

### Efecto de sentido

Procede de la semiótica de Eliseo Verón (2013) y, más atrás, de la articulación entre la lingüística de Antoine Culioli y la filosofía de la individuación de Gilbert Simondon que desarrollé en otro lado (Colman, 2023a, 2024). El sentido de una forma no es un contenido que ella transporte, sino el conjunto de transformaciones que esa forma produce al ser reconocida por estructuras de recepción dentro de un sistema psicosocial. Dicho de otro modo: una configuración de marcas no *tiene* un sentido, sino que *produce efectos* cuando alguien —una mente, un colectivo, un dispositivo— la reconoce, y el sentido son esos efectos. Para *EmoParse* esto tiene una consecuencia directa: la emoción discursiva es un efecto de sentido de tipo afectivo, y por eso su análisis no puede reducirse al rastreo de palabras aisladas, sino que exige reconstruir en qué condiciones y ante qué sistema de recepción una configuración puede sostener un reconocimiento afectivo.

### Forma, marca, configuración

El triple andamiaje material sobre el que se apoya todo lo demás, retomado de Culioli (2010) y de la tradición de las operaciones enunciativas. Una *forma* es una cualificación discernible: algo susceptible de ser reconocido como tal en un instante dado (Franckel y Lebaud, 2006). Una *marca* es una señal observable —léxica, morfosintáctica, prosódica, tecnográfica— inscripta siempre en un soporte material. Una *configuración* es el modo en que esas marcas aparecen organizadas. El principio operativo que de acá se desprende, y que atraviesa el diseño del sistema, es que lo único a lo que un sistema receptor accede son formas, nunca procesos psíquicos: todo lo que se diga sobre esos procesos es una hipótesis construida a partir de las marcas. En el sistema, esta noción se materializa en el modelo de datos: cada emoción, cada actor y cada atribución viene acompañada de la *marca* literal del texto que la habilita.

### Localizador

Un término que uso para nombrar la relación entre una marca y la emoción discursiva que sostiene, sin confundir una con otra. Las marcas que el análisis identifica —léxico afectivo, construcciones modales, patrones sintácticos, categorías con carga axiológica— no *son* la emoción: la *localizan*, en la medida en que, al ser reconocidas por un receptor, dan lugar a un efecto de sentido afectivamente cualificado. La distinción importa porque fija qué puede aspirar a *detectar* un sistema automatizado (marcas, configuraciones) y qué solo puede *reconstruir* de modo metadiscursivo a partir de ellas (la emoción). Operativamente, cada emoción detectada guarda el sintagma o el ítem léxico que la localiza, de manera que la hipótesis del sistema queda siempre anclada a una evidencia textual verificable.

### Cualificación afectiva

El criterio de contenido mínimo que vuelve "afectiva" a una cualificación, y no otra cosa. Una cualificación es afectiva cuando se articula alrededor de la atribución, a un actor, de un proceso de valoración y de modulación de su relación con un entorno, aun cuando el objeto de esa valoración quede implícito. No se postula ese proceso como sustancia interna del actor: se lo trata como un *referente* que el reconocimiento atribuye y que, en esa misma operación, pasa a integrar el efecto de sentido. Esta definición es deliberadamente económica —cubre tensiones, valoraciones y disposiciones sin comprometerse con ninguna teoría psicológica particular de la emoción— porque el sistema necesita un umbral claro para decidir cuándo una configuración de marcas cuenta como emocional y cuándo no.

### Medio

El conjunto de condiciones materiales, cognitivas y sociales que sostienen el funcionamiento de un discurso, es decir, los procesos por los que se produce y se reconoce. La noción viene de Simondon (2015): una forma solo produce un proceso de información —de adquisición de forma— cuando encuentra un medio en estado metaestable, capaz de ser reorganizado por su aparición. El medio no es un canal por el que un efecto se transmite, sino un componente de la producción de ese efecto; e incluye al sistema receptor que opera el reconocimiento. De ahí se sigue algo central para la evaluación del sistema: como el medio integra el efecto, la divergencia entre lecturas de un mismo texto no es ruido alrededor de un valor verdadero, sino un rasgo del fenómeno. Un mismo enunciado —"acaban de matar al presidente"— habilita un haz de cualificaciones afectivas cuya actualización depende del medio en que circula.

### Reconocimiento

Un dominio específico de los efectos del discurso, deudor de Verón (2013). Refiere a las operaciones —generalmente cognitivas— de puesta en relación entre marcas discursivas y producción de efectos de sentido, que se traducen en textos y comportamientos nuevos. La emoción discursiva vive del lado del reconocimiento: es el reconocimiento, por parte de un sistema receptor, de que cierta configuración de marcas porta una cualificación afectiva. Esto ubica al analista —y al modelo de lenguaje— no como observadores neutrales de una emoción presente en el texto, sino como sistemas de recepción que producen el efecto que dicen detectar. El sistema hace suya esta condición al tratar cada salida como una hipótesis de reconocimiento situada, y no como un dato sobre un objeto independiente del observador.

### Los tres niveles de los procesos discursivos

Una distinción analítica que uso para delimitar qué es accesible al análisis computacional y qué no. El **Nivel 1** son las operaciones de producción: los procesos cognitivos, sociales y culturales implicados en la génesis de un discurso, que un observador no ve directamente y solo puede inferir de modo parcial e hipotético. El **Nivel 2** son las configuraciones materiales: textos, enunciados, marcas observables; el ángulo desde el que las superficies discursivas quedan disponibles para el análisis. El **Nivel 3** son los efectos: las reorganizaciones cognitivas, afectivas, sociales y técnicas que esas configuraciones producen al ser reconocidas. Niveles 2 y 3 son dos cortes sobre un mismo proceso, no dos momentos sucesivos. *EmoParse* opera sobre el Nivel 2 y, a partir de él, formula hipótesis sobre el Nivel 3; no accede al Nivel 1 ni a los estados psíquicos de los actores, y no postula ese acceso.

### Simulacro de emoción

La unidad analítica central del sistema, y la que le da su arquitectura. Articula el *simulacro pasional* de Greimas y Fontanille (1994) con el *enunciado de emoción* de Plantin (2014), en la elaboración que propuse en mi tesis (Colman, 2024a). No es una configuración presente en el texto, sino *la forma esquemática que adquiere la reconstrucción metadiscursiva de una emoción discursiva* cuando la efectúa un sistema receptor, humano o computacional. Tiene la forma de un esquema de posiciones articuladas: un experienciador, una categoría emocional ligada a un proceso afectivo, fuentes o desencadenantes, mediadores, verificadores, operadores de transformación y un repertorio de marcas que funcionan como sus localizadores. Su doble cara —reconstrucción de un efecto, por un lado; esquema de posiciones, por otro— es lo que lo vuelve preferible a una etiqueta categorial o a un par valencia/intensidad: respeta la asimetría entre forma y emoción y, al mismo tiempo, ofrece una estructura interna que admite ser instrumentada como un conjunto de tareas diferenciadas. Cada posición del simulacro puede interrogarse por separado, con sus propias instrucciones, evidencias y criterios de validación; el *pipeline* es, precisamente, la traducción operativa de ese esquema.

### Modo de semiotización

Retomo el término de Raphaël Micheli (2013). "Semiotizar" una emoción no implica ni expresarla ni comunicar un estado interno: designa cualquier operación por la que un discurso pone en juego recursos para dar forma significativa a una emoción, sin presuponer que alguien la esté sintiendo. La noción permite mantener separado lo que se experimenta de lo que se significa, y por eso habilita a tratar en un mismo marco las autoatribuciones ("estoy furioso") y las atribuciones a terceros ("el público estaba ansioso"). En *EmoParse*, el modo de semiotización toma tres valores —**dicha**, **mostrada** y **sostenida**— siguiendo la distinción de Micheli y Plantin entre emociones nombradas, expresadas por indicios y sostenidas por la descripción de una situación. Este campo no lo infiere el modelo de manera directa: se deriva de forma determinista del *tipo de configuración* (ver más abajo), lo que garantiza que la relación entre uno y otro sea siempre coherente y auditable.

---

## 2. La escena enunciativa

*(Etapa `enunciation`. Opera sobre el discurso completo y produce el contexto que las etapas posteriores usan para desambiguar a quién se atribuye cada emoción.)*

### Enunciador

Una posición actancial del eje de la comunicación: la posición identificable con el "yo" del discurso, correspondiente a quien enuncia. Su especificación figurativa depende del tipo y el género de discurso —en un discurso argumentativo oral puede figurar como "orador", en un cuento como "narrador"—. No se confunde con el autor empírico ni, en el caso del discurso nativo digital, con el identificador técnico de la cuenta. El sistema lo identifica y, si es implícito pero deducible, lo infiere y lo declara como inferencia; cuando es del todo indeterminable, devuelve "no identificado" antes que forzar una atribución.

### Enunciatario(s)

La contraparte del enunciador: la posición identificable con el "tú", correspondiente a quien se dirige el enunciado. Puede haber varios. En el discurso político, retomo de Verón (1983) el fenómeno de **multidestinación**: un mismo discurso se dirige simultáneamente a destinatarios distintos con estatutos distintos. De ahí los tres roles del género `discurso_presidencial` —**prodestinatario** (aquel que comparte las creencias del enunciador, destinatario del refuerzo), **paradestinatario** (aquel indeciso al que se busca persuadir) y **contradestinatario** (el adversario, destinatario de la polémica)—. El rol es siempre un valor de la lista cerrada que declara el género; el sistema no puede devolver un rol que ese género no habilite. A cada enunciatario, además, se le asigna un actor concreto (una persona, un colectivo, una institución), nunca la etiqueta del rol.

En el género digital, la tipología de destinatarios se afina según el *tipo de tuit* —político, periodístico-informativo, institucional, humorístico, personal-cotidiano o promocional—, cada uno con su propio conjunto cerrado de roles, fundado en la tradición que mejor da cuenta de esa clase de discurso: la multidestinación veroniana para el político, el contrato mediático y la instancia-blanco/instancia-público para el periodístico, la pluralidad de públicos para el institucional, y así con los demás. A esos roles específicos se suman dos categorías *transversales*, presentes en cualquier tuit por ser propiedades del dispositivo antes que del tipo discursivo: la **audiencia ambiente** (el público difuso e imaginado que el colapso de contextos vuelve inevitable, en la línea de la *audiencia en red* y la *afiliación ambiente*: Marwick y Boyd, 2011; Zappavigna, 2011) y el **destinatario mencionado** (el `@`-destinatario explícito). La fundamentación completa de cada tipología, con su anclaje teórico y su cruce entre género y tipo de discurso, está en [la tipología de destinatarios por tipo de tuit](https://github.com/alexdcolman/EmoParse/blob/main/docs/other/tipologia_destinatarios_tuits_fundamentacion.md).

### Auditorio

Retomo la categoría de la tradición retórica. El auditorio es el destinatario *directo*: el público concreto presente en la situación de enunciación, quienes efectivamente escuchan o leen. Se distingue de los enunciatarios, que son posiciones de destinación y no público efectivo: el contradestinatario, por ejemplo, rara vez está en el auditorio, y un mismo auditorio puede reunir a varios tipos de enunciatario a la vez. La distinción no es escolástica: sin un auditorio identificado, un deíctico como "ustedes" no tiene a quién remitir. Por eso el auditorio es uno de los insumos de la resolución de la deixis.

### Colectivos de identificación

Tomo la noción del análisis del discurso político de Verón (1983). Un colectivo de identificación es la entidad colectiva con la que el enunciador se identifica o a la que adscribe —"nosotros los peronistas"—, y no aquella a la que se dirige. La distinción importa porque un colectivo del que se *habla* ("el Estado argentino") o un tema etiquetado ("#Milei") no son colectivos de identificación, salvo que el enunciador se inscriba explícitamente en ellos. Como el auditorio, los colectivos son un insumo de la deixis: sin ellos, un "nosotros" no tiene referente concreto. A cada colectivo el sistema le asigna una *clase*, tomada del conjunto válido para el tipo de discurso.

### Deixis (resolución deíctica)

*(Etapa `deixis`, opcional.)* La deixis es el conjunto de marcas —pronombres, posesivos, morfología verbal de primera y segunda persona: "yo", "nosotros", "ustedes", "veamos"— que refieren a un referente sin nombrarlo, por lo que la correferencia léxica no puede resolverlas: un "nosotros" no comparte forma con "argentinos" ni con "Javier Milei". A partir del enunciador, el auditorio y los colectivos ya identificados, esta etapa asigna cada marca deíctica a uno o varios referentes concretos del discurso. La asignación puede ser múltiple —"nuestro equipo" puede remitir a la vez al enunciador y a su colectivo de identificación—, lo que traduce operativamente el hecho de que el reconocimiento de la referencia depende del medio: que un "nosotros" remita a los argentinos en un discurso y a un colectivo ideológico transnacional en otro es una operación de reconocimiento, y delegarla en las posiciones enunciativas ya identificadas es el modo en que el sistema hace de esa dependencia una parte controlable del análisis.

---

## 3. Actores, marcas y referentes

*(Etapas `actors`, `explode_emotions`, la correferencia determinista, `modalidad` y `semas`.)*

### Actor discursivo

Un efecto de sentido, generalmente localizado en una unidad léxica nominal, que se presenta en el discurso como figura autónoma del universo semiótico (retomo a Greimas y Courtés, 2006). Incluye personas ("el presidente"), colectivos ("los trabajadores") e instituciones ("la Corte Suprema"), pero también actores inferibles a partir de unidades que no los nombran de manera explícita: una nominalización deverbal ("la represión" → "los represores") o un sintagma que permite deducirlos. Esta apertura tiene un corolario operativo: los actores válidos como posibles experienciadores de emoción se definen por sus rasgos semánticos en las ontologías, que son editables. Quien analice discursos de otro tipo —literatura fantástica, por ejemplo— puede habilitar actores con rasgos distintos ('animal', 'deidad', 'espacio') sin tocar el código.

### Marca / mención

Una *mención* es una marca en su lugar: una expresión situada en un discurso y una unidad ("Javier Milei", "ellos", "la casta", "tomamos"), registrada con independencia de la función que cumpla. La distinción entre la marca y su función es deliberada: las funciones actanciales —actor, experienciador, fuente— viven aparte, de modo que una misma marca puede ser a la vez actor y experienciador sin duplicarse. Este desacople es la traducción, en el modelo de datos, del principio de que lo único observable son configuraciones de marcas, y de que toda función que se les atribuya es una hipótesis construida sobre ellas.

### Referente canónico y correferencia

El *referente canónico* es la unidad bajo la cual el sistema agrupa las distintas marcas que, en una lectura, se reconocen como remitiendo a lo mismo ("el presidente", "Milei", "el jefe de Estado"). No es la marca ni una entidad del mundo: es un objeto de discurso construido por el análisis. Su construcción es automática y determinista —ocupa el lugar que en versiones anteriores tenía una etapa a cargo del modelo, ya eliminada— y se apoya en cuatro procedimientos: correferencia léxica conservadora, la inferencia dominante que el propio modelo produjo al detectar el actor, la resolución de la deixis de primera persona hacia el enunciador, y la coincidencia con una base de referentes ya conocidos. La regla de agrupamiento es deliberadamente cautelosa: es preferible que el sistema deje casi-duplicados sin unir, para que un revisor los resuelva, antes que fusione dos referentes distintos y borre una distinción que el corpus sostenía. El desplazamiento de una etapa inferencial hacia un procedimiento determinista tiene, además, una consecuencia sobre la reproducibilidad: la identidad de los referentes deja de depender de una inferencia que podría variar entre corridas.

### Modalidad referencial

*(Etapa `modalidad`, opcional.)* Un eje que clasifica *cómo* una marca refiere a un referente, ortogonal a la aceptación del vínculo. Nace de un problema concreto: un mismo vínculo entre marca y referente puede sostenerse de maneras muy distintas, y colapsarlas en una sola decisión de aceptar o rechazar hace perder información. Toma tres valores. La **designación** nombra o categoriza al referente con un sustantivo o un nombre propio ("Javier Milei", "el presidente de la Nación"). La **referencia gramatical** lo refiere por deixis o morfología, sin nombrarlo ("yo", "nosotros", "he defendido"). La **identificación inferencial** lo identifica por la actitud o los valores que expresa, no porque la marca lo nombre: "ellos son la casta corrupta" identifica al enunciador como quien sostiene esa posición, aunque no lo nombre. La clasificación es por vínculo y no por marca, porque un mismo sintagma puede designar a un referente e identificar inferencialmente a otro. El método es híbrido: las herramientas de procesamiento resuelven los casos claros —pronombres como referencia gramatical, nombres propios como designación— y el modelo de lenguaje interviene solo en los sintagmas ambiguos.

### Naturaleza del referente

El segundo eje de la clasificación de referentes: qué clase de entidad es aquello a lo que la marca remite. Toma cinco valores —**persona**, **colectivo**, **institución**, **objeto_proceso** (un objeto de discurso, un evento o una nominalización abstracta, como "el abandono del modelo de la libertad") y **otro**—. La distinción permite, entre otras cosas, separar los actores capaces de experimentar emociones de los objetos de valor que las desencadenan.

### Sema

Un rasgo semántico distintivo, en el sentido de la semántica estructural de Greimas (1971). *(Etapa `semas`.)* La etapa clasifica cada referente según un vocabulario curado de semas organizado por dimensiones. La primera decisión es la **clase** —*actor* (figura autónoma), *circunstante* (aquello que rodea a un actor sin ser autónomo) o *cualidad* (un predicado que califica a otra cosa)—, y de ella dependen las demás: la naturaleza, la individuación y la temporalidad solo tienen sentido para los actores; otras dimensiones, para los circunstantes o las cualidades. La temporalidad, acá, es histórica y no gramatical: un referente puede estar narrado en pretérito y seguir vigente hoy. Un conjunto de dimensiones opcionales —rol narrativo, agente/paciente, animación, figuratividad, especificidad, concreción— se completa solo cuando hay evidencia clara. Como en todo el sistema, el vocabulario de semas vive en una ontología editable, lo que permite ajustar la grilla al corpus bajo estudio.

---

## 4. La emoción detectada

*(Etapa `emotions`. Es el punto donde el sistema realiza la operación central del proyecto: reconocer configuraciones de marcas como portadoras de una cualificación afectiva. La lectura se hace, por defecto, frase por frase y de forma aislada, para impedir que el modelo "contagie" emociones de una frase a otra.)*

### Experienciador

El sujeto que vive o padece la emoción; la posición que ocupa el actor al que se atribuye el proceso afectivo. Retomo la categoría de Plantin (2014), donde el experienciador es una de las funciones del enunciado de emoción. En la salida del sistema se registran dos cosas distintas: el experienciador como referente concreto inferido (`exp`: "el presidente", "los manifestantes") y su *marca* literal en la unidad (`expm`: el sintagma o el verbo que lo identifica, "nosotros", "tienen miedo"). El desdoblamiento es coherente con el principio general: una cosa es la marca observable y otra la hipótesis metadiscursiva que se construye sobre ella.

### Fuente / desencadenante

El actor, evento o circunstante que *origina* la emoción en el experienciador. Retomo también acá la función de Plantin (2014). La distingo con cuidado del mediador (que vehiculiza la emoción) y del operador (que interviene sobre ella): la fuente la *desencadena*. Como el experienciador, se registra en dos campos: la fuente como referente inferido (`fue`) y su marca literal, contigua y breve, copiada del texto (`fuem`). Cuando no es determinable, el sistema devuelve "no identificado" antes que fabricar un origen.

### Categoría emocional y normalización

El núcleo semiótico de la experiencia: el tipo de emoción, expresado como sustantivo ("tristeza", "indignación", "esperanza"). El sistema lo detecta con vocabulario abierto —no lo constriñe a una taxonomía cerrada de emociones básicas, decisión que separa a *EmoParse* de los enfoques categoriales clásicos— y luego, en una etapa aparte (`normalize_emotions`), le asigna un nombre *canónico* tomado de las ontologías, de modo que variantes equivalentes ("bronca", "enojo", "ira") puedan agruparse en el análisis agregado sin perder el registro de la forma original. La equivalencia entre variantes vive en un diccionario editable, no en el código.

### Tipo de configuración

*(Campo `conf`.)* La categoría, diseñada en el proyecto que antecedió a *EmoParse*, que clasifica una emoción según el tipo de configuración discursiva que la sostiene. Son ocho, y responden a la pregunta de *cómo* la unidad porta la emoción, no de cuál es:

1. emociones sostenidas en **sustantivos** ("la tristeza de Mara" → tristeza);
2. emociones sostenidas en **adjetivos** ("los testigos estaban nerviosos" → nervios);
3. emociones sostenidas en **verbos psicológicos** ("los manifestantes se enojaron" → enojo);
4. emociones sostenidas en **indicadores cognitivos** ("totalmente concentrado en resolver el problema" → preocupación);
5. emociones sostenidas en **indicadores de comportamiento** ("evitó el contacto visual" → miedo, vergüenza);
6. emociones sostenidas en **indicadores axiológicos** ("una medida injusta y arbitraria" → rechazo, indignación);
7. emociones sostenidas en **formateos descriptivo-narrativos** ("los policías irrumpieron a la madrugada en el edificio" → temor u otras, según el contexto narrativo);
8. emociones sostenidas en la **transposición de una situación de reconocimiento potencial** que induce una emoción al enunciatario ("resulta evidente la gravedad del contexto" → preocupación inducida).

La utilidad de esta categoría es doble. Por un lado, obliga al modelo a justificar la emoción por su sostén formal concreto, y no por una impresión global. Por otro, de ella se deriva de forma determinista el *modo de semiotización*: las configuraciones (1)–(3) dan una emoción **dicha**; las (4)–(6), una emoción **mostrada**; las (7) y (8), una emoción **sostenida**. Es el mecanismo que garantiza que forma de sostén y modo de semiotización nunca se contradigan.

### Modo de existencia

*(Campo `modo`.)* Traduce la noción de *modos de existencia semiótica* de la semiótica tensiva (Fontanille y Zilberberg, 2016). Describe el estatuto de realización de la emoción en el discurso, con cuatro valores: **virtual** (la emoción como posibilidad o competencia, todavía no convocada), **actual** (insinuada o convocada sin realización plena), **potencial** (disponible, activable, proyectada sobre un actor) y **realizado** (explícitamente expresada o actuada). En la etapa de detección se agrega un quinto valor operativo, `inducida_proyectada`, para la emoción que el discurso provoca o atribuye a otro actor. La categoría permite distinguir, por ejemplo, la emoción efectivamente predicada de la que el discurso solo proyecta como horizonte deseable o temido, distinción que una etiqueta plana de "presencia de emoción" perdería.

---

## 5. La caracterización de la emoción

*(Etapa `characterizer`. Descompone cada emoción ya detectada en un conjunto de dimensiones, cada una con su propia justificación textual. Cada dimensión traduce un componente del simulacro de emoción en una variable con su criterio de extracción.)*

### Foria

*(Campo `foria`.)* El término —sustituto del griego *thymós*— fue introducido en la semiótica greimasiana para articular la tensión entre los polos de euforia y disforia (Greimas y Fontanille, 1994). Designa la atracción o repulsión de base del sujeto respecto de los objetos de valor: la **euforia** es el movimiento de acercamiento (alegría, esperanza, orgullo); la **disforia**, el de alejamiento (miedo, tristeza, indignación). A los dos polos clásicos sumo dos valores que permiten capturar configuraciones de mayor complejidad: la **ambiforia** (coexistencia simultánea de atracción y repulsión, como en una nostalgia agridulce) y la **aforia** (ausencia o neutralización de la tensión fórica). Un quinto valor, **indeterminado**, cubre los casos en que la valencia no es deducible. La foria es una de las dimensiones de alto acuerdo del sistema —próxima a lo constatable—, y por eso conserva su valor como criterio de evaluación por comparación con una referencia.

### Dominancia

*(Campo `dominancia`.)* El registro principal en el que la emoción se manifiesta discursivamente. Toma tres valores: **corporal** (somática, visceral, sensorial), **cognoscitiva** (mental, evaluativa, racionalizada) y **mixta** (ambos registros activos en proporción comparable). No es una afirmación sobre la fisiología del experienciador, sino sobre el tipo de marcas por las que la emoción se hace reconocible en el texto.

### Intensidad

*(Campo `intensidad`.)* El nivel de energía o activación afectiva que la emoción presenta en la unidad. Toma los valores **alta** (manifiesta, dominante), **baja** (tenue, en segundo plano) y **neutra_ambivalente** (imposible de calificar entre una y otra). A diferencia de la foria, la intensidad es una dimensión de campo admisible amplio: la coincidencia con una etiqueta única no es un buen criterio de evaluación para ella, y conviene juzgarla por la pertinencia de su justificación antes que por su acierto puntual.

### Duración

*(Campo `duracion`.)* La extensión temporal del estado emocional en el discurso, distinta tanto del aspecto como de la temporalidad histórica. Toma tres valores: **instantánea** (emoción puntual, que aparece y se disuelve en el fragmento: una exclamación, una reacción inmediata), **durable** (una pasión que se extiende a lo largo del enunciado sin estabilizarse) y **permanente** (un sentimiento-rasgo estable del experienciador, constitutivo de su identidad afectiva, sin límite temporal definido).

### Tipo de atribución

*(Campo `tipo_atribucion`.)* Retomo las categorías de Plantin (2014): define quién atribuye la emoción al experienciador y bajo qué condiciones. Toma tres valores, pero con un criterio estricto: la **auto_atribución** (el propio experienciador se atribuye la emoción en primera persona) y la **hetero_atribución** (otro actor se la atribuye a un tercero) exigen dos condiciones simultáneas —que la emoción esté explicitada mediante un término del campo léxico de la emoción, y que se atribuya sintácticamente a un actor—. Si falta cualquiera de las dos, el valor es **sin_atribución**, que es el caso por defecto: la emoción se infiere de la situación, de una valoración, de un adverbio modal o del comportamiento, pero nadie la enuncia como término emocional atribuido a alguien. La distinción evita el error frecuente de tratar como heteroatribución lo que en rigor es una inferencia del analista ("Occidente está en peligro" no es una atribución de miedo: el miedo se infiere del peligro).

### Temporalidad histórica

*(Campo `temporalidad`.)* El locus temporal *histórico* de la emoción respecto de la situación de enunciación —pensado en términos estrictos, no de aspecto ni de duración—. Toma cinco valores: **contemporánea** (del presente de la enunciación; incluye la emoción proyectada sobre el auditorio que escucha el discurso, aunque sea futura para él), **pasado_histórico** (el terror de las víctimas de un genocidio ya ocurrido), **futuro_histórico** (situada en un porvenir histórico, distinta de la del auditorio presente), **atemporal** (gnómica, un rasgo sin anclaje temporal) e **indeterminada**. Los factores de temporalidad y aspecto se retoman de la propuesta de Fabbri (2001) sobre los simulacros pasionales.

### Aspecto

*(Campo `aspecto`.)* El aspecto gramatical de la predicación emocional: cómo se presenta el desarrollo interno del estado, no cuándo ocurre. Toma seis valores —**perfectivo** (completado, visto como un todo cerrado), **imperfectivo** (en curso o habitual, sin foco en los límites), **ingresivo** (foco en el inicio), **terminativo** (foco en el cese), **iterativo** (repetido) y **no_marcado**—. Como la temporalidad, procede de la caracterización de la pasión de Fabbri (2001), y capta la dimensión aspectual con la que una configuración semiótica organiza el devenir de un estado afectivo.

---

## 6. La configuración actancial

*(Etapa `actants`, opcional. Es el punto donde el sistema sale del registro de la sola detección para entrar en el de la caracterización relacional: ubicar cada emoción dentro del entramado de operaciones que la sostienen, la evalúan y eventualmente la modifican. El análisis se hace emoción por emoción, porque una misma frase puede sostener varias emociones con configuraciones relacionales distintas. Cada componente puede estar presente o ausente, y cada uno se configura de forma independiente.)*

### Mediador

Aquello que *vehiculiza* la emoción entre su origen (la fuente) y quien la siente (el experienciador). La noción retoma una posición del esquema actancial del simulacro y proviene, más específicamente, del enfoque de Plantin (2014) sobre el enunciado de emoción, y también de la propuesta teórica de Latour (2008), que adapté para pensar la mediación emocional de artefactos, textos y espacios (Colman, 2024a). El mediador puede ser el propio discurso del orador, una voz citada, un documento, un objeto, un espacio o una acción. Cuando la emoción se vincula con su origen sin intermediario, el mediador se marca como ausente. Se lo distingue de la fuente con cuidado: la fuente *origina*, el mediador *transporta*.

### Verificadores

Operaciones del discurso que *evalúan* la emoción. El término se toma de Berrendonner (1982). *EmoParse* distingue dos, porque el discurso produce sobre las emociones juicios de naturaleza diferente. El **verificador normativo** evalúa la adecuación de la emoción a una norma —sociocultural, moral, jurídica, ideológica o estética—, sea para legitimarla ("está bien indignarse por esto") o para rechazarla ("no deberías estar triste por eso"); su evaluación se registra como *legítima*, *deslegítima* o *sin evaluación*. El **verificador observacional** evalúa, en cambio, la autenticidad de la emoción o la veracidad de su desencadenante: pone en duda la sinceridad ("no parecías enojado") o reinterpreta el disparador ("lo que en realidad te molesta es otra cosa"); su evaluación se registra como *realizada* (confirma), *no realizada* (niega) o *sin evaluación*. Unos juicios remiten al orden de lo socialmente sancionable, los otros al de la atribución causal.

### Operador de modificación

Una operación del discurso dirigida a *intervenir* sobre la emoción de algún actor. Recupera, en el plano operativo, la dimensión retórico-argumentativa de la emoción: el hecho de que esta no solo se enuncia o se expresa, sino que también orienta juicios y conductas. Toma cuatro funciones: **argumentación de la emoción** (legitimarla, cuestionarla o problematizarla argumentativamente, en el sentido de Plantin, 2010), **persuasión afectiva** (proyectar un horizonte emocional deseable o anticipado: "si confiás en mí, vas a estar tranquilo"), **activación emocional** (buscar generar la emoción como efecto intencional: "¡tenés que indignarte!") e **inhibición** (bloquear, restringir o deslegitimar afectivamente la emoción). Se lo distingue de la fuente —que origina— y del verificador —que evalúa—: el operador *actúa sobre* la emoción con una finalidad.

### Polaridad

Si la emoción se predica afirmada o negada, y bajo qué modalidad. La distinción importa porque la negación de una emoción no equivale a su ausencia: enunciar que un actor "no siente miedo" o que "nadie debería alegrarse por esto" inscribe la emoción en el discurso, aunque sea para negarla, y esa inscripción tiene efectos distintos de los de una afirmación directa. Toma los valores **afirmada** y cuatro formas de negación: **negada_factual** ("no se arrepienten"), **negada_deóntica** ("no se dejen robar la esperanza"), **negada_volitiva** ("no quiero que sientan miedo") y **negada_epistémica** ("no es que esté triste"). Registrar la polaridad permite separar la emoción predicada positivamente de la que aparece bajo el alcance de una negación, un contraste que la sola detección de la categoría subsumiría.

---

## 7. Género, tipo de discurso y unidad de análisis

### Género discursivo

Trabajo con una acepción de raíz bajtiniana (Bajtín, 1997): tipos relativamente estables de enunciados, caracterizados por regularidades temáticas, estilísticas y composicionales, que conforman condiciones históricamente sedimentadas para la producción y la recepción de sentido. En *EmoParse*, el género se traduce en un *descriptor declarativo* que especifica cómo varía el *pipeline* para una clase de discurso: la unidad de análisis, el conjunto cerrado de roles enunciativos válidos y otros parámetros. El sistema incorpora dos géneros —`discurso_presidencial` y `tuit`— y admite agregar otros sin modificar el núcleo. Esta apertura traduce un principio del enfoque: ningún sistema receptor puede reconocer configuraciones de marcas como afectivamente cualificadas si no dispone antes de las distinciones que organizan la clase de discurso que observa. Analizar tuits con la grilla enunciativa de un discurso presidencial impondría condiciones de reconocimiento ajenas al medio.

### Tipo de discurso

*(Etapa `metadata`.)* El reconocimiento del ámbito de producción verbal donde se inscribe convencionalmente un texto —discurso político, religioso, científico, literario—, en una de las acepciones que distingue Maingueneau (Charaudeau y Maingueneau, 2005). Dentro del discurso político, el sistema identifica además una subclase más fina (asunción, anuncio de medida, discurso de campaña, acto conmemorativo). El tipo de discurso, junto con el género, condiciona qué roles enunciativos y qué clases de colectivo son válidos, y forma parte del contexto que las etapas de detección usan para desambiguar.

### Unidad de *chunking*

El modo en que el discurso se segmenta condiciona qué configuraciones emocionales resultan visibles para el sistema. Elegir la frase, el párrafo o el documento entero como unidad de análisis define distintas condiciones del medio sobre el que se aplicarán las operaciones de reconocimiento. Cada género fija su unidad: el `discurso_presidencial` trabaja por frase; el `tuit`, por documento (y desactiva el resumen, por la brevedad del género). La elección no es neutral: emociones que solo se reconocen en la continuidad de un discurso pueden perderse en una lectura frase por frase, y por eso el sistema conserva —como etapa opcional y en revisión— una segunda pasada que reintroduce el contexto previo.

---

## 8. El discurso nativo digital

*(Categorías propias del género `tuit` y de los posts de redes sociales, donde hashtags, emojis, tecnografismos y menciones funcionan como marcas discursivas y afectivas de pleno derecho.)*

### Semiótica del hashtag

*(Etapa `hashtag_semiotics`.)* El hashtag es a la vez segmento del enunciado y operador de indexación: proyecta el post hacia un archivo buscable y puede construir comunión alrededor de valores, acoplando una evaluación o un afecto a un tema. Su funcionamiento no es fijo, sino que varía post a post, y por eso el sistema lo caracteriza *en cada uso* y no en general. Registra tres cosas: la **función** —*tópico* (indexa un tema sin evaluarlo), *afiliación_consigna* (comunión alrededor de una causa, donde usar el hashtag es sumarse), *evaluativo* (porta una valoración sobre su objeto: "#tarifazo" nombra y condena a la vez), *irónico* o *campaña*—; el **acoplamiento**, es decir, qué evaluación o afecto queda ligado a qué objeto de discurso en ese post; y la **foria del entorno**, la tonalidad fórica del post en que aparece. La forma y la posición del hashtag operan como indicios, no como determinaciones: los sufijos aumentativos o despectivos ("-azo", "-gate") y la nominalización de un reproche tienden a lo evaluativo; la posición pospuesta en bloque final y la coocurrencia con la primera persona plural, a la afiliación; y un mismo hashtag que en la muestra admite posts de valoraciones opuestas es, por eso, tópico y no evaluativo.

### Emoji afectivo

*(Etapa `emoji_affect`.)* Un emoji no porta un afecto fijo: aporta uno distinto según el contexto en que aparece. El sistema parte de un prior léxico —los valores afectivos típicos del emoji— pero decide siempre por el contexto: 😂 sobre una desgracia ajena celebrada es burla disfórica, y sobre una anécdota propia, risa eufórica; la ironía invierte los valores (un ✨ en un reproche es disfórico); y un emoji meramente referencial (🎃 junto a una receta de calabaza) no aporta afecto. Por eso la etapa determina, para cada uso, el tipo de emoción que el emoji aporta —o `sin_afecto`, si su función es ilustrativa o decorativa— y su foria; la repetición (😡😡😡) intensifica, pero no cambia el tipo. La categoría trata al emoji como una marca afectiva plena, sujeta a las mismas operaciones de reconocimiento contextual que el léxico.

### Menciones, enlaces y tecnografismos

*(Etapa `tecno_usage`.)* Caracteriza el uso pragmático de las marcas propias del dispositivo —las menciones (`@cuenta`), los enlaces y los tecnografismos (mayúsculas sostenidas, alargamientos, risas, puntuación expresiva)— en el contexto de cada post. El principio es el mismo que rige el resto del sistema: ni el tipo de entidad ni la posición sintáctica deciden la función, sino el contenido del post. Una misma mención puede *interpelar*, *confrontar*, *exponer* a la cuenta ante terceros (escracharla), *citarla*, *agradecerle*, *convocarla* o *marcar afiliación* con ella; unas mismas mayúsculas pueden ser grito de indignación, celebración, énfasis neutro o mero rótulo temático —la volanta del titular trasladada al post, que indexa el asunto sin expresar afecto—; y una misma risa puede ser complicidad o burla, según haya o no un blanco al que se ridiculiza. La etapa asigna a cada marca un único uso, tomado de un conjunto cerrado, y lo justifica citando el post. Trata así a la mención y al tecnografismo como marcas discursivas de pleno derecho —localizadores de posiciones enunciativas y de afectos—, sujetas a las mismas operaciones de reconocimiento contextual que el léxico.

### Reencuadre (recontextualización)

*(Etapa `reframing`.)* Qué hace un post cuando cita o repostea a otro. La operación se decide por el *comentario* del citador y su relación con lo citado, no por el contenido del post citado en sí. El sistema clasifica la **operación** dominante —*adhesión* (suscribe o amplifica lo citado haciéndolo propio), *ironía_distancia* (lo retoma con distancia burlona, invirtiéndolo), *denuncia* (lo exhibe para condenarlo), *neutra_informativa* (lo difunde sin toma de posición) o *ambigua*— y, de manera separada, el estatuto de las **emociones citadas** respecto del autor citador: *asumidas* (el citador las hace propias, típico de la adhesión), *semiotizadas* (las exhibe o comenta sin experimentarlas, típico de la ironía y la denuncia: quien denuncia la euforia ajena no está eufórico) o *ninguna*. Esta última distinción es una aplicación directa del concepto de semiotización: separa lo que un discurso *siente* de lo que *pone en escena*.

---

## 9. La verificación del simulacro

### Juez

*(Etapa `judge`, opcional.)* Un segundo modelo de lenguaje que corrobora el simulacro producido por el primero y, solo ante un error sustantivo, propone corregir el o los elementos equivocados. Recibe un contexto acotado —título, enunciador, auditorio, resumen y una ventana de frases vecinas— y atiende sobre todo a que el experienciador y la fuente estén bien atribuidos. Su alcance de corrección está restringido, y de forma deliberada, a los elementos de mayor valor y menor ambigüedad: experienciador, tipo de emoción, fuente, modo de existencia, temporalidad y los actantes. No evalúa foria, dominancia, intensidad, duración ni atribución. La razón es teórica: para las dimensiones donde el campo de lecturas admisibles es amplio, pedirle a un segundo modelo que "corrija" al primero reproduce el sesgo de anclaje, porque no dispone de un criterio más firme para dirimir entre lecturas igualmente admisibles. El juez interviene, entonces, solo donde tiene sentido exigir acierto y no mera admisibilidad: ante un retome de un discurso ajeno mal atribuido, una ironía no reconocida o una inversión de polaridad.

### Validadores semióticos

Reglas declarativas que codifican restricciones semióticas y que el sistema aplica a las caracterizaciones para detectar incoherencias, sin recurrir al modelo de lenguaje. Por ejemplo: una emoción atribuida en modo potencial no puede tener al enunciador como experienciador; una orientación afórica es incompatible con una intensidad alta. Las incidencias que estas reglas detectan no se corrigen de forma automática: se registran para que un revisor decida si corresponden a un error del sistema o a un fenómeno discursivo complejo que la regla no preveía —en cuyo caso la regla, y no la salida, es lo que conviene reconsiderar—. Los validadores son el punto donde el aparato teórico del sistema se vuelve una condición explícita y falsable: un marco que no pueda producir ninguna lectura inadmisible sería un marco demasiado laxo, y esa laxitud es un defecto, no una virtud.

---

## Bibliografía

Las nociones reunidas acá provienen, centralmente, de las siguientes tradiciones y autores: la semiótica narrativa y de las pasiones (Greimas, 1971; Greimas y Courtés, 2006; Greimas y Fontanille, 1994; Fontanille, 2001); la semiótica tensiva (Fabbri, 2001; Fontanille y Zilberberg, 2016); la teoría de las operaciones enunciativas (Culioli, 2010; Franckel y Lebaud, 2006); la propuesta semiótica y comunicacional de Eliseo Verón (1983, 2013), la retórica y los estudios de la argumentación (Berrendonner, 1982; Plantin, 2010, 2014; Micheli, 2013); la teoría del actor-red (Latour, 2008); las propuestas sobre el género y el tipo de discurso (Bajtín, 1997; Charaudeau y Maingueneau, 2005); los estudios sobre audiencias en redes (Marwick y Boyd, 2011; Zappavigna, 2011); y la filosofía de la individuación (Simondon, 2015). La articulación de conjunto, la noción de simulacro de emoción y la traducción de estas categorías a procedimientos computables se desarrollan en Colman (2023, 2024a) y en el trabajo que documenta este sistema (Colman, 2026).

Bajtín, M. (1997). *Estética de la creación verbal.* Siglo XXI.

Berrendonner, A. (1982). *Éléments de pragmatique linguistique.* Éditions de Minuit.

Charaudeau, P., y Maingueneau, D. (2005). *Diccionario de análisis del discurso*. Amorrortu.

Colman, A. (2023). La argumentación desde una perspectiva psico-socio-técnica. *Revista Eletrônica de Estudos Integrados em Discurso e Argumentação, 23*(1), 18-38.

Colman, A. (2024a). *Un "archivo de la represión" para la historia reciente: modos de existencia discursivos del archivo de la DIPPBA en artículos de investigación de historia (2003-2015)*. Tesis de Doctorado. FFyL-UBA.

Colman, A. (2026). *EmoParse: hacia la automatización del análisis de emociones discursivas con IA generativa*. Trabajo Final de Especialización. Especialización en Ciencias Sociales Computacionales, UNaB.

Culioli, A. (2010). *Escritos*. Santiago Arcos.

Fabbri, P. (2001). *El giro semiótico*. Gedisa.

Fontanille, J. (2001). *Semiótica del discurso.* Fondo de Cultura Económica.

Fontanille, J., y Zilberberg, C. (2016). *Tensión y significación.* Fondo Editorial de la Universidad de Lima.

Franckel, J. J., y Lebaud, D. (2006). Forme. En: D. Ducard y C. Normand (Eds.), *Antoine Culioli, un homme dans le langage* (pp. 332-357). Ophrys.

Greimas, A. J. (1971). *Semántica estructural*. Gredos.

Greimas, A. J., y Courtés, J. (2006). *Semiótica: Diccionario razonado de la teoría del lenguaje*. Gredos.

Greimas, A. J., y Fontanille, J. (1994). *Semiótica de las pasiones: de los estados de cosas a los estados de ánimo.* Siglo XXI.

Latour, B. (2008). *Reensamblar lo social: una introducción a la teoría del actor-red.* Manantial.

Marwick, A. E., y Boyd, D. (2011). I tweet honestly, I tweet passionately: Twitter users, context collapse, and the imagined audience. *New Media & Society, 13*(1), 114-133.

Micheli, R. (2013). Esquisse d'une typologie des différents modes de sémiotisation verbale de l'émotion. *Semen. Revue de sémio-linguistique des textes et discours*, (35).

Plantin, C. (2010). As razões das emoções. En: E. Mendez e I. Machado (Orgs.), *As emoções no discurso. Vol. II* (pp. 57-80). Mercado de Letras.

Plantin, C. (2014). *Las buenas razones de las emociones.* Universidad Nacional de Moreno.

Simondon, G. (2015). *La individuación a la luz de las nociones de forma y de información.* Cactus.

Verón, E. (1983). La palabra adversativa. En: AA.VV., *El discurso político. Lenguajes y acontecimientos*. Hachette.

Verón, E. (2013). *La semiosis social 2: Ideas, momentos, interpretantes*. Paidós.

Zappavigna, M. (2011). Ambient affiliation: A linguistic perspective on Twitter. *New Media & Society, 13*(5), 788-806.

---

## Documentos relacionados

- [*EmoParse: hacia la automatización del análisis de emociones discursivas con IA generativa*](https://github.com/alexdcolman/EmoParse/blob/main/docs/other/EMOPARSE_HACIA_LA_AUTOMATIZACION_DEL_ANALISIS_DE_EMOCIONES_DISCURSIVAS_CON_IA_GENERATIVA.pdf) — Trabajo (PDF) donde se desarrollan en extenso el enfoque teórico-metodológico y la prueba del sistema.
- [Tipología de destinatarios por tipo de tuit: fundamentación teórica y propuesta](https://github.com/alexdcolman/EmoParse/blob/main/docs/other/tipologia_destinatarios_tuits_fundamentacion.md) — el cruce entre género y tipo de discurso en el dominio digital, y el anclaje teórico de las categorías de destinatario.
