import os
import logging
import pandas as pd
from tqdm import tqdm
from sentence_transformers import SentenceTransformer
from sklearn.metrics.pairwise import cosine_similarity
from modulos.recursos import limpiar_prompt

# Configuración
logging.basicConfig(level=logging.INFO)
emb_model = SentenceTransformer("distiluse-base-multilingual-cased-v1")

def segmentar_por_cambio_tema(texto, umbral=0.25):
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

def resumir_con_llm(prompt, modelo_llm):
    try:
        return modelo_llm(prompt).strip()
    except Exception as e:
        logging.warning(f"[LLM] Error al resumir: {e}")
        return "[Error en resumen]"

def resumen_llm_registro(registro, modelo_llm, prompt_fragmento, prompt_discurso, umbral=0.25, mostrar_prompts=False):
    titulo = registro.get("titulo", "")
    fecha = registro.get("fecha", "")
    codigo = registro.get("codigo", "SIN_CODIGO")
    texto = registro.get("texto_limpio", "")

    bloques = segmentar_por_cambio_tema(texto, umbral=umbral)

    resumenes_parciales = []
    for bloque in bloques:
        prompt_bloque = prompt_fragmento.replace("<<FRAGMENTO>>", bloque)
        prompt_bloque = limpiar_prompt(prompt_bloque)
        if mostrar_prompts:
            print(f"\n📤 Prompt fragmento:\n{prompt_bloque}\n")
        resumen = resumir_con_llm(prompt_bloque, modelo_llm)
        resumenes_parciales.append(resumen)

    joined_resumenes = "\n\n".join(res.strip() for res in resumenes_parciales if res.strip())

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

def resumir_dataframe(df, modelo_llm, prompt_fragmento, prompt_discurso, umbral=0.25, guardar=False, path_salida=None, mostrar_prompts=False):
    df = df.copy()

    tqdm.pandas(desc="Generando resúmenes con LLM")
    df["resumen"] = df.progress_apply(
        lambda row: resumen_llm_registro(
            row,
            modelo_llm=modelo_llm,
            prompt_fragmento=prompt_fragmento,
            prompt_discurso=prompt_discurso,
            umbral=umbral,
            mostrar_prompts=mostrar_prompts
        ),
        axis=1
    )

    if guardar:
        if not path_salida:
            raise ValueError("Debés especificar path_salida si guardar=True.")
        os.makedirs(os.path.dirname(path_salida), exist_ok=True)
        df.to_csv(path_salida, index=False, encoding="utf-8-sig")
        print(f"\n✅ Archivo guardado en: {path_salida}")

    return df

