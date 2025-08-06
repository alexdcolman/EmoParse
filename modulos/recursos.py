import json
import os

# Base path relativo al archivo actual (recursos.py)
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

def cargar_ontologia(path=None):
    if path is None:
        path = os.path.join(BASE_DIR, "ontologia", "actores.json")
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def cargar_heuristicas(path=None):
    if path is None:
        path = os.path.join(BASE_DIR, "heuristicas", "inferencia_actores.txt")
    with open(path, "r", encoding="utf-8") as f:
        return f.read()

def cargar_prompt_template1(path=None):
    if path is None:
        path = os.path.join(BASE_DIR, "prompts", "identificar_actores.txt")
    elif not os.path.isabs(path):
        path = os.path.join(BASE_DIR, path)
    
    with open(path, "r", encoding="utf-8") as f:
        return f.read()

def cargar_prompt_template(path):
    with open(path, "r", encoding="utf-8") as f:
        return f.read()

def limpiar_prompt(prompt: str) -> str:
    # Elimina espacios innecesarios y normaliza saltos de línea
    return "\n".join(line.strip() for line in prompt.strip().splitlines() if line.strip())

import ast

def limpiar_dict_modelo(respuesta: str):
    """
    Intenta decodificar la respuesta del modelo como un diccionario Python (no JSON).
    Es más flexible con comillas internas.
    """
    try:
        contenido = re.sub(r"^```(json|python)?\s*|\s*```$", "", respuesta.strip(), flags=re.DOTALL)
        return ast.literal_eval(contenido)
    except Exception as e:
        print("❌ Error al interpretar como diccionario Python:", e)
        print(respuesta)
        return None

def limpiar_json_modelo(respuesta: str):
    try:
        contenido = re.sub(r"^```json\s*|\s*```$", "", respuesta.strip(), flags=re.DOTALL)
        return json.loads(contenido)
    except Exception as e:
        print("❌ Error al decodificar JSON:", e)
        print(respuesta)
        return None

# Limpiado de respuestas de modelos

import json
import re
import ast

def limpiar_markdown(response: str) -> str:
    """
    Elimina bloques markdown de código (```json```, ```python```, etc) al principio y final del texto.
    """
    return re.sub(r"^```(json|python)?\s*|\s*```$", "", response.strip(), flags=re.DOTALL)

def reemplazar_comillas_simples_por_dobles(texto: str) -> str:
    """
    Reemplaza comillas simples por dobles en contextos JSON simples.
    Atención: no es infalible, mejor usar junto con parseo seguro.
    """
    # Solo reemplaza comillas simples que no estén escapadas ni dentro de strings dobles
    # Aquí simplificamos para casos comunes
    texto = re.sub(r"(?<!\\)'", '"', texto)
    return texto

def corregir_comas_basico(texto: str) -> str:
    """
    Intenta corregir errores básicos de comas:
    - Agrega coma faltante entre } y { en listas de objetos JSON
    - Elimina comas finales antes de cierre de objetos o listas
    """
    # Ejemplo básico: agregar coma entre objetos concatenados (esto es muy simple)
    texto = re.sub(r"}\s*{", "},{", texto)
    # Eliminar comas finales antes de ] o }
    texto = re.sub(r",(\s*[\]}])", r"\1", texto)
    return texto

def parsear_json_con_fallback(texto: str):
    """
    Intenta parsear texto como JSON con limpieza y fallback a dict Python.
    """
    texto = limpiar_markdown(texto)
    texto = reemplazar_comillas_simples_por_dobles(texto)
    texto = corregir_comas_basico(texto)

    try:
        return json.loads(texto)
    except json.JSONDecodeError as e_json:
        print(f"❌ Error json.loads(): {e_json}")
        # Intentar parsear como dict Python (más permisivo, con ast.literal_eval)
        try:
            return ast.literal_eval(texto)
        except Exception as e_ast:
            print(f"❌ Error ast.literal_eval(): {e_ast}")
            print("Respuesta problemática:\n", texto)
            return None

# Ejemplo de función para limpiar respuesta del modelo (usar en lugar de limpiar_json_modelo)
def limpiar_respuesta_modelo(respuesta: str):
    """
    Función genérica para limpiar y parsear la respuesta del modelo LLM.
    """
    resultado = parsear_json_con_fallback(respuesta)
    if resultado is None:
        print("⚠️ No se pudo parsear la respuesta del modelo.")
    return resultado

import re

def parsear_actores_texto(texto):
    """
    Parsea el formato libre de actores devuelto por el modelo a una lista de diccionarios.
    El formato esperado en texto es:

    - ACTOR: ...
      TIPO: ...
      MODO: ...
      JUSTIFICACION: ...

    Retorna:
        lista de dicts con claves: actor, tipo, modo, justificacion.
    """
    actores = []
    bloques = re.split(r'\n(?=- ACTOR: )', texto.strip())  # Divide solo en líneas que empiezan con "- ACTOR:"

    for bloque in bloques:
        actor_match = re.search(r'- ACTOR: (.+)', bloque)
        tipo_match = re.search(r'  TIPO: (.+)', bloque)
        modo_match = re.search(r'  MODO: (.+)', bloque)
        justif_match = re.search(r'  JUSTIFICACION: (.+)', bloque)

        if actor_match and tipo_match and modo_match and justif_match:
            actores.append({
                "actor": actor_match.group(1).strip(),
                "tipo": tipo_match.group(1).strip(),
                "modo": modo_match.group(1).strip(),
                "justificacion": justif_match.group(1).strip()
            })
        else:
            # Opcional: podrías registrar logs o avisos si algún bloque está incompleto
            continue
    return actores