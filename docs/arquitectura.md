# Arquitectura y diseño de EmoParse

*Referencia técnica pública del estado actual de EmoParse.*

EmoParse transforma un corpus en una serie de hipótesis analíticas trazables. Para hacerlo separa
las tareas que suelen aparecer mezcladas: adquirir textos, decidir cómo se segmentan, construir el
contexto del género, pedir inferencias estructuradas a modelos de lenguaje, aplicar operaciones
deterministas, persistir cada resultado y habilitar la revisión humana.

Este documento explica esa separación. Cuando aparece un término técnico, se lo define en el mismo
lugar donde se vuelve necesario.

## 1. El recorrido general

El recorrido tiene cinco momentos:

1. **Entrada**. Un archivo CSV, JSON o JSONL aporta los textos y su metadata.
2. **Ingesta y segmentación**. El género valida la metadata y decide si la unidad de análisis es una
   frase, un párrafo o el documento completo.
3. **Pipeline**. Una secuencia de etapas produce resúmenes, escena enunciativa, emociones,
   referentes y caracterizaciones.
4. **Persistencia**. Cada corrida escribe una SQLite propia. SQLite es una base de datos contenida en
   un solo archivo.
5. **Revisión y exportación**. El tablero lee esa base; las correcciones humanas se guardan sin borrar
   la inferencia original; el export produce archivos CSV abiertos.

Una corrida puede detenerse y reanudarse. Cada etapa escribe su salida antes de que comience la
siguiente, por lo que una interrupción no obliga a repetir el trabajo completado.

## 2. Capas y responsabilidades

La arquitectura está dividida en capas. La división no responde solo a una cuestión de orden del
código: impide que una fuente de adquisición, un género o una vista del tablero redefinan el sentido
de los datos.

```text
Interfaces      CLI · tablero · adquisición · carga de archivos
Orquestación    pipeline · DAG · selección · reintentos · contexto
Géneros         unidad · roles · metadata · reglas y capacidades propias
Agentes         llamadas a modelos y transformación de sus respuestas
Dominio         categorías y validadores semióticos
Núcleo          backends · generación estructurada · cache · schemas
Persistencia    SQLite por corrida · repositorios · exportadores
Conocimiento    vocabularios · heurísticas · recursos editables
```

Las dependencias principales apuntan hacia abajo. La interfaz puede consultar la persistencia, pero
la persistencia no conoce el tablero. Un adapter de Página/12 sabe extraer un artículo, pero no decide
qué cuenta como lector-ciudadano. Esa decisión pertenece al descriptor del género periodístico.

## 3. Géneros declarativos

Un género es una ficha que declara cómo debe variar el análisis. Actualmente hay tres géneros
incluidos:

- `discurso_presidencial`: unidad por frase y posiciones de destinación política;
- `articulo_periodistico`: unidad por párrafo, metadata editorial y roles periodísticos;
- `tuit`: unidad por post, contexto conversacional y materialidad propia de plataformas.

La ficha del género puede declarar:

- la unidad de segmentación;
- los roles enunciativos válidos;
- los tipos de discurso admitidos;
- un modelo tipado para la metadata de entrada;
- qué campos de esa metadata se muestran en la interfaz;
- qué campos llegan como contexto a cada etapa;
- capacidades propias, como el análisis tecnodiscursivo de posts;
- ajustes de lote o modelo cuando una tarea lo requiere.

La metadata se valida antes de ingresar a la base. En un artículo periodístico, por ejemplo,
`autoria` puede contener una firma o varias; el género la normaliza y la usa para fijar de manera
determinista la instancia emisora. El nombre del medio queda como contexto editorial, no reemplaza a
la firma.

Cada corrida guarda además un **snapshot de presentación** del género: una copia mínima de su nombre
y de las etiquetas de sus campos. Gracias a eso, una base puede abrirse años después aunque el plugin
que definía el género ya no esté instalado.

## 4. Contexto estático y contexto dinámico

No todo el contexto proviene del cuerpo del texto.

El **contexto estático del género** reúne metadata declarada: medio, sección, subtítulo, autoría o
agencia en un artículo. Cada bloque indica qué etapas lo consumen y un presupuesto aproximado. El
presupuesto limita cuánto texto auxiliar entra en una llamada.

El **contexto dinámico** se calcula durante la corrida. En posts puede incluir la cadena de respuestas,
las marcas tecnodiscursivas, la descripción de una imagen o el contenido citado. Todos esos bloques
usan una interfaz común: declaran su alcance, la etapa que los produce o consulta y las etapas que
los reciben.

Esta composición evita dos errores frecuentes: copiar templates completos para cada género y sumar
contexto sin controlar su tamaño.

## 5. El pipeline como grafo

Las etapas forman un **DAG**, un grafo dirigido sin ciclos. Un grafo representa relaciones; en este
caso, una flecha indica qué resultado debe existir antes de ejecutar otra etapa.

Hay dos clases de dependencia:

- **dura**: la etapa no puede ejecutarse sin su antecedente;
- **blanda**: el antecedente mejora el contexto, pero la etapa funciona si no fue habilitado.

Por ejemplo, `emotions` necesita la escena construida por `enunciation`. `actors`, en cambio, es una
dependencia blanda: aporta una lista de actores si se ejecutó, pero la detección emocional puede
trabajar sin ella.

Las etapas activas por defecto cubren el recorrido general. Las etapas de análisis fino, redes,
visión, segunda lectura o auditoría son optativas. El orden del DAG no equivale a habilitación: una
etapa puede estar declarada en el grafo y no formar parte de una corrida.

## 6. Inferencia estructurada

Cada agente pide al modelo una tarea acotada y declara un schema. Un **schema** es la definición de
los campos, tipos y valores válidos de una respuesta.

Los backends locales restringen la generación para que el modelo produzca una estructura válida:

- con llama.cpp, el schema se compila a una gramática GBNF;
- con servidores compatibles con OpenAI, se usa JSON Schema estricto cuando el backend lo admite.

Esta restricción garantiza la forma, no la verdad de la lectura. Una respuesta puede ser un JSON
perfecto y atribuir una emoción al actor equivocado. Por eso el sistema combina forma restringida,
contratos entre etapas, validadores de dominio y revisión humana.

## 7. Detección, normalización y caracterización

Estas operaciones están separadas porque resuelven preguntas diferentes.

### Detección

`emotions` identifica una expresión emocional con vocabulario abierto y conserva la etiqueta
producida, el experienciador, la fuente, el modo de existencia y la evidencia textual. La segunda
lectura opcional puede revisar una unidad con el contexto previo del mismo texto.

### Materialización

`explode_emotions` convierte cada emoción en una fila propia y construye las primeras relaciones
entre marcas y referentes. Es una operación determinista: no vuelve a consultar al modelo.

### Normalización

`normalize_emotions` consulta un catálogo de nombres canónicos y aliases. Agrega el nombre canónico
sin reemplazar la etiqueta cruda. Una emoción sin correspondencia queda registrada como brecha de
normalización; no se descarta.

### Caracterización

`characterizer` describe foria, intensidad, dominancia, duración, temporalidad, atribución y
configuración. Algunas variables analíticas se derivan después de manera determinista para evitar
que el modelo tome decisiones redundantes o contradictorias.

La separación permite evaluar si un problema proviene de una omisión de detección, una atribución,
un alias faltante o una caracterización, en vez de convertir todo desacuerdo en un único error.

## 8. Marcas, funciones y referentes

Una **marca** es una expresión situada en el corpus: «Milei», «nosotros», «la casta» o una forma
verbal. Su función se guarda aparte: la misma marca puede ser actor y experienciador.

Los **referentes canónicos** agrupan expresiones que remiten a la misma entidad. La relación es
muchos-a-muchos porque un «nosotros» puede incluir más de un referente y una entidad puede aparecer
con muchas denominaciones.

La base conserva:

- la marca y su ubicación;
- las funciones que cumple;
- los vínculos propuestos, aceptados o rechazados;
- el origen de cada vínculo;
- la modalidad referencial, cuando se analizó;
- los semas asignados al referente.

Las correcciones humanas no borran la inferencia original. La procedencia permite distinguir lo que
propuso el modelo, lo que resolvió una regla y lo que decidió la persona que revisó.

## 9. Persistencia por corrida

Cada corrida usa una SQLite independiente. Las tablas centrales conservan:

- `runs`: identidad, estado, configuración y versiones;
- `discursos`: texto original, metadata y resultados de nivel documento;
- `frases`: unidades segmentadas y payloads de detección;
- `emociones`: una fila por emoción materializada;
- tablas de menciones y referentes;
- cache de respuestas;
- incidencias de validación;
- veredictos del juez;
- métricas por etapa;
- tablas específicas de posts, redes y elementos tecnodiscursivos cuando corresponden.

Los payloads flexibles se guardan como JSON dentro de columnas de texto. Los campos que necesitan
consultas frecuentes o integridad relacional tienen tablas propias.

`run --prepare-only` usa la misma ingesta y segmentación, pero detiene el recorrido antes de ejecutar
etapas o cargar modelos. Sirve para verificar un corpus y preparar bases de anotación sin producir
salidas analíticas.

## 10. Selección y reanudación

`--select` permite acotar una corrida sin crear un corpus alternativo. Puede filtrar:

- campos originales del input;
- resultados de etapas previas mediante notación punto, como
  `metadata.tipo_discurso`.

Los filtros sobre resultados se activan solo cuando la etapa que los produce está completa. El
alcance se persiste por etapa, y `status` distingue pendiente, completado, fallido, no aplicable y
fuera de alcance. Una corrida posterior sin selector retoma lo excluido sin repetir lo ya guardado.

## 11. Evaluación

La evaluación combina controles automáticos y anotación humana.

Los controles automáticos verifican schemas, contratos entre etapas, persistencia, reglas semióticas
y, de forma optativa, la revisión de un segundo modelo.

El circuito humano permite:

1. crear una muestra ciega reproducible;
2. anotar presencia, tipo, experienciador, fuente, modo de existencia y foria;
3. congelar la planilla como golden set versionado;
4. repetir una submuestra para medir consistencia intraanotador;
5. comparar uno o varios runs y separar el reporte por género.

Un golden set no reemplaza la lectura cualitativa. Funciona como alarma de regresión: señala que un
cambio estructural alteró la salida respecto de una anotación fijada.

La comparación de modelos mantiene el corpus constante y crea una SQLite independiente por
configuración. Las métricas contra el golden pueden persistirse en el propio run; el dashboard
muestra el routing observado, advierte mezclas de modelos y compara acuerdo y referencias sin
reescribir las salidas analíticas.

## 12. Extensión

Las extensiones principales tienen fronteras distintas:

- una **fuente** adquiere y normaliza datos;
- un **género** declara unidades, roles, metadata y contexto;
- una **etapa** coordina una operación en el DAG;
- un **agente** define una tarea de inferencia estructurada;
- un **backend** conecta un motor de generación;
- un **validador** comprueba una regla de dominio;
- una **vista** presenta datos ya definidos por las capas anteriores.

La guía `docs/puntos_de_extension.md` muestra los contratos concretos. El mapa detallado de rutas se
mantiene en `.dev/referencia/directorios.md` para el desarrollo local.

## 13. Principios de diseño

Las decisiones que atraviesan todo el sistema son:

- conservar siempre el texto original;
- anotar sin sobrescribir;
- separar inferencia, normalización y revisión;
- mantener una base por corrida;
- declarar el género en lugar de inferirlo desde nombres de columnas;
- usar contexto con presupuesto;
- hacer visibles la procedencia y las versiones;
- preferir operaciones deterministas cuando no hace falta un modelo;
- evitar que una interfaz o un adapter redefina categorías analíticas;
- tratar la revisión humana como parte del método, no como corrección externa.

Esa arquitectura permite cambiar un modelo, agregar una fuente o incorporar un género sin volver a
diseñar el conjunto del programa.

## 14. Observabilidad y registro

La consola muestra el avance de la tarea en curso. Además, cada corrida puede escribir un log propio
en `logs/` con detalle de depuración, rotación por tamaño y retención limitada. El log permite
reconstruir fallos sin mezclar varias corridas y evita incorporar al traceback las variables locales
que podrían contener fragmentos sensibles del corpus.

Las métricas por etapa se persisten en la SQLite: tiempos, unidades procesadas y, cuando el backend
lo informa, velocidad de generación. `status`, `metrics` y el tablero consultan la misma fuente de
estado; no mantienen contadores paralelos.

## 15. CLI y documentación generada

Los subcomandos se registran mediante un catálogo común. El punto de entrada recorre ese catálogo y
no necesita conocer por nombre cada comando. Esta organización permite agregar una operación sin
convertir el archivo principal del CLI en una lista creciente de casos especiales.

La referencia `docs/comandos.md` y su versión HTML se generan desde el parser real. El modo
`python scripts/gen_cli_reference.py --check` compara los archivos publicados con la superficie
actual del programa. Por eso las opciones no deben corregirse a mano solo en la documentación: el
cambio comienza en el parser y la referencia se regenera.

## 16. Pruebas y controles de integración

La validación del proyecto separa tres niveles:

- **contratos**: protegen comportamiento estable, schemas, DAG, persistencia y CLI sin usar modelos;
- **andamio**: documenta capacidades en evolución sin convertirlas todavía en un bloqueo general;
- **integración LLM**: pruebas explícitas y optativas que requieren modelos y hardware local.

Ruff verifica estilo, mypy cubre una frontera tipada explícita y la integración continua ejecuta los
controles compatibles con un entorno sin GPU. Las pruebas con modelos se realizan después de que los
controles deterministas han pasado y respetan el routing real de `config.yaml`.

## 17. Backends y ejecución por lotes

Los agentes usan un contrato común y el routing de `config.yaml` decide qué alias ejecuta cada stage.
EmoParse incluye tres rutas locales:

- `llama_cpp`, que carga un GGUF dentro del proceso;
- `llama_server`, que se conecta a `llama-server` por HTTP;
- `lmstudio`, que usa la interfaz compatible con OpenAI de LM Studio.

El backend servidor puede aprovechar procesamiento concurrente, reutilización de prefijos, cache KV
cuantizado o modelos multimodales según la forma en que fue iniciado. Esas capacidades pertenecen al
motor; el agente conserva el mismo schema y la misma tarea.

En una llamada por lotes, cada ítem declara el índice de la unidad a la que corresponde. La
asignación se hace por ese índice y puede incorporar un ancla textual adicional. El orden en que el
modelo enumera los resultados no se toma como evidencia de correspondencia. Un batch inconsistente
se rechaza para evitar que una lectura válida termine asociada con otro fragmento.

Cuando un lote excede la ventana de contexto, el agente lo divide una vez y reintenta cada mitad. La
unidad que sigue excediendo el límite queda registrada como fallida. Los detalles de diagnóstico se
explican en [`docs/solucion_de_problemas.md`](solucion_de_problemas.md).

## 18. Cache y versiones de recursos

Cada llamada puede reutilizar una respuesta anterior cuando coincide su clave. La clave incorpora el
modelo, los prompts, el schema, la semilla, las versiones de recursos y, en llamadas multimodales, un
digest de las imágenes.

Las cuatro versiones permiten invalidar una parte concreta del trabajo:

- `knowledge`: recursos generales;
- `prompt`: templates, heurísticas y composición del contexto;
- `ontology`: ontologías y catálogos consumidos por las tareas;
- `schema`: estructura de las respuestas.

El versionado no reemplaza el registro de configuración de la corrida. La SQLite conserva las
versiones y el routing usados, de modo que dos resultados pueden compararse con su procedencia. Un
cambio de prompt invalida las llamadas que dependían de él y deja disponibles las demás respuestas.
