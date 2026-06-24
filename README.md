# EmoParse

> Análisis de emociones en discursos con LLMs locales.

EmoParse procesa corpus de discursos y devuelve, para cada frase, una caracterización semiótica de las emociones que la atraviesan: qué actor las experimenta, en qué modo de existencia, con qué foria, dominancia, intensidad y cuál es la fuente que la desencadena. Opcionalmente, realiza un análisis actancial de cada emoción (mediador, verificadores normativo y observacional, operador de modificación) y homogeneiza actores y emociones para habilitar el análisis agregado del corpus.

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

Las marcas discursivas de actores, experienciadores y fuentes se agrupan en una base de menciones y se vinculan a **referentes canónicos**. El agrupamiento es automático (correferencia léxica conservadora) y los canónicos se construyen descartando artículos y prefiriendo la inferencia dominante del LLM. La revisión humana —agrupar, aceptar, reasignar, mergear canónicos, dar de alta/baja, asignar semas— vive en la tab **Referentes** del dashboard.

La etapa opcional `deixis` (se corre con `--stages …,deixis`, luego de `enunciation` y `emotions`) resuelve las marcas deícticas de 1ª y 2ª persona ("yo", "nosotros", "veamos"…) a los referentes concretos del discurso: el **enunciador**, el **auditorio** (destinatario directo) o los **colectivos de identificación** del enunciador, todos identificados por `enunciation`. La asignación puede ser múltiple (p. ej. "nosotros" → el enunciador y su colectivo). Sus sugerencias se revisan en la tab **Deixis**: al aceptarlas, la marca queda inscripta en el referente concreto (p. ej. "yo" → *Javier Milei*) y se sobreescribe el canónico que el modelo había inventado.

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
