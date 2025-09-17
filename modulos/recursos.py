# recursos.py

import json
import os
import logging
import ast
import re
import signal
import threading
import platform
import gc
import time
import torch
import subprocess
import requests
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
    timeout=60,
    recorte_id=None,
    delay_between_calls: float = 0.0,
    max_retries: int = 3,
    backoff_factor: float = 1.0,
    restart_ollama: bool = True   # <--- nuevo flag
):
    import time
    import os
    import json
    import logging
    from datetime import datetime

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

    for intento in range(1, max_retries + 1):
        # --- healthcheck antes de cada request ---
        if not check_and_restart_ollama(restart_if_down=restart_ollama):
            logging.error("[analizar_generico] Ollama no disponible ni tras restart.")
            break

        try:
            respuesta = ejecutar_con_timeout(lambda: modelo_llm(prompt), timeout=timeout)
            resultado = parser.parse(respuesta)
            break  # éxito, salir del loop

        except Exception as e:
            logging.warning(f"[analizar_generico] Excepción en {etiqueta_log} (intento {intento}): {e}")
            resultado = default

            if intento < max_retries:
                sleep_time = backoff_factor * (2 ** (intento - 1))
                logging.info(f"[analizar_generico] Reintentando en {sleep_time:.1f}s...")
                time.sleep(sleep_time)
            else:
                logging.warning(f"[analizar_generico] Fallaron todos los {max_retries} intentos.")

    # --- mantenimiento/pausa que NO cuenta para el timeout ---
    try:
        if delay_between_calls and delay_between_calls > 0:
            time.sleep(delay_between_calls)
        limpiar(cada_n=5)
    except Exception:
        pass

    # --- Registro de errores si se devuelve default ---
    if resultado == default and path_errores:
        os.makedirs(os.path.dirname(path_errores), exist_ok=True)
        registro_error = {
            "etiqueta": etiqueta_log,
            "error": f"Default devuelto tras {max_retries} intentos (timeout, parseo fallido o respuesta vacía)",
            "prompt_usado": prompt,
            "respuesta_cruda": respuesta,
            "campos": campos,
            "timestamp": datetime.now().isoformat(),
            "INDEX": campos.get("INDEX")
        }
        if recorte_id is not None:
            registro_error["recorte_id"] = recorte_id
        with open(path_errores, "a", encoding="utf-8-sig") as f:
            f.write(json.dumps(registro_error, ensure_ascii=False) + "\n")

    return resultado

# Función de limpieza
_llamadas_limpiar = 0 # Contador global para saber cuántas veces se llamó a limpiar()

def limpiar(cada_n=5):
    """
    Libera memoria RAM y VRAM, pero solo se ejecuta
    realmente cada 'cada_n' llamadas.
    
    - cada_n=1  -> limpia siempre
    - cada_n=5  -> limpia cada 5 llamadas
    """
    global _llamadas_limpiar
    _llamadas_limpiar += 1

    if _llamadas_limpiar % cada_n != 0:
        return  # no limpia todavía

    # --- limpieza real ---
    try:
        gc.collect()
    except Exception:
        pass

    try:
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
    except Exception:
        pass

# Función helper con healthcheck y restart opcional
def check_and_restart_ollama(restart_if_down: bool = True, sleep_after_restart: int = 5) -> bool:
    """
    Hace un healthcheck a Ollama y, si no responde, opcionalmente lo reinicia.

    Parámetros:
    - restart_if_down: si True, intenta reiniciar Ollama si está caído.
    - sleep_after_restart: segundos a dormir tras reiniciar antes de devolver control.

    Devuelve:
    - True si Ollama está operativo tras la verificación/restart.
    - False si no se pudo verificar ni reiniciar.
    """
    try:
        # Healthcheck vía API local
        resp = requests.get("http://localhost:11434/api/tags", timeout=3)
        if resp.status_code == 200:
            return True
    except Exception:
        pass  # no responde

    logging.warning("[ollama] Ollama no responde al healthcheck")

    if restart_if_down:
        try:
            logging.info("[ollama] Intentando reiniciar Ollama...")
            subprocess.run(["pkill", "-9", "ollama"], check=False)
            subprocess.Popen(["ollama", "serve"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            time.sleep(sleep_after_restart)
            # Reintentar healthcheck
            resp = requests.get("http://localhost:11434/api/tags", timeout=5)
            if resp.status_code == 200:
                logging.info("[ollama] Reinicio exitoso")
                return True
        except Exception as e:
            logging.error(f"[ollama] Error al reiniciar Ollama: {e}")

    return False

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