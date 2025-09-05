import os
import json
import time
import logging
import pandas as pd
from tqdm import tqdm
from pathlib import Path
from modulos.recursos import cargar_heuristicas, cargar_ontologia, limpiar_prompt, analizar_generico
from modulos.schemas import ActorSchema, ListaActoresSchema
from modulos.utils_io import guardar_csv, mostrar_tiempo_procesamiento
from modulos.modelo import get_model_ollama

# -------------------- CONSTRUCCIÓN DE PROMPT --------------------

def construir_prompt(
    frase,
    frases_contexto,
    resumen_global,
    tipo_discurso,
    fecha,
    lugar_justificacion,
    enunciador,
    enunciatarios,
    heuristicas,
    ontologia,
    prompt_base
):
    return limpiar_prompt(prompt_base.format(
        resumen_global=resumen_global,
        frase=frase,
        frases_contexto="\n".join(frases_contexto),
        heuristicas=heuristicas,
        ontologia=ontologia,
        tipo_discurso=tipo_discurso,
        fecha=fecha,
        lugar_justificacion=lugar_justificacion,
        enunciatarios=enunciatarios,
        enunciador=enunciador
    ))

# -------------------- PROCESAR UNA FRASE --------------------

def extraer_contexto(df_recortes, frase_idx, window=4):
    idx_inicio = max(frase_idx - window, 0)
    idx_fin = min(frase_idx + window, len(df_recortes) - 1)
    return df_recortes.loc[idx_inicio:idx_fin, "texto_limpio"].tolist()

def obtener_metadatos(df_enunc, codigo):
    fila = df_enunc[df_enunc["codigo"] == codigo].iloc[0]
    enunciatarios = []
    for col in fila.index:
        if col.startswith("enunciatario_") and col.endswith("_actor"):
            idx = col.split("_")[1]
            actor = fila[col]
            tipo_col = f"enunciatario_{idx}_tipo"
            tipo = fila.get(tipo_col, "")
            enunciatarios.append(f"{actor} (tipo: {tipo})")
    return fila, enunciatarios

def llamar_llm_y_parsear(modelo_llm, prompt, schema, mostrar_prompt=False, path_errores=None, index=None):
    try:
        data = analizar_generico(
            modelo_llm=modelo_llm,
            prompt_base=prompt,
            campos={"INDEX": str(index) if index is not None else None},
            default=[],
            schema=schema,
            mostrar_prompts=mostrar_prompt,
            path_errores=path_errores,
            etiqueta_log=f"Actores idx={index}"
        )

        # --- Extraer lista interna si es RootModel ---
        if data:
            if isinstance(data, list):
                lista_actores = data
            elif hasattr(data, "root"):  # RootModel (Pydantic v2)
                lista_actores = data.root
            elif isinstance(data, tuple):  # compatibilidad versiones antiguas
                lista_actores = data[0]
            else:
                logging.warning(f"[llm_parse] No se reconoce el formato de data: {type(data)}")
                lista_actores = []
        else:
            lista_actores = []

        columnas = list(ActorSchema.__fields__.keys())
        df = pd.DataFrame([a.model_dump() for a in lista_actores]) if lista_actores else pd.DataFrame(columns=columnas)
        return df, lista_actores

    except Exception as e:
        logging.warning(f"[llm_parse] Error inesperado en index={index}: {e}")
        columnas = list(ActorSchema.__fields__.keys())
        return pd.DataFrame(columns=columnas), []

def procesar_una_frase(
    frase_idx, df_recortes, df_enunc, modelo_llm, prompt_actores, mostrar_prompt=False,
    max_context=2, path_errores=None
):
    frase = df_recortes.loc[frase_idx, "texto_limpio"]
    recorte_id = df_recortes.loc[frase_idx, "recorte_id"]
    codigo = df_recortes.loc[frase_idx, "codigo"]

    frases_contexto = extraer_contexto(df_recortes, frase_idx, window=max_context)
    fila_enunc, enunciatarios = obtener_metadatos(df_enunc, codigo)
    
    heuristicas = cargar_heuristicas()
    ontologia = json.dumps(cargar_ontologia(), indent=2, ensure_ascii=False)

    prompt = construir_prompt(
        frase, frases_contexto, fila_enunc.get("resumen", ""),
        fila_enunc.get("tipo_discurso", ""), fila_enunc.get("fecha", ""),
        fila_enunc.get("lugar_justificacion", ""), fila_enunc.get("enunciador_actor", ""),
        "\n".join(enunciatarios), heuristicas, ontologia, prompt_base=prompt_actores
    )

    df_actores, data = llamar_llm_y_parsear(
        modelo_llm, prompt, ListaActoresSchema,
        mostrar_prompt=mostrar_prompt,
        path_errores=path_errores,
        index=frase_idx
    )

    df_actores["frase_idx"] = frase_idx
    df_actores["recorte_id"] = recorte_id
    df_actores["codigo"] = codigo

    return df_actores, prompt, data

# -------------------- IDENTIFICAR ACTORES CON CONTEXTO --------------------

def identificar_actores_con_contexto(
    df_recortes, df_enunc, path_errores=None, output_path=None,
    modelo_llm=None, mostrar_prompts=False, guardar=True,
    mostrar_tiempo=False, checkpoint_interval=50,
    procesador=None, prompt_actores=None, max_context=2
):
    start_time = time.time()
    if modelo_llm is None:
        modelo_llm = get_model_ollama(modelo="gpt-oss:20b", temperature=0.0, output_format="text")
    if procesador is None:
        procesador = procesar_una_frase

    resultados = []

    for i in tqdm(range(len(df_recortes))):
        try:
            df_actores, prompt, data = procesador(
                frase_idx=i,
                df_recortes=df_recortes,
                df_enunc=df_enunc,
                modelo_llm=modelo_llm,
                mostrar_prompt=mostrar_prompts,
                prompt_actores=prompt_actores,
                max_context=max_context,
                path_errores=path_errores
            )
            resultados.append(df_actores)

            # checkpoints periódicos
            if guardar and output_path and checkpoint_interval and (i + 1) % checkpoint_interval == 0:
                df_parcial = pd.concat(resultados, ignore_index=True)
                checkpoint_path = Path(output_path)
                checkpoint_path = checkpoint_path.with_name(checkpoint_path.stem + "_checkpoint.csv")
                guardar_csv(df_parcial, checkpoint_path)

        except Exception as e:
            # Solo log a consola/archivo, sin escribir JSONL manual
            logging.warning(f"[identificar_actores_con_contexto] Error en frase_idx={i}: {e}")
            continue

    if not resultados:
        raise ValueError("No se generaron resultados. Verificá si hubo errores.")

    df_resultado = pd.concat(resultados, ignore_index=True)
    if guardar and output_path:
        guardar_csv(df_resultado, output_path)

    if mostrar_tiempo:
        mostrar_tiempo_procesamiento(start_time, mensaje="Tiempo de identificar_actores_con_contexto")

    return df_resultado