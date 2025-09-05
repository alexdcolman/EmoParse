# recursos.py

import json
import os
import logging
import ast
import re
import signal
import threading
import platform
from datetime import datetime
from langchain.output_parsers import PydanticOutputParser
from modulos.parsers import extraer_texto_respuesta

# Base path relativo al archivo actual (recursos.py)
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

class TimeoutException(Exception):
    pass

# Manejadores de timeout por SO
def _ejecutar_con_timeout_signal(func, timeout):
    """
    Versión Unix/Linux/Mac usando signal.alarm
    """
    def handler(signum, frame):
        raise TimeoutException

    # Guardamos handler anterior para restaurar luego
    old_handler = signal.signal(signal.SIGALRM, handler)
    signal.alarm(timeout)

    try:
        return func()
    finally:
        signal.alarm(0)  # Desactivar alarma
        signal.signal(signal.SIGALRM, old_handler)

def _ejecutar_con_timeout_threading(func, timeout):
    """
    Versión Windows usando threading
    """
    result = [TimeoutException("Tiempo excedido")]

    def wrapper():
        try:
            result[0] = func()
        except Exception as e:
            result[0] = e

    hilo = threading.Thread(target=wrapper)
    hilo.daemon = True
    hilo.start()
    hilo.join(timeout)

    if hilo.is_alive():
        raise TimeoutException("Tiempo excedido")
    elif isinstance(result[0], Exception):
        raise result[0]
    else:
        return result[0]

def ejecutar_con_timeout(func, timeout=60):
    """
    Wrapper portable: usa signal en Unix, threading en Windows.
    """
    if platform.system() == "Windows":
        return _ejecutar_con_timeout_threading(func, timeout)
    else:
        return _ejecutar_con_timeout_signal(func, timeout)

# Analizador genérico
def analizar_generico(
    modelo_llm,
    prompt_base,
    campos,
    default,
    schema=None,
    etiqueta_log=None,
    mostrar_prompts=False,
    path_errores=None,
    timeout=30
):
    """
    Ejecuta LLM con prompt y parsea usando PydanticOutputParser de LangChain.
    Si hay error, timeout o se devuelve default, se guarda un JSONL si path_errores está definido.
    """
    if schema is None:
        logging.warning("[analizar_generico] No se pasó schema, devolviendo default")
        return default

    parser = schema.get_langchain_parser()
    format_instructions = parser.get_format_instructions()

    # Construir prompt
    prompt = prompt_base
    for clave, valor in campos.items():
        prompt = prompt.replace(f"<<{clave.upper()}>>", valor)
    prompt = f"{prompt}\n\n{format_instructions}"

    if mostrar_prompts:
        print(f"\n📤 Prompt - {etiqueta_log or 'Análisis'}:\n{prompt}\n")

    respuesta = ""
    resultado = default

    try:
        respuesta = ejecutar_con_timeout(lambda: modelo_llm(prompt), timeout=timeout)
        resultado = parser.parse(respuesta)

    except Exception as e:
        logging.warning(f"[analizar_generico] Excepción en {etiqueta_log}: {e}")
        resultado = default

    # --- Registro de errores si se devuelve default ---
    if resultado == default and path_errores:
        os.makedirs(os.path.dirname(path_errores), exist_ok=True)
        registro_error = {
            "etiqueta": etiqueta_log,
            "error": "Default devuelto (timeout, parseo fallido o respuesta vacía)",
            "prompt_usado": prompt,
            "respuesta_cruda": respuesta,
            "campos": campos,
            "timestamp": datetime.now().isoformat(),
            "INDEX": campos.get("INDEX")
        }
        with open(path_errores, "a", encoding="utf-8-sig") as f:
            f.write(json.dumps(registro_error, ensure_ascii=False) + "\n")

    return resultado

# Preparación de fragmentos y limpieza de prompts
def preparar_fragmentos_str(fragmentos):
    return "\n".join([f"Fragmento {i+1}:\n{frag}" for i, frag in enumerate(fragmentos)])

def limpiar_prompt(prompt: str) -> str:
    # Elimina espacios innecesarios y normaliza saltos de línea
    return "\n".join(line.strip() for line in prompt.strip().splitlines() if line.strip())

# Carga de ontología y heurística
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

# Manejo de registro de errores
class ErrorLogger:
    """
    Maneja registro de errores en formato JSONL (un error por línea).
    """

    def __init__(self, path_errores):
        self.path = path_errores

    def cargar(self):
        """
        Devuelve lista de errores (dicts). Si no existe, devuelve [].
        """
        if not os.path.exists(self.path):
            return []

        errores = []
        with open(self.path, "r", encoding="utf-8-sig") as f:
            for line in f:
                try:
                    errores.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
        return errores

    def guardar(self, error, auto_timestamp=True):
        """
        Agrega un único error al archivo.
        """
        if auto_timestamp and "timestamp" not in error:
            error["timestamp"] = datetime.now().isoformat()

        with open(self.path, "a", encoding="utf-8-sig") as f:
            f.write(json.dumps(error, ensure_ascii=False) + "\n")

    def guardar_varios(self, errores, overwrite=False, auto_timestamp=True):
        """
        Guarda múltiples errores.
        """
        mode = "w" if overwrite else "a"
        with open(self.path, mode, encoding="utf-8-sig") as f:
            for err in errores:
                if auto_timestamp and "timestamp" not in err:
                    err["timestamp"] = datetime.now().isoformat()
                f.write(json.dumps(err, ensure_ascii=False) + "\n")

    def eliminar_error(self, error_a_eliminar):
        """
        Elimina un error específico buscando coincidencia por INDEX y etiqueta.
        """
        if not os.path.exists(self.path):
            return

        errores = self.cargar()
        index_obj = error_a_eliminar.get("INDEX")
        etiqueta_obj = error_a_eliminar.get("etiqueta")

        errores_filtrados = [
            err for err in errores
            if not (err.get("INDEX") == index_obj and err.get("etiqueta") == etiqueta_obj)
        ]

        # Solo sobrescribimos si hubo cambios
        if len(errores_filtrados) < len(errores):
            with open(self.path, "w", encoding="utf-8-sig") as f:
                for err in errores_filtrados:
                    f.write(json.dumps(err, ensure_ascii=False) + "\n")