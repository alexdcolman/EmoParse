# metadatos.py

import json
import pandas as pd
import time
import os
import spacy
from modulos.extraccion_fragmentos import extraer_fragmentos_relevantes
from modulos.recursos import preparar_fragmentos_str, analizar_generico
from modulos.schemas import TipoDiscursoSchema, LugarSchema
from modulos.utils_io import guardar_csv, mostrar_tiempo_procesamiento

nlp = spacy.load("es_core_news_md")

def analizar_tipo_discurso(
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
    default = TipoDiscursoSchema(tipo="", justificacion="Sin justificación")
    return analizar_generico(
        modelo_llm,
        prompt_base,
        campos,
        default,
        schema=TipoDiscursoSchema,
        etiqueta_log="Tipo de discurso",
        mostrar_prompts=mostrar_prompts,
        path_errores=path_errores
    )

def analizar_lugar(
    titulo,
    resumen,
    fragmentos,
    modelo_llm,
    prompt_base,
    mostrar_prompts=False,
    path_errores=None,
    index=None
):
    campos = {
        "TITULO": titulo,
        "RESUMEN": resumen,
        "FRAGMENTOS": preparar_fragmentos_str(fragmentos),
        "INDEX": str(index) if index is not None else None
    }
    default = LugarSchema(ciudad="", provincia="", pais="", justificacion="Sin respuesta")
    return analizar_generico(
        modelo_llm,
        prompt_base,
        campos,
        default,
        schema=LugarSchema,
        etiqueta_log="Lugar",
        mostrar_prompts=mostrar_prompts,
        path_errores=path_errores
    )

def procesar_metadatos_core(
    df,
    modelo_llm,
    diccionario,
    prompt_tipo,
    prompt_lugar,
    mostrar_prompts=False,
    path_errores_tipo=None,
    path_errores_lugar=None
):
    filas = []
    for idx, row in df.iterrows():
        base = row.to_dict()
        texto, titulo, resumen = row["texto_limpio"], row["titulo"], row["resumen"]
        fragmentos = extraer_fragmentos_relevantes(texto, nlp)

        # --- Tipo ---
        tipo_result = analizar_tipo_discurso(
            resumen,
            fragmentos,
            modelo_llm,
            prompt_tipo,
            diccionario,
            mostrar_prompts=mostrar_prompts,
            path_errores=path_errores_tipo,
            index=idx
        )
        base.update({
            "tipo_discurso": tipo_result.tipo,
            "tipo_discurso_justificacion": tipo_result.justificacion
        })

        # --- Lugar ---
        lugar_result = analizar_lugar(
            titulo,
            resumen,
            fragmentos,
            modelo_llm,
            prompt_lugar,
            mostrar_prompts=mostrar_prompts,
            path_errores=path_errores_lugar,
            index=idx
        )
        base.update({
            "lugar_ciudad": lugar_result.ciudad,
            "lugar_provincia": lugar_result.provincia,
            "lugar_pais": lugar_result.pais,
            "lugar_justificacion": lugar_result.justificacion
        })

        filas.append(base)
    return pd.DataFrame(filas)

def procesar_metadatos_llm(
    df,
    modelo_llm,
    diccionario,
    prompt_tipo,
    prompt_lugar,
    guardar=False,
    output_path=None,
    mostrar_tiempo=True,
    mostrar_prompts=False,
    path_errores_tipo=None,
    path_errores_lugar=None
):
    start_time = time.time()

    df_final = procesar_metadatos_core(
        df,
        modelo_llm,
        diccionario,
        prompt_tipo,
        prompt_lugar,
        mostrar_prompts=mostrar_prompts,
        path_errores_tipo=path_errores_tipo,
        path_errores_lugar=path_errores_lugar
    )

    if guardar and output_path:
        if os.path.exists(output_path):
            df_existente = pd.read_csv(output_path, encoding="utf-8-sig")
            df_final = pd.concat([df_existente, df_final], ignore_index=True)
        df_final.to_csv(output_path, index=False, encoding="utf-8-sig")

    if mostrar_tiempo:
        mostrar_tiempo_procesamiento(start_time, mensaje="Tiempo de procesar_tipo_lugar_llm")

    return df_final