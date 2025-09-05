# parsers.py

import re
import logging
from typing import Any

logging.basicConfig(level=logging.INFO)

def extraer_texto_respuesta(respuesta: Any) -> str:
    """
    Extrae el texto principal de la respuesta del LLM,
    quitando metadatos o bloques <think>.
    """
    try:
        if isinstance(respuesta, str):
            texto = respuesta.strip()
        elif hasattr(respuesta, "content"):
            texto = respuesta.content.strip()
        elif isinstance(respuesta, dict):
            if "content" in respuesta:
                texto = respuesta["content"].strip()
            elif "message" in respuesta and "content" in respuesta["message"]:
                texto = respuesta["message"]["content"].strip()
            else:
                texto = str(respuesta).strip()
        else:
            texto = str(respuesta).strip()

        # Quitar bloques <think> y espacios iniciales/finales
        texto = re.sub(r"<think>.*?</think>\n?", "", texto, flags=re.DOTALL).strip()
        return texto

    except Exception as e:
        logging.warning(f"[parsers] Error extrayendo texto: {e}")
        return "[Error en texto LLM]"