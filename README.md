# EmoParse

**Sistema modular para el análisis automático de emociones en discursos**

EmoParse es una arquitectura automatizada que integra herramientas de procesamiento de lenguaje natural, modelos de lenguaje de gran escala (LLMs) y reglas semióticas para detectar, caracterizar y visualizar emociones discursivas. Está diseñado para facilitar el análisis crítico de textos, tanto desde la perspectiva retórica como enunciativa y afectiva.

## Propósito

Este sistema busca automatizar el análisis emocional de discursos complejos, respetando las especificidades del lenguaje, el contexto y los modos en que se inscriben las emociones. Su modularidad permite adaptarlo a diferentes tipos de texto y expandirlo progresivamente. Pretende ser un aporte metodológico para investigaciones en ciencias sociales, análisis del discurso, estudios emocionales y lingüística computacional.

---

## Arquitectura modular

EmoParse está organizado como una cadena de módulos funcionales. Cada módulo opera de forma autónoma, pero está integrado dentro de una pipeline general documentada y reproducible:

### 1. Recolección de discursos (`webscraping.py`)
- Descarga discursos desde sitios web estructurados.
- Genera una base con metadatos como autor, fecha, medio, etc.

### 2. Preprocesamiento lingüístico (`preprocesamiento.py`)
- Limpieza, segmentación y análisis gramatical (POS, lemas, dependencias).
- Extracción de entidades y sujetos implícitos.
- Identificación de nominalizaciones y otros recursos.

### 3. Resumen contextual inteligente (`resumen.py`)
- Resumen global y por secciones mediante LLM.
- Proporciona contexto clave para análisis enunciativo y emocional.

### 4. Identificación de actores discursivos (`identificacion_actores.py`)
- Usa LLM para detectar enunciador, enunciatarios y actores representados.
- Clasifica roles enunciativos por frase.
- Aplica reglas discursivas (e.g., triple destinación de Verón).

### 5. Detección de emociones (`emociones.py`, en desarrollo)
- Clasifica emociones **dichas, mostradas, sostenidas e inducidas**.
- Asocia emociones a actores específicos.
- Identifica efectos emocionales sobre el destinatario.

### 6. Caracterización emocional (`emociones.py`)
- Atributos (MVP): foria (tonalidad), dominancia, intensidad, fuente.
- Expandible a otros atributos.
- Categorización computacional basada en inferencias semióticas.

### 7. Verificación y control de coherencia (`postprocesamiento.py`)
- Cruza resultados con diccionarios de compatibilidades.
- Genera alertas ante contradicciones semánticas o estructurales.

### 8. Historial de decisiones
- Registro transparente del camino de clasificación por frase.

### 9. Exportación y análisis
- Base final con una línea por emoción, frase y actor.
- Estructura lista para análisis cuantitativo o visualización.

### 10. Visualización temporal del discurso
- Curvas emocionales frase a frase.
- Seguimiento de la evolución afectiva del enunciador, destinatario y actores.

---

## 🛠️ Estado actual

Actualmente se encuentran optimizadas las funciones de:

- Identificación de actores y tipos de discurso.
- Posprocesamiento y validación de resultados.

Próximamente se implementarán las funciones específicas del módulo `emociones.py` para detección y caracterización completa.

---

## Estructura del proyecto

```bash
EmoParse/
│
├── main.ipynb # Notebook principal de ejecución
├── inicio.bat # Inicia entorno desde CMD o Anaconda Prompt
├── requirements.txt # Librerías necesarias
├── readme.md # Este archivo
├── arquitectura_modular.md # Detalle de cada módulo
├── marco_teorico.md # (Próximamente)
│
├── data/ # CSVs con datos procesados
├── errores/ # Registro de errores
├── logs/ # Logs de ejecución (Próximamente)
├── modulos/ # Módulos funcionales
│ ├── init.py
│ ├── prompts.py
│ ├── ontologia.py
│ ├── diccionario_conceptual.py
│ ├── heuristicas.py
│ ├── paths.py
│ ├── modelo.py
│ ├── recursos.py
│ ├── webscraping.py
│ ├── preprocesamiento.py
│ ├── resumen.py
│ ├── extraer_fragmentos.py
│ ├── metadatos.py
│ ├── enunciacion.py
│ ├── identificacion_actores.py
│ ├── reprocesamiento.py
│ ├── postprocesamiento.py
│ ├── diccionario_compatibilidades.py # (Próximamente)
│ └── emociones.py # (Próximamente)

```
---

## Ejecución recomendada

```bash
# 1. Crear entorno con Python 3.10
conda create -n ag_env2 python=3.10

# 2. Activar entorno
conda activate ag_env2

# 3. Instalar dependencias
pip install -r requirements.txt

# 4. Descargar recursos adicionales
python -m nltk.downloader punkt
python -m nltk.downloader averaged_perceptron_tagger
python -m nltk.downloader stopwords
python -m nltk.downloader wordnet
python -m nltk.downloader omw-1.4
python -m spacy download es_core_news_sm
python -m spacy download es_core_news_md
python -m stanza.download es

# 5. (Opcional) Instalar JupyterLab
conda install -y jupyterlab

# 6. Lanzar JupyterLab
jupyter lab

```

**Nota:** actualmente requiere instalación de Ollama y download de LLMs (Mistral, Gemma, etc.).

## Módulos destacados y funciones clave

**Webscraping (scrap_discursos)**

- Scrapea discursos desde webs paginadas.
- Devuelve DataFrame con título, fecha, contenido, etc.

**Preprocesamiento (generar_recortes, filtrar_discursos, procesar_textos)**

- Genera frases por discurso.
- Filtra discursos con pocas frases.
- Procesa morfosintácticamente los textos.

**Resumen (resumir_dataframe)**

- Segmenta discursos en fragmentos temáticos.
- Resume con LLM fragmentos y luego redacción global.

**Identificación enunciativa (procesar_discursos_llm)**

- Detecta tipo de discurso, enunciador, enunciatarios y lugar.
- Usa prompts y un diccionario conceptual.

**Actores por contexto (identificar_actores_con_contexto)**

- Detecta actores implícitos y explícitos por frase.
- Cruza contexto global, ontología y heurísticas.
- Usa LLM (por defecto, Mistral vía Ollama, pero extensible a OpenAI).

## ¿Qué aporta EmoParse?

- Un enfoque computacional sensible al lenguaje, no reduccionista.
- Una arquitectura extensible para combinar LLMs con reglas semióticas.
- Un modelo reproducible para análisis retórico y emocional de discursos.
- Un sistema que visibiliza relaciones afectivas y enunciativas complejas en los textos.

## Futuras implementaciones

- Identificación de escenas enunciativas y géneros discursivos.
- Incorporación de emociones compuestas y dinámicas afectivas.
- Generación automática de informes emocionales comparativos.

## Licencia

Este proyecto se publica bajo la licencia GNU GENERAL PUBLIC LICENSE Version 3, 29 June 2007. Podés reutilizar y modificar el código citando adecuadamente.

## Autoría

Este proyecto fue desarrollado en el marco de una investigación sobre análisis automático de emociones en discursos por:

- **[Alex Colman](https://independent.academia.edu/AlexColman1)**

Para dudas o colaboraciones, podés contactarme vía GitHub o correo:
alexdcolman@gmail.com

## Agradecimientos

Agradezco especialmente a [Mathi Gatti](https://mathigatti.com/) y a [Martín Schuster](https://www.flacso.org.ar/docentes/schuster-martin-ivan/) por la orientación en el desarrollo del proyecto.

## ¿Querés colaborar?

Pull requests, issues o sugerencias son bienvenidas.
