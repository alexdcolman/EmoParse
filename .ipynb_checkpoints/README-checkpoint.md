# Hacia el análisis automático de emociones en discursos políticos: web scraping, NLP y extracción de actores mediante LLMs

**Estudiante:** Alex Colman  
**Curso:** Webscraping, NLP e introducción a LLM  
**Fecha:** 27 de agosto de 2025  

## Descripción
Este paquete es un pipeline modular para facilitar el análisis automático de discursos políticos. Combina web scraping, procesamiento de lenguaje natural (NLP) y modelos de lenguaje de gran escala (LLMs) para:

- Recolectar discursos desde sitios web paginados.  
- Preprocesar y segmentar los textos en frases.  
- Generar resúmenes automáticos por discurso y por fragmento.  
- Identificar metadatos enunciativos (tipo de discurso, enunciador, enunciatarios, lugar).  
- Detectar actores mencionados o inferidos en cada frase con justificación.  

El sistema es reproducible, escalable y adaptable a otros tipos de discursos o análisis de emociones.

## Estructura del pipeline

1. **Web scraping:** `scrap_discursos` recolecta discursos completos, guardando título, fecha y contenido en un DataFrame.  
2. **Preprocesamiento:** `generar_recortes`, `filtrar_discursos` y `procesar_textos` permiten segmentar en frases, limpiar y enriquecer los textos con NLP (tokenización, lematización, POS, entidades).  
3. **Resúmenes automáticos:** `resumir_dataframe` usa LLMs para generar resúmenes parciales y globales, segmentando discursos por cambios temáticos.  
4. **Metadatos y enunciación:** `procesar_metadatos_llm` y `procesar_enunciacion_llm` identifican tipo de discurso, lugar, enunciador y enunciatarios usando LLMs y diccionarios conceptuales.  
5. **Identificación de actores:** `identificar_actores_con_contexto` analiza frase por frase, integrando contexto, heurísticas y ontología, con manejo de errores y timeouts.  
6. **Postprocesamiento:** funciones de reprocesamiento y validación de actores aseguran consistencia y completitud de los resultados.

## Resultados de prueba

- Corpus: 50 discursos presidenciales (2024–2025).  
- Frases procesadas: 9052.  
- Resúmenes generados: 50.  
- Metadatos: tipo de discurso, lugar, enunciador y enunciatarios identificados.  
- Actores: prueba en 5 discursos (1002 frases) detectando 920 actores validados.

## Limitaciones y proyecciones

- Dependencia de calidad de prompts y cobertura del modelo.  
- Requiere revisión manual para corroborar resultados.  
- Consumo elevado de recursos y tiempos de cómputo intensos para identificación de actores por frase.  
- Puede ampliarse a otros corpus, análisis de emociones y estudios comparativos de dinámicas discursivas.

## Archivos incluidos

- `main.ipynb` – notebook integradora.  
- `requirements.txt` – dependencias.  
- `README.md` – instrucciones y descripción.  
- `iniciar_proyecto.bat` – script de inicio.  
- Subcarpetas:
  - `errors/` – registros de errores.  
  - `logs/` – logs de ejecución.  
  - `data/` – CSVs procesados.  
  - `modulos/` – scripts Python y recursos auxiliares (ontología, heurísticas).  

## Instrucciones para correr

Correr el archivo "iniciar_proyecto.bat". O bien:

1. **Crear un entorno nuevo limpio con Python 3.10**  
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
