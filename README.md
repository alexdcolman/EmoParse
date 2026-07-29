# EmoParse

> Análisis de emociones en discursos con LLMs locales.

EmoParse procesa corpus de discursos y devuelve, para cada frase, una caracterización semiótica de las emociones que la atraviesan: qué actor las experimenta, en qué modo de existencia, con qué foria, dominancia, intensidad, duración, temporalidad histórica y aspecto gramatical, y cuál es la fuente que la desencadena. Opcionalmente, realiza un análisis actancial de cada emoción (mediador, verificadores normativo y observacional, operador de modificación y polaridad —afirmación/negación de la emoción—) y homogeneiza actores y emociones para habilitar el análisis agregado del corpus.

Además del discurso tradicional (discursos presidenciales, políticos, institucionales), EmoParse analiza **discurso nativo digital**: el género `tuit` trata cada post como enunciado compuesto (texto + hashtags + menciones + emojis + tecnografismos + imágenes), preserva la estructura conversacional (hilos, citas, reposts) y agrega análisis de redes de interacción con acoplamiento emocional. Ver [Género tuit](#género-tuit-discurso-nativo-digital).

Está pensado para investigadores en lingüística, semiótica, ciencias del lenguaje y análisis del discurso que necesitan procesar corpus extensos sin renunciar a la trazabilidad ni al marco teórico.

- **Reproducible**: una base SQLite por run, versionado fino de prompts y ontologías, seed fija.
- **Trazable**: cada emoción detectada lleva su justificación textual y queda enlazada a la frase original.
- **Local-first**: corre con modelos GGUF locales (llama.cpp) o vía LM Studio. La arquitectura admite además backends de API (OpenAI, Anthropic, etc.) — ver la documentación.
- **Extensible**: pipeline organizado como DAG declarativo; sumar géneros, sources de scraping o agentes es código aislado.

---

> 📖 **[Documentación completa →](https://alexdcolman.github.io/EmoParse/)**

---

## Requisitos

- Python 3.11+
- git
- GPU recomendada (NVIDIA con CUDA, AMD con ROCm) para correr modelos GGUF localmente.

---

## Instalación

```bash
git clone https://github.com/alexdcolman/EmoParse.git
cd EmoParse

python -m venv .venv
source .venv/bin/activate   # Linux/macOS
# .venv\Scripts\activate    # Windows

# Instalación con backend local + dashboard + scraping
pip install -e ".[llamacpp,ui,scraping]"
```

Los extras disponibles son `llamacpp`, `lmstudio`, `ui`, `nlp`, `scraping`, `scraping_selenium`, `bluesky` (adquisición de posts vía AT Protocol; Mastodon no requiere extra), `techno` (parsing de emojis con secuencias ZWJ), `network` (análisis de redes), `embeddings` (agrupamiento semántico de textos vía sentence-transformers), `analytics` (DuckDB sobre la SQLite del run), `agents`, `data`, `utils`, `dev` y `all`. Ver el detalle en la documentación.

La etapa `modalidad` usa spaCy (extra `nlp`) y un modelo en español; instalalo una vez con:

```bash
pip install -e ".[nlp]"
python -m spacy download es_core_news_md
```

> Una imagen Docker oficial está en preparación.

---

## Quickstart

```bash
# 1. Copiar el config de ejemplo y ajustarlo
cp config.example.yaml config.yaml

# 2. Bajar al menos un modelo GGUF a models/
#    (ver la documentación para recomendaciones)

# 3. Correr el pipeline sobre un CSV de discursos
emoparse run \
  --config config.yaml \
  --input  data/discursos.csv \
  --run-id mi_run

# 4. Explorar resultados
streamlit run src/emoparse/app/__main__.py
```

El input mínimo es un CSV con columnas `codigo` (identificador único) y `contenido` (texto). EmoParse también incluye un scraper para Casa Rosada:

```bash
emoparse scrape --source casarosada \
  --out data/discursos.csv \
  --from 2024-01-01 --to 2024-12-31
```

---

## Comandos disponibles

```
emoparse app         Abre la aplicación de Streamlit para revisión y visualización
emoparse run         Ejecuta el pipeline completo
emoparse scrape      Scrapea discursos desde una source registrada
emoparse acquire     Adquiere posts (Bluesky, Mastodon, dumps JSONL/CSV) a un corpus incremental
emoparse follows     Adquiere el grafo de seguimiento entre las cuentas del corpus (grafo 'follow')
emoparse network     Construye y analiza las redes de un run (interacción, similitud, semántica)
emoparse eval        Evaluación de validez: golden sets, acuerdo inter-anotador, controles
emoparse status      Resumen pending/failed/completed por stage
emoparse inspect     Estado completo de un discurso particular
emoparse retry       Limpia errores para reintentar (modo legacy o policy YAML)
emoparse validate    Corre los domain validators sobre las emociones
emoparse modalidad   Clasifica la modalidad referencial de los vínculos (NLP-only)
emoparse semas       Mantenimiento de semas de referentes canónicos (reset)
emoparse judge       Resumen de veredictos del LLM-as-judge
emoparse metrics     Métricas persistidas por stage
emoparse stats       Estadísticas del cache LLM
emoparse export      Exporta las tablas a CSV
```

Todos aceptan `--help`. Ejemplo:

```bash
emoparse run --help
```

---

## Foco de análisis, referentes y deixis

Por defecto `emoparse run` detecta emociones de todos los experienciadores. Para acotar el análisis a ciertos roles, `run` acepta `--enunciador`, `--enunciatarios` y `--actores` (combinables): si se pasa alguno, solo se analizan las emociones de esos experienciadores, en ambos pases de detección.

Las marcas discursivas de actores, experienciadores y fuentes se agrupan en una base de menciones y se vinculan a **referentes canónicos**. El agrupamiento es automático (correferencia léxica conservadora) y los canónicos se construyen descartando artículos y prefiriendo la inferencia dominante del LLM. La revisión humana —agrupar, aceptar, reasignar, mergear canónicos, dar de alta/baja, asignar semas— vive en la tab **Referentes** del dashboard. Una emoción nunca agrupa dos o más experienciadores: si más de un actor la experimenta, se desdobla en una emoción por experienciador, cada una con su propio modo de existencia (el enunciador puede sentirla como realizada y proyectarla al auditorio como potencial). El desdoblamiento opera en tres niveles: en los prompts, como respaldo determinista al materializar las emociones —donde resuelve las anáforas posesivas ("Carlitos y su círculo cercano" → dos referentes) y fija el referente por emoción cuando la marca compartida no los distingue, sin pisar la revisión humana—, y en la revisión. La **fuente**, en cambio, puede combinar entidades sin multiplicar simulacros: "libertarios, radicales y macristas" desencadena una sola indignación, con sus tres referentes resueltos juntos. Esa resolución —un experienciador, una o más fuentes— vive en un solo módulo que comparten el pipeline, el dashboard y el export, de modo que ninguna vista muestre dos referentes donde el modelo de datos define uno. Los campos de inferencia que devuelve el modelo se sanean antes de persistir: una sola categoría por campo, sin sinónimos, enumeraciones ni restos tipográficos, y las etiquetas de rol enunciativo ("el enunciador") se resuelven al referente que ocupa esa posición.

Para revisar a escala, la tab **Referentes** incluye **acciones masivas** (aceptar/rechazar en lote filtrando por estado, modalidad, función —con selección negativa "no es actor"— y referentes a incluir/excluir) y **fusiones sugeridas**: un detector escalable de referentes casi-duplicados (blocking + similitud léxica, y opcionalmente semántica por embeddings de spaCy) que propone grupos para fusionar con revisión humana, sin pasar toda la base por un LLM.

La etapa `enunciation` resuelve el enunciador antes del análisis principal: en géneros clásicos, un sub-paso con prompt mínimo (`enunciator_id`, configurable con un modelo chico) devuelve su denominación normalizada ("el presidente Javier Milei" → "Javier Milei"); en el género `tuit` el enunciador es la cuenta autora del post, sin inferencia. Con el enunciador fijado, el prompt principal solo identifica enunciatarios, auditorio y colectivos de identificación, siempre como referentes concretos y nunca como etiquetas de rol; los roles con que se tipa a cada enunciatario dependen del tipo de discurso que resolvió `metadata` (la destinación propia del tipo más las posiciones transversales del dispositivo). En los destinatarios que se ordenan alrededor de creencias y valores (pro-, para- y contradestinatario) esto se refuerza con un filtro: se descarta la audiencia nombrada solo por el dispositivo ("seguidores de la cuenta", "los usuarios") sin una posición que la califique, porque ya se registra como auditorio y audiencia ambiente. Una base persistida (`knowledge/enunciacion_kb.json`) acumula el repertorio conocido de cada enunciador —se promueve desde la tab **Enunciación**— y entra como contexto en corridas futuras, con libertad del modelo para proponer identificaciones nuevas.

La etapa opcional `deixis` (se corre con `--stages …,deixis`, luego de `enunciation` y `emotions`) resuelve las marcas deícticas de 1ª y 2ª persona ("yo", "nosotros", "veamos"…) a los referentes concretos del discurso: el **enunciador**, el **auditorio** (destinatario directo) o los **colectivos de identificación** del enunciador, todos identificados por `enunciation`. La asignación puede ser múltiple (p. ej. "nosotros" → el enunciador y su colectivo). Sus sugerencias se revisan en la tab **Deixis**, que las inscribe en la marca sin decidir por sí sola: como una marca pertenece a toda la unidad, qué referente rige cada simulacro se decide **por emoción y por rol**, entre reemplazar el que estaba o añadir el nuevo (añadir desdobla la emoción si es el experienciador, y suma si es la fuente). La tab muestra los simulacros donde interviene la marca para elegir sobre cada uno, con selector de modo de existencia —una emoción atribuida al auditorio se propone como potencial— y permite eliminar los que sobren.

La etapa opcional `modalidad` clasifica **cómo** cada marca refiere a su referente, en dos ejes: la **modalidad referencial** —`designacion` (lo nombra/categoriza: "Javier Milei", "el presidente"), `referencia_gramatical` (deixis/morfología: "yo", "he defendido") o `identificacion_inferencial` (se identifica por la actitud/valores: "ellos son la casta corrupta" identifica al enunciador)— y la **naturaleza** del referente (persona, colectivo, institución, objeto/proceso). Es un **híbrido NLP+LLM**: un pre-pass con spaCy resuelve los casos claros y el LLM interviene solo en los ambiguos. Así se puede **aceptar** un vínculo (sin perder el experienciador) y a la vez **separar** las designaciones para estudiar la construcción de objetos de discurso. Se corre con LLM vía `emoparse run --stages …,modalidad`, o **NLP-only** post-hoc con `emoparse modalidad --db <db>` (requiere spaCy y un modelo ES, p. ej. `python -m spacy download es_core_news_md`). En la tab **Referentes** cada marca muestra su modalidad/naturaleza, se puede filtrar por modalidad y corregirla a mano.

Cuando una frase tiene **varias emociones que comparten la marca de experienciador**, la tab **Referentes** permite **atribuir el experienciador —o la fuente— por emoción**: al pasar el cursor por la frase de una marca se ven sus emociones con experienciador, tipo, **modo de existencia** y fuente, y se puede fijar el experienciador (o la fuente) de una emoción puntual sin arrastrar las demás (p. ej. atribuir la *indignación* a un referente y dejar el *miedo* en otro). La atribución por emoción prima sobre la resolución por marca; en el caso del experienciador, además fuerza el recálculo downstream de esa emoción. Atribuir varios experienciadores desdobla la emoción; varias fuentes conviven en el mismo simulacro.

El dashboard incluye además tabs de **Búsqueda** (por texto o por selección de emoción/actor/experienciador/fuente, con contexto de frases), **Co-ocurrencia** de emociones (por frase, y por hilo o por hashtag en corpus de posts) y **Simulacros** (reconstrucción de cada emoción con sus funciones actanciales, filtrable por actantes, semas y texto).

---


## Género tuit (discurso nativo digital)

El género `tuit` adapta el marco a posts de redes sociales, donde el texto es un **tecnodiscurso**: los hashtags, menciones, emojis, alargamientos y mayúsculas no son ruido a limpiar sino materia enunciativa a analizar.

```bash
# 1. Adquirir un corpus (Bluesky o Mastodon; también importa dumps JSONL o CSV ajenos)
emoparse acquire --source bluesky --query "#tarifazo" --lang es \
    --max 500 --out data/tarifazo.jsonl

# 2. Analizarlo
emoparse run --config config.yaml --genre tuit \
    --input data/tarifazo.jsonl --run-id tarifazo01

# 3. Redes de interacción (reply, mention, rt, qt, co-ocurrencia de hashtags)
emoparse network --db runs/tarifazo01.sqlite --export-dir exports/red
```

Qué agrega el género respecto del pipeline clásico:

- **`technoparse`** (determinista, sin LLM): extrae hashtags (con función sintáctica integrada/pospuesta), @menciones (que siembran referentes canónicos con vínculo aceptado por designación), URLs, emojis y tecnografismos, con offsets, sin alterar el texto. Los @handles alimentan directamente la base de referentes.
- **Contexto conversacional**: cada post se analiza junto al post que abrió la conversación y a los posts a los que responde (con el padre inmediato marcado), además del post que cita, como contexto de desambiguación y no como fuente de emociones. El root fija de qué se habla cuando las respuestas son elípticas, a costo de un solo post cualquiera sea la profundidad del hilo. Los hilos se reconstruyen en la ingesta.
- **`reframing`**: clasifica la operación de las citas y reposts con comentario (adhesión / ironía-distancia / denuncia / difusión neutra) y el estatuto de las emociones citadas (asumidas / semiotizadas), para no atribuirle a quien denuncia la euforia que exhibe.
- **`emoji_affect`** (híbrida): un léxico curado resuelve los emojis inequívocos sin LLM; los ambiguos (😂 ¿risa o burla?) se desambiguan en contexto.
- **`hashtag_semiotics`**: analiza el funcionamiento de cada hashtag en cada post donde aparece (tópico / afiliación-consigna / evaluativo / irónico / campaña, con posibilidad de proponer funciones nuevas), con su acoplamiento y la foria de ese uso; las funciones ya identificadas del mismo hashtag entran como contexto creciente entre batches, y la caracterización a nivel corpus se deriva por agregación (función dominante o mixta más la distribución completa).
- **`tecno_usage`**: caracteriza el uso pragmático de cada @mención (interpelar, confrontar, exponer, citar, agradecer, convocar, marcar afiliación), de cada tecnografismo (énfasis, grito, ironía, celebración, risa, saturación expresiva, marca identitaria, etiqueta temática, reticencia/sugerencia, incredulidad/asombro) y de cada URL (fuente/prueba, autopromoción, convocatoria a la acción, enlace temático) en el contexto de su post.
- **Enunciación anclada al dispositivo**: el enunciador es la cuenta autora del post (funciona igual con corpus seudonimizados: el alias es estable por cuenta) y el auditorio se construye de forma determinista, sin inferencia: los seguidores de la cuenta, un auditorio por cada hashtag presente y un destinatario directo por cada cuenta mencionada. La etapa `metadata` clasifica el tipo de discurso sobre un vocabulario cerrado del género (político, periodístico-informativo, institucional, humor/meme, personal-cotidiano, promocional, otro), restringido por el schema.
- **`vision_describe`** (multimodal, opcional): describe las imágenes adjuntas con un modelo de visión (llama-server con `--mmproj`) y esa descripción entra como contexto del análisis emocional; el post se analiza como enunciado compuesto.
- **Roles enunciativos por tipo de discurso**: dos posiciones transversales del dispositivo —destinatario mencionado (interpelación técnica vía @) y audiencia ambiente (el público del archivo buscable)— se cruzan con la destinación propia de cada tipo de discurso: pro/para/contradestinatario (Verón) en el político; lector-ciudadano / instancia-blanco / fuente-referente (Charaudeau) en el periodístico-informativo; y tríadas análogas en el institucional, el humor/meme, el personal-cotidiano y el promocional. La etapa `metadata` resuelve el tipo y `enunciation` ofrece en el prompt solo los roles de ese tipo (con indicadores lingüísticos orientativos) y descarta los ajenos.
- **Redes**: `emoparse network` construye los grafos de interacción (reply, mención, RT, cita, co-hashtag), calcula métricas (PageRank, grados, intermediación), comunidades (Louvain, seed fija) y opcionalmente cliques de vínculos recíprocos, los acopla al análisis emocional (perfiles fóricos por comunidad, matrices de transición fórica padre→respuesta, y con `--flujo` el contagio por tipo de emoción y la transición fórica partida intra/inter comunidad) y exporta GEXF para Gephi. Con `--similitud` agrupa los simulacros emocionales por parecido entre sus componentes (agrupamiento narrativo) y con `--semantico` agrupa los posts por contenido (extra `embeddings`); ambos análisis valen para cualquier género, así que la tab Red y estos agrupamientos también sirven para corpus de discursos, no solo de posts. `emoparse follows` adquiere aparte el grafo de seguimiento entre las cuentas del corpus y lo deja medido como un grafo más.
- **Dashboard**: cuando el run contiene posts, aparecen las tabs 🧵 Hilos (árbol conversacional con foria por post), 🕸 Red, #️⃣ Hashtags (distribución de funciones por hashtag y drill-down por uso) y ✳ Tecno (usos en contexto de menciones, tecnografismos y links, y frases por emoji). La tab 🕸 Red aparece también en corpus de discursos si se corrieron los agrupamientos de similitud o semántico. Una sección **⚙ Ejecutar**, hermana de Resultados, arma los comandos de CLI desde controles para copiar y pegar (no ejecuta: el pipeline corre en CLI); además, la curva emocional se ve por defecto como evolución de la conversación pública (por hashtag o por hilo), la co-ocurrencia y la timeline se filtran por hilo o hashtag, y la revisión muestra cada post con sus tecnolingüísticos y su media.
- **Ontología ampliada**: emociones del discurso político en redes (burla, hartazgo, vergüenza ajena, diversión) restringidas por género sobre una base compartida.

La adquisición respeta los términos de cada plataforma e incluye seudonimización opcional (`--pseudonymize`) con alias estables que preservan la estructura de hilos y redes. Ver `src/emoparse/acquisition/README.md` para las consideraciones éticas.

## Evaluación de validez

`emoparse eval` implementa el circuito de validación: exportar una muestra estratificada para **anotación humana a ciegas** (`--make-sample`), calcular el **acuerdo inter-anotador** con alpha de Krippendorff (`--agreement`, implementación propia verificada contra los valores publicados), construir un **golden set** de regresión y comparar cada run contra él (`--golden`: precisión/recall/F1 de detección + accuracy por dimensión), y medir la **sobre-detección** sobre corpus de control sin carga emocional (`--control`). El manual de anotación vive en `evals/manual_anotacion.md`; el protocolo convierte cada cambio de prompt u ontología en un experimento medible.

---

## Estado del proyecto

EmoParse está en **beta**. La arquitectura es estable; las ontologías y heurísticas semióticas (en `knowledge/`) se siguen refinando. Reportes de issues y pull requests son bienvenidos.

---

## Licencia

[MIT](https://github.com/alexdcolman/EmoParse/blob/main/LICENSE).

Si lo usás en una publicación académica, una referencia al repositorio es bienvenida y ayuda a sostener el proyecto.

---

## Autoría

Este proyecto fue desarrollado en el marco de una investigación sobre análisis automático de emociones en discursos por:

- **[Alex Colman](https://independent.academia.edu/AlexColman1)**

Para dudas o colaboraciones, podés contactarme vía GitHub o correo: alexdcolman@gmail.com

---

## Agradecimientos

Agradezco especialmente a [Mathi Gatti](https://mathigatti.com/) y a [Martín Schuster](https://www.flacso.org.ar/docentes/schuster-martin-ivan/) por la orientación en el desarrollo del proyecto.

[Laura Bonilla](https://www.researchgate.net/profile/Laura-Bonilla-Neira) me está ayudando a desarrollar la adaptación de EmoParse para análisis de tuits (género `tuit`).

---

## ¿Querés colaborar?

Pull requests, issues o sugerencias son bienvenidas.
