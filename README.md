# EmoParse

**Sistema modular para el análisis automático de emociones en discursos**

EmoParse es una arquitectura automatizada que integra herramientas de procesamiento de lenguaje natural, modelos de lenguaje de gran escala (LLMs) y reglas semióticas para detectar, caracterizar y visualizar emociones discursivas. Está diseñado para facilitar el análisis crítico de textos, tanto desde la perspectiva retórica como enunciativa y afectiva.

## Propósito

Este sistema busca automatizar el análisis emocional de discursos complejos, respetando las especificidades del lenguaje, el contexto y los modos en que se inscriben las emociones. Su modularidad permite adaptarlo a diferentes tipos de texto y expandirlo progresivamente. Pretende ser un aporte metodológico para investigaciones en análisis del discurso, ciencias sociales, estudios emocionales y lingüística computacional.

---

## Arquitectura modular

EmoParse está organizado como una cadena de módulos funcionales. Cada módulo opera de forma autónoma, pero está integrado dentro de una [pipeline general](https://github.com/alexdcolman/EmoParse/blob/main/main.ipynb) documentada y reproducible (aún en fase de prueba de módulos):

### 1. Recolección de discursos ([`webscraping.py`](https://github.com/alexdcolman/EmoParse/blob/main/modulos/webscraping.py))
- Descarga discursos desde sitios web estructurados.
- Genera una base con metadatos como autor, fecha, medio, etc.

### 2. Preprocesamiento lingüístico ([`preprocesamiento.py`](https://github.com/alexdcolman/EmoParse/blob/main/modulos/preprocesamiento.py))
- Limpieza, segmentación y análisis gramatical (POS, lemas, dependencias).
- Extracción de entidades y sujetos implícitos.
- Identificación de nominalizaciones y otros recursos.

### 3. Resumen contextual inteligente ([`resumen.py`](https://github.com/alexdcolman/EmoParse/blob/main/modulos/resumen.py))
- Resumen global y por secciones mediante LLM.
- Proporciona contexto clave para análisis enunciativo y emocional.

### 4. Identificación de metadatos () y enunciación ()
- Módulos que identifican tipo de discurso, lugar, enunciador y enunciatarios usando LLMs y diccionarios conceptuales.

### 5. Identificación de actores discursivos ([`identificacion_actores.py`](https://github.com/alexdcolman/EmoParse/blob/main/modulos/identificacion_actores.py))
- Usa LLM para detectar actores explícitos o inferibles por frase.

### 6. Detección de emociones (`deteccion_emociones.py`, en desarrollo)
- Clasifica emociones **dichas, mostradas, sostenidas e inducidas**.
- Asocia emociones a actores específicos.
- Identifica efectos emocionales sobre el destinatario.

### 7. Caracterización emocional (`caracterizacion_emociones.py`, en desarrollo)
- Atributos (MVP): foria (tonalidad), dominancia, intensidad, fuente.
- Expandible a otros atributos.
- Categorización computacional basada en inferencias semióticas.

### 8. Verificación y control de coherencia (`verificacion.py`, en desarrollo)
- Cruza resultados con diccionarios de compatibilidades.
- Genera alertas ante contradicciones semánticas o estructurales.

### 9. Historial de decisiones
- Registro transparente del camino de clasificación por frase.

### 10. Exportación y análisis
- Base final con una línea por emoción, frase y actor.
- Estructura lista para análisis cuantitativo o visualización.

### 11. Visualización temporal del discurso
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
├── ini.bat # Inicia entorno desde CMD o Anaconda Prompt
├── requirements.txt # Librerías necesarias
├── README.md # Este archivo
├── arquitectura_modular.md # Detalle de cada módulo
├── marco_teorico.md # (Próximamente)
│
├── data/ # CSVs con datos procesados
├── errors/ # Registro de errores
├── logs/ # Logs de ejecución
├── modulos/ # Módulos funcionales
│ ├── init.py
│ ├── diccionario_compatibilidades.py # (Próximamente)
│ ├── diccionario_conceptual.py # (Próximamente)
│ ├── driver_utils.py
│ ├── emociones.py # (Próximamente)
│ ├── extraccion_fragmentos.py
│ ├── identificacion_actores
│ ├── metadatos
│ ├── modelo
│ ├── parsers
│ ├── paths
│ ├── postprocesamiento_actores
│ ├── preprocesamiento
│ ├── prompts
│ ├── recursos
│ ├── reprocesamiento
│ └── resumen
│ └── schemas
│ └── scraping_utils
│ └── tipos_discurso
│ └── utils_io
│ └── webscraping

```
---

## Ejecución recomendada

### Automática

1. **Crear entorno con Python 3.10**
```bash
conda create -n ag_env2 python=3.10
```
2. **Correr el archivo `ini.bat`**
```bash
ini
```

### Manual

1. **Crear entorno con Python 3.10**  
```bash
conda create -n ag_env2 python=3.10
```
2. **Activar el entorno**
```bash
conda activate ag_env2
```
3. **Instalar pip**
```bash
conda install pip
```
4. **Instalar PyTorch con CUDA (cu118) desde el índice oficial de PyTorc**
```bash
pip install torch==2.1.0+cu118 torchvision==0.16.0+cu118 torchaudio==2.1.0+cu118 -f https://download.pytorch.org/whl/torch_stable.html
```
5. **Instalar todo desde requirements.txt con pip**
```bash
pip install -r requirements.txt
```
6. **Instalar stanza**
```bash
pip install stanza
```
7. **Descargar recursos adicionales necesarios**
```bash
python -m nltk.downloader punkt
python -m nltk.downloader averaged_perceptron_tagger
python -m nltk.downloader stopwords
python -m nltk.downloader wordnet
python -m nltk.downloader omw-1.4
```
8. **Descargar modelos de procesamiento de lenguaje**
```bash
python -m spacy download es_core_news_sm
python -m spacy download es_core_news_md
python -m stanza.download es
```
9. **(Opcional) Instalar jupyterlab para trabajar en notebooks**
```bash
conda install -y jupyterlab
```
10. **Lanzar Jupyter Lab**
```bash
jupyter lab
```

**Nota:** actualmente requiere instalación de [Ollama](https://ollama.com/download) y download de LLMs (GPT-OSS:20b, Mistral, etc.).

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

**Metadatos (procesar_metadatos_llm)** y **Enunciación (procesar_enunciacion_llm)**

- Detectan tipo de discurso, enunciador, enunciatarios y lugar.
- Usan [prompts](https://github.com/alexdcolman/EmoParse/blob/main/modulos/prompts.py) y un [diccionario conceptual](https://github.com/alexdcolman/EmoParse/blob/main/modulos/tipos_discurso.py).

**Actores por contexto (identificar_actores_con_contexto)**

- Detecta actores implícitos y explícitos por frase.
- Cruza contexto global, [ontología](https://github.com/alexdcolman/EmoParse/blob/main/modulos/ontologia/actores.json) y [heurísticas](https://github.com/alexdcolman/EmoParse/blob/main/modulos/heuristicas/inferencia_actores.txt).
- Usa LLM (por defecto, Mistral vía Ollama, pero extensible a OpenAI).

**Reprocesamiento (reprocesar_errores_metadatos, reprocesar_enunciacion, reprocesar_errores_identificacion)** y **Postprocesamiento (propagar_actores_por_pronombres, validacion_actores)**

- Funciones de reprocesamiento y validación que aseguran consistencia y completitud de los resultados.

## ¿Qué aporta EmoParse?

- Un enfoque computacional sensible al lenguaje, no reduccionista.
- Una arquitectura extensible para combinar LLMs con reglas semióticas.
- Un modelo reproducible para análisis retórico y emocional de discursos.
- Un sistema que visibiliza relaciones afectivas y enunciativas complejas en los textos.

## Futuras implementaciones

- Identificación de escenas enunciativas y géneros discursivos.
- Incorporación de emociones compuestas, dinámicas afectivas y diferentes atributos (ver [Diccionario de variables](https://github.com/alexdcolman/cartografia-afectiva/blob/main/diccionario_variables.md)).
- Generación automática de informes emocionales comparativos.
- Puede ampliarse a otros corpus, análisis de emociones y estudios comparativos de dinámicas discursivas.

## Limitaciones

- Dependencia de calidad de prompts y cobertura del modelo.  
- Requiere revisión manual para corroborar resultados.  
- Consumo elevado de recursos y tiempos de cómputo intensos para identificación de actores por frase.  

## Licencia

Este proyecto se publica bajo la [licencia GNU GENERAL PUBLIC LICENSE Version 3, 29 June 2007](https://github.com/alexdcolman/EmoParse/blob/main/LICENSE). Podés reutilizar y modificar el código citando adecuadamente.

## Autoría

Este proyecto fue desarrollado en el marco de una investigación sobre análisis automático de emociones en discursos por:

- **[Alex Colman](https://independent.academia.edu/AlexColman1)**

Para dudas o colaboraciones, podés contactarme vía GitHub o correo:
alexdcolman@gmail.com

## Agradecimientos

Agradezco especialmente a [Martín Schuster](https://www.flacso.org.ar/docentes/schuster-martin-ivan/) y a [Mathi Gatti](https://mathigatti.com/) por la orientación en el desarrollo del proyecto.

## ¿Querés colaborar?

Pull requests, issues o sugerencias son bienvenidas.
