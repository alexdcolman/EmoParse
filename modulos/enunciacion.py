# enunciacion.py

import json
import pandas as pd
import time
import spacy
from modulos.extraccion_fragmentos import extraer_fragmentos_relevantes
from modulos.recursos import preparar_fragmentos_str, analizar_generico
from modulos.schemas import EnunciacionSchema, EnunciadorSchema
from modulos.utils_io import guardar_csv, mostrar_tiempo_procesamiento

nlp = spacy.load("es_core_news_md")

def analizar_enunciacion(
    resumen,
    fragmentos,
    modelo_llm,
    prompt_base,
    diccionario=None,
    mostrar_prompts=False,
    path_errores=None,
    index=None
):
    campos = {
        "RESUMEN": resumen,
        "FRAGMENTOS": preparar_fragmentos_str(fragmentos),
        "DICCIONARIO": json.dumps(diccionario, indent=2, ensure_ascii=False) if diccionario else "",
        "INDEX": str(index) if index is not None else None
    }
    default = EnunciacionSchema(
        enunciador=EnunciadorSchema(actor="", justificacion="Sin justificación"),
        enunciatarios=[]
    )
    return analizar_generico(
        modelo_llm,
        prompt_base,
        campos,
        default,
        schema=EnunciacionSchema,
        etiqueta_log="Enunciación",
        mostrar_prompts=mostrar_prompts,
        path_errores=path_errores
    )

def procesar_enunciacion_core(
    df,
    modelo_llm,
    diccionario,
    prompt_enunciacion,
    mostrar_prompts=False,
    path_errores=None
):
    filas = []
    for idx, row in df.iterrows():
        base = row.to_dict()
        resumen = row["resumen"]
        texto = row["texto_limpio"]
        fragmentos = extraer_fragmentos_relevantes(texto, nlp)

        enun_result = analizar_enunciacion(
            resumen,
            fragmentos,
            modelo_llm,
            prompt_enunciacion,
            diccionario,
            mostrar_prompts=mostrar_prompts,
            path_errores=path_errores,
            index=idx
        )
        base.update({
            "enunciador_actor": enun_result.enunciador.actor,
            "enunciador_justificacion": enun_result.enunciador.justificacion
        })
        for i, e in enumerate(enun_result.enunciatarios):
            base[f"enunciatario_{i}_actor"] = e.actor
            base[f"enunciatario_{i}_tipo"] = e.tipo
            base[f"enunciatario_{i}_justificacion"] = e.justificacion
        filas.append(base)
    return pd.DataFrame(filas)

def procesar_enunciacion_llm(
    df,
    modelo_llm,
    diccionario,
    prompt_enunciacion,
    guardar=False,
    output_path=None,
    mostrar_tiempo=True,
    mostrar_prompts=False,
    path_errores=None
):
    start_time = time.time()
    df_final = procesar_enunciacion_core(
        df,
        modelo_llm,
        diccionario,
        prompt_enunciacion,
        mostrar_prompts=mostrar_prompts,
        path_errores=path_errores
    )
    if guardar and output_path:
        guardar_csv(df_final, output_path)
    if mostrar_tiempo:
        mostrar_tiempo_procesamiento(start_time, mensaje="Tiempo de procesar_enunciacion_llm")
    return df_final