# modules/deteccion_emociones.py
"""
Módulo M2: Detección de emociones con cache
"""

import os
import json
import re
import pandas as pd
from abc import ABC, abstractmethod

# Para HF LangChain
from langchain.llms import HuggingFacePipeline
from langchain.prompts import PromptTemplate
from langchain.chains import LLMChain
from transformers import pipeline

# Para Ollama
from ollama import Client  # Correcto import para Ollama

PROMPT_TEMPLATE = """
Analiza el siguiente texto completo en español rioplatense, tomando en cuenta todo el contexto discursivo.  
Luego, realiza un análisis detallado **frase por frase**, considerando la relación entre frases para comprender mejor las emociones y roles en el discurso.

### 1. Emociones expresadas:
Identifica emociones comunicadas directamente en cada frase. Para cada emoción, indica su modalidad según la siguiente clasificación:

- *Dicha*: nombrada explícitamente mediante un sustantivo, adjetivo o verbo emocional (ej.: "soy feliz", "estoy preocupado", "me obsesiona").
- *Mostrada*: inferible por signos no verbales o intensidad lingüística (ej.: "esto es perverso", "se puso roja", "la mirada de la policía estaba puesta en...").
- *Sostenida*: construida a través de la narrativa o el contexto, sin ser dicha ni mostrada (ej.: "fue al hospital a ver nacer a su hijo", "estaba por entrar a dar el examen").

### 2. Emociones inducidas:
Detecta las emociones que el texto busca generar en el enunciatario. Indica si la inducción es:
- *Explícita*: se apela directamente a una emoción ("tenés que indignarte", "no tengas miedo").
- *Implícita*: se induce indirectamente mediante imágenes, argumentos o tono.

### 3. Roles emocionales:
Identifica a todos los actores emocionales presentes en el texto. Para cada actor, indica las emociones asociadas. Usa estas categorías:

- **enunciador**: quien emite el texto (si tiene emociones expresadas, inducidas o proyectadas).
- **enunciatario**: el destinatario implícito o explícito del texto (si se le inducen emociones o se le atribuyen).
- **otros_actores**: personajes mencionados o categorías sociales (ej.: "la gente", "los políticos", "mi madre").

### 4. Devuelve un JSON con una entrada por cada frase.  
El JSON debe mantener el orden original de las frases.

Ejemplo:

[
  {{
    "frase": "Nos mintieron durante años.",
    "emociones_expresadas": [{{"emocion": "ira", "modalidad": "mostrada"}}],
    "emociones_inducidas": [{{"emocion": "desconfianza", "tipo": "implícita"}}],
    "roles_emocionales": {{
      "enunciador": ["ira"],
      "enunciatario": ["desconfianza"]
    }}
  }},
  ...
]

---

**Importante:**  
Para obtener mejores resultados, antes de enviar el texto al modelo, concatená todas las frases (o líneas) que querés analizar en un solo string, separadas por un espacio o salto de línea, y pasá ese string como `{texto}`.

Texto a analizar completo:
'''{texto}'''
"""

def extraer_json_de_respuesta(texto):
    """
    Extrae el contenido JSON dentro de un bloque markdown ```json ... ```
    Devuelve el string JSON o el texto original si no lo encuentra.
    """
    match = re.search(r"```json(.*?)```", texto, re.DOTALL)
    if match:
        return match.group(1).strip()
    else:
        return texto

class EmocionDetectorBase(ABC):
    def __init__(self, cache_path="cache/emociones_cache.json"):
        self.cache_path = cache_path
        self.cache = self._load_cache()

    def _load_cache(self):
        if os.path.exists(self.cache_path):
            with open(self.cache_path, "r", encoding="utf-8") as f:
                return json.load(f)
        return {}

    def _save_cache(self):
        carpeta = os.path.dirname(self.cache_path)
        if carpeta and not os.path.exists(carpeta):
            os.makedirs(carpeta)
        with open(self.cache_path, "w", encoding="utf-8") as f:
            json.dump(self.cache, f, ensure_ascii=False, indent=2)

    @abstractmethod
    def detectar_emociones(self, texto):
        pass

class EmocionDetectorHF(EmocionDetectorBase):
    def __init__(self, modelo="gemma3:latest", cache_path="cache/emociones_cache_hf.json"):
        super().__init__(cache_path)
        hf_pipeline_obj = pipeline("text-generation", model=modelo, max_length=512, do_sample=False)
        self.llm = HuggingFacePipeline(pipeline=hf_pipeline_obj)
        self.prompt = PromptTemplate(input_variables=["texto"], template=PROMPT_TEMPLATE)
        self.chain = LLMChain(llm=self.llm, prompt=self.prompt)

    def detectar_emociones(self, texto):
        texto = texto.strip()
        if texto in self.cache:
            return self.cache.get(texto)
        respuesta_raw = self.chain.run(texto)
        try:
            respuesta_json = json.loads(respuesta_raw)
        except json.JSONDecodeError:
            print("Error parsing JSON, respuesta cruda:")
            print(respuesta_raw)
            respuesta_json = respuesta_raw
        self.cache[texto] = respuesta_json
        self._save_cache()
        return respuesta_json

class EmocionDetectorOllama(EmocionDetectorBase):
    def __init__(self, modelo="gemma3", cache_path="cache/emociones_cache_ollama.json"):
        super().__init__(cache_path)
        self.modelo = modelo
        self.client = Client()

    def detectar_emociones(self, texto):
        texto = texto.strip()
        if texto in self.cache:
            return self.cache.get(texto)

        prompt = PROMPT_TEMPLATE.format(texto=texto)
        respuesta_raw = self.client.generate(model=self.modelo, prompt=prompt)
        
        text = getattr(respuesta_raw, "text", str(respuesta_raw))
        json_text = extraer_json_de_respuesta(text)
        try:
            respuesta_json = json.loads(json_text)
        except json.JSONDecodeError:
            print("Error parsing JSON, respuesta cruda:")
            print(text)
            respuesta_json = text

        self.cache[texto] = respuesta_json
        self._save_cache()
        return respuesta_json

def detectar_masivo(df, columna_texto="frase", detector=None):
    """
    Aplica detección de emociones a un DataFrame y añade columna 'emociones'.

    Args:
        df (pd.DataFrame): DataFrame con textos a analizar.
        columna_texto (str): nombre de la columna con los textos.
        detector (EmocionDetectorBase): instancia de detector (HF o Ollama).

    Returns:
        pd.DataFrame: DataFrame con columna 'emociones'.
    """
    if detector is None:
        raise ValueError("Se requiere una instancia de detector")

    emociones = []
    for texto in df[columna_texto]:
        if pd.isna(texto):
            emociones.append(None)
            continue
        emos = detector.detectar_emociones(str(texto))
        emociones.append(emos)
    df["emociones"] = emociones
    return df


# Ejemplo uso

# detector = EmocionDetectorHF(modelo="gemma3:latest")
# detector = EmocionDetectorOllama(modelo="gemma3")
# df_result = detectar_masivo(df_preprocesado, columna_texto="frase", detector=detector)
# df_result.to_csv("resultados_emociones.csv", index=False)
