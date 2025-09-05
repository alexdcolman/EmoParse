import ollama
import logging
from langchain_ollama import ChatOllama
from modulos.parsers import extraer_texto_respuesta

def get_model_ollama(modelo="gpt-oss:20b", temperature=0.0, output_format="text"):
    """
    Devuelve un callable modelo_llm(prompt).
    """
    llm = ChatOllama(model=modelo, temperature=temperature)

    def modelo_llm(prompt: str):
        try:
            respuesta = llm.invoke([{"role": "user", "content": prompt}])
            if output_format == "text":
                return extraer_texto_respuesta(respuesta)
            elif output_format == "raw":
                return respuesta
            else:
                raise ValueError(f"Formato de salida desconocido: {output_format}")
        except Exception as e:
            logging.warning(f"[LLM wrapper] Error llamando al modelo: {e}")
            return "[Error en LLM]"

    return modelo_llm

def get_model_ollama_par(
    modelo: str = "gpt-oss:20b",
    temperature: float = 0.0,
    output_format: str = "text",
    num_predict: int | None = None,
    num_parallel: int | None = None,
):
    """
    Devuelve un callable modelo_llm(prompt).
    
    Parámetros extra:
    - num_predict: máximo de tokens de salida (equivalente a max_tokens).
    - num_parallel: cantidad de requests en paralelo que Ollama maneja (batching/concurrencia).
    """

    # Armar kwargs dinámicos
    ollama_kwargs = {"temperature": temperature}
    if num_predict is not None:
        ollama_kwargs["num_predict"] = num_predict
    if num_parallel is not None:
        ollama_kwargs["num_parallel"] = num_parallel

    # Crear instancia del modelo
    llm = ChatOllama(model=modelo, **ollama_kwargs)

    def modelo_llm(prompt: str):
        try:
            respuesta = llm.invoke([{"role": "user", "content": prompt}])
            if output_format == "text":
                return extraer_texto_respuesta(respuesta)
            elif output_format == "raw":
                return respuesta
            else:
                raise ValueError(f"Formato de salida desconocido: {output_format}")
        except Exception as e:
            logging.warning(f"[LLM wrapper] Error llamando al modelo: {e}")
            return "[Error en LLM]"

    return modelo_llm