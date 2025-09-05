# resumen.py

import os
import logging
import time
import pandas as pd
from tqdm import tqdm
from sentence_transformers import SentenceTransformer
from sklearn.metrics.pairwise import cosine_similarity
from modulos.recursos import limpiar_prompt
from modulos.parsers import extraer_texto_respuesta
from modulos.modelo import get_model_ollama
from modulos.utils_io import guardar_csv, mostrar_tiempo_procesamiento
from langchain_ollama import ChatOllama

logging.basicConfig(level=logging.INFO)

# Modelo de embeddings para segmentación
emb_model = SentenceTransformer("distiluse-base-multilingual-cased-v1")

# Funciones de segmentación
def segmentar_por_cambio_tema(texto, umbral=0.25):
    """
    Segmenta un texto en bloques usando embeddings de frase y similitud coseno.
    """
    parrafos = [p.strip() for p in texto.split("\n") if len(p.strip()) > 30]
    if len(parrafos) < 2:
        return [texto]

    emb = emb_model.encode(parrafos)
    segmentos, buffer = [], [parrafos[0]]

    for i in range(1, len(parrafos)):
        sim = cosine_similarity([emb[i - 1]], [emb[i]])[0][0]
        if sim < umbral:
            segmentos.append(" ".join(buffer))
            buffer = [parrafos[i]]
        else:
            buffer.append(parrafos[i])
    if buffer:
        segmentos.append(" ".join(buffer))

    return [seg for seg in segmentos if len(seg) > 100]

# Funciones de resumen
def resumir_con_llm(prompt, modelo_llm):
    """
    Llama al LLM con el prompt y devuelve solo el texto limpio.
    """
    try:
        return modelo_llm(prompt)
    except Exception as e:
        logging.warning(f"[LLM] Error al resumir: {e}")
        return "[Error en resumen]"

def resumen_llm_registro(
    registro, modelo_llm, prompt_fragmento, prompt_discurso,
    umbral=0.25, mostrar_prompts=False,
    max_chars_parciales=10000, max_chars_final=5000
):
    """
    Resume un registro individual del dataframe usando segmentación y LLM.
    max_chars_parciales: truncamiento de cada bloque para evitar prompts excesivos.
    max_chars_final: truncamiento del resumen final antes de enviarlo al LLM.
    """
    titulo = registro.get("titulo", "")
    fecha = registro.get("fecha", "")
    codigo = registro.get("codigo", "SIN_CODIGO")
    texto = registro.get("texto_limpio", "")

    # --- Resumen parcial por bloques ---
    bloques = segmentar_por_cambio_tema(texto, umbral=umbral)
    resumenes_parciales = []
    for bloque in bloques:
        if len(bloque) > max_chars_parciales:
            bloque = bloque[:max_chars_parciales] + "\n[...]"
        prompt_bloque = prompt_fragmento.replace("<<FRAGMENTO>>", bloque)
        prompt_bloque = limpiar_prompt(prompt_bloque)
        if mostrar_prompts:
            print(f"\n📤 Prompt fragmento:\n{prompt_bloque}\n")
        resumen = resumir_con_llm(prompt_bloque, modelo_llm)
        resumenes_parciales.append(resumen)

    joined_resumenes = "\n\n".join(res.strip() for res in resumenes_parciales if res.strip())
    if len(joined_resumenes) > max_chars_final:
        joined_resumenes = joined_resumenes[:max_chars_final] + "\n[...]"

    # Prompt final con todos los resúmenes parciales
    prompt_final = (
        prompt_discurso
        .replace("<<TITULO>>", titulo)
        .replace("<<FECHA>>", fecha)
        .replace("<<RESUMENES_PARCIALES>>", joined_resumenes)
    )
    prompt_final = limpiar_prompt(prompt_final)

    if mostrar_prompts:
        print(f"\n📤 Prompt final:\n{prompt_final}\n")

    resumen_final = resumir_con_llm(prompt_final, modelo_llm)

    print(f"\n🟩 Resumen generado con éxito para código: {codigo}")
    print("Resumen:")
    print(resumen_final)
    print("-" * 80)

    return resumen_final

def resumir_dataframe(
    df, modelo_llm, prompt_fragmento, prompt_discurso, umbral=0.25,
    guardar=False, path_salida=None, mostrar_prompts=False, mostrar_tiempo=True,
    max_chars_parciales=10000, max_chars_final=5000
):
    """
    Aplica resumen a un dataframe completo y devuelve la columna 'resumen'.
    Controla la longitud máxima de bloques y resumen final.
    """
    start_time = time.time()
    df = df.copy()

    tqdm.pandas(desc="Generando resúmenes con LLM")
    df["resumen"] = df.progress_apply(
        lambda row: resumen_llm_registro(
            row,
            modelo_llm=modelo_llm,
            prompt_fragmento=prompt_fragmento,
            prompt_discurso=prompt_discurso,
            umbral=umbral,
            mostrar_prompts=mostrar_prompts,
            max_chars_parciales=max_chars_parciales,
            max_chars_final=max_chars_final
        ),
        axis=1
    )

    if guardar:
        if not path_salida:
            raise ValueError("Debés especificar `path_salida` si guardar=True.")
        guardar_csv(df, path_salida, verbose=True)

    if mostrar_tiempo:
        mostrar_tiempo_procesamiento(start_time, mensaje="Tiempo de resumir_dataframe")

    return df