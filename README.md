# EmoParse

> Análisis de emociones en discursos con LLMs locales.

EmoParse procesa corpus de discursos y devuelve, para cada frase, una caracterización semiótica de las emociones que la atraviesan: qué actor las experimenta, en qué modo de existencia, con qué foria, dominancia, intensidad, duración, temporalidad histórica y aspecto gramatical, y cuál es la fuente que la desencadena. Opcionalmente, realiza un análisis actancial de cada emoción (mediador, verificadores normativo y observacional, operador de modificación y polaridad —afirmación/negación de la emoción—) y homogeneiza actores y emociones para habilitar el análisis agregado del corpus.

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

Los extras disponibles son `llamacpp`, `lmstudio`, `ui`, `nlp`, `scraping`, `scraping_selenium`, `agents`, `data`, `utils`, `dev` y `all`. Ver el detalle en la documentación.

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

Las marcas discursivas de actores, experienciadores y fuentes se agrupan en una base de menciones y se vinculan a **referentes canónicos**. El agrupamiento es automático (correferencia léxica conservadora) y los canónicos se construyen descartando artículos y prefiriendo la inferencia dominante del LLM. La revisión humana —agrupar, aceptar, reasignar, mergear canónicos, dar de alta/baja, asignar semas— vive en la tab **Referentes** del dashboard. La detección (`actors`, `emotions`, `emotions_pass2`) identifica **una entidad por rol** y parte las enumeraciones ("los colectivistas y los socialistas" → dos fuentes), lo que reduce los referentes-conjunción.

Para revisar a escala, la tab **Referentes** incluye **acciones masivas** (aceptar/rechazar en lote filtrando por estado, modalidad, función —con selección negativa "no es actor"— y referentes a incluir/excluir) y **fusiones sugeridas**: un detector escalable de referentes casi-duplicados (blocking + similitud léxica, y opcionalmente semántica por embeddings de spaCy) que propone grupos para fusionar con revisión humana, sin pasar toda la base por un LLM.

La etapa opcional `deixis` (se corre con `--stages …,deixis`, luego de `enunciation` y `emotions`) resuelve las marcas deícticas de 1ª y 2ª persona ("yo", "nosotros", "veamos"…) a los referentes concretos del discurso: el **enunciador**, el **auditorio** (destinatario directo) o los **colectivos de identificación** del enunciador, todos identificados por `enunciation`. La asignación puede ser múltiple (p. ej. "nosotros" → el enunciador y su colectivo). Sus sugerencias se revisan en la tab **Deixis**: al aceptarlas, la marca queda inscripta en el referente concreto (p. ej. "yo" → *Javier Milei*) y se sobreescribe el canónico que el modelo había inventado.

La etapa opcional `modalidad` clasifica **cómo** cada marca refiere a su referente, en dos ejes: la **modalidad referencial** —`designacion` (lo nombra/categoriza: "Javier Milei", "el presidente"), `referencia_gramatical` (deixis/morfología: "yo", "he defendido") o `identificacion_inferencial` (se identifica por la actitud/valores: "ellos son la casta corrupta" identifica al enunciador)— y la **naturaleza** del referente (persona, colectivo, institución, objeto/proceso). Es un **híbrido NLP+LLM**: un pre-pass con spaCy resuelve los casos claros y el LLM interviene solo en los ambiguos. Así se puede **aceptar** un vínculo (sin perder el experienciador) y a la vez **separar** las designaciones para estudiar la construcción de objetos de discurso. Se corre con LLM vía `emoparse run --stages …,modalidad`, o **NLP-only** post-hoc con `emoparse modalidad --db <db>` (requiere spaCy y un modelo ES, p. ej. `python -m spacy download es_core_news_md`). En la tab **Referentes** cada marca muestra su modalidad/naturaleza, se puede filtrar por modalidad y corregirla a mano.

Cuando una frase tiene **varias emociones que comparten la marca de experienciador**, la tab **Referentes** permite **atribuir el experienciador —o la fuente— por emoción**: al pasar el cursor por la frase de una marca se ven sus emociones con experienciador, tipo, **modo de existencia** y fuente, y se puede fijar el experienciador (o la fuente) de una emoción puntual sin arrastrar las demás (p. ej. atribuir la *indignación* a un referente y dejar el *miedo* en otro). La atribución por emoción prima sobre la resolución por marca; en el caso del experienciador, además fuerza el recálculo downstream de esa emoción.

El dashboard incluye además tabs de **Búsqueda** (por texto o por selección de emoción/actor/experienciador/fuente, con contexto de frases), **Co-ocurrencia** de emociones por frase y **Simulacros** (reconstrucción de cada emoción con sus funciones actanciales, filtrable por actantes, semas y texto).

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

[Laura Bonilla](https://www.researchgate.net/profile/Laura-Bonilla-Neira) me está ayudando a desarrollar una adaptación de EmoParse para análisis de tuits.

---

## ¿Querés colaborar?

Pull requests, issues o sugerencias son bienvenidas.
