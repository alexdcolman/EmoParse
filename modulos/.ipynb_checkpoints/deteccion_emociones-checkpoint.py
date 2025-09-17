import os
import json
import time
import logging
import pandas as pd
from tqdm import tqdm
from pathlib import Path

from modulos.recursos import (
    cargar_ontologia,
    limpiar_prompt,
    analizar_generico,
    cargar_heuristicas,
)
from modulos.utils_io import guardar_csv, mostrar_tiempo_procesamiento
from modulos.modelo import get_model_ollama
from modulos.schemas import ListaEmocionesSchema
from modulos.paths import BASE_DIR

def construir_prompt_emociones(
    frase,
    frases_contexto,
    resumen_global,
    tipo_discurso,
    fecha,
    lugar_justificacion,
    enunciador,
    enunciatarios,
    actores,
    heuristicas,
    ontologia,
    prompt_base
):
    """
    Arma el prompt para pedirle al LLM identificación de emociones discursivas.
    """
    return limpiar_prompt(
        prompt_base.format(
            resumen_global=resumen_global,
            frase=frase,
            frases_contexto="\n".join(frases_contexto),
            heuristicas=heuristicas,
            ontologia=ontologia,
            tipo_discurso=tipo_discurso,
            fecha=fecha,
            lugar_justificacion=lugar_justificacion,
            enunciatarios=enunciatarios,
            enunciador=enunciador,
            actores=actores
        )
    )

def extraer_contexto(df_recortes, frase_idx, window=3):
    """
    Devuelve lista de frases alrededor de la frase central.
    """
    idx_inicio = max(frase_idx - window, 0)
    idx_fin = min(frase_idx + window, len(df_recortes) - 1)
    return df_recortes.loc[idx_inicio:idx_fin, "texto_limpio"].tolist()

def obtener_metadatos(df_discursos, df_actores, codigo):
    """
    Devuelve fila de df_discursos + lista de enunciatarios + actores externos.
    """
    fila = df_discursos[df_discursos["codigo"] == codigo].iloc[0]

    enunciatarios = []
    for col in fila.index:
        if col.startswith("enunciatario_") and col.endswith("_actor"):
            idx = col.split("_")[1]
            actor = fila[col]
            tipo_col = f"enunciatario_{idx}_tipo"
            tipo = fila.get(tipo_col, "")
            enunciatarios.append(f"{actor} (tipo: {tipo})")

    actores = df_actores[df_actores["codigo"] == codigo]["actor"].tolist()
    return fila, enunciatarios, actores

def llamar_llm_y_parsear(
    modelo_llm, prompt, schema, mostrar_prompt=False, path_errores=None, index=None
):
    """
    Llama al modelo con analizar_generico y devuelve dataframe con resultados.
    """
    try:
        data = analizar_generico(
            modelo_llm=modelo_llm,
            prompt_base=prompt,
            campos={"INDEX": str(index) if index is not None else None},
            default=[],
            schema=schema,
            mostrar_prompts=mostrar_prompt,
            path_errores=path_errores,
            etiqueta_log=f"Emociones idx={index}",
        )

        if data:
            if isinstance(data, list):
                lista = data
            elif hasattr(data, "root"):
                lista = data.root
            else:
                lista = []
        else:
            lista = []

        columnas = list(schema.__fields__.keys())
        df = pd.DataFrame([a.model_dump() for a in lista]) if lista else pd.DataFrame(columns=columnas)
        return df, lista

    except Exception as e:
        logging.warning(f"[llm_parse_emociones] Error inesperado en index={index}: {e}")
        columnas = list(schema.__fields__.keys())
        return pd.DataFrame(columns=columnas), []

def procesar_una_frase(
    frase_idx,
    df_recortes,
    df_discursos,
    df_actores,
    modelo_llm,
    prompt_emociones,
    schema,
    mostrar_prompt=False,
    max_context=2,
    path_errores=None,
):
    """
    Procesa una frase, construye prompt y llama al LLM.
    """
    frase = df_recortes.loc[frase_idx, "texto_limpio"]
    recorte_id = df_recortes.loc[frase_idx, "recorte_id"]
    codigo = df_recortes.loc[frase_idx, "codigo"]

    frases_contexto = extraer_contexto(df_recortes, frase_idx, window=max_context)
    fila_disc, enunciatarios, actores = obtener_metadatos(df_discursos, df_actores, codigo)

    # --- Filtrar solo actores que aparecen en la frase ---
    actores_en_frase = [a for a in actores if a in frase]

    heuristicas_path = Path(BASE_DIR) / "modulos" / "heuristicas" / "inferencia_emociones.txt"
    heuristicas = cargar_heuristicas(path=str(heuristicas_path))
    ontologia_path = Path(BASE_DIR) / "modulos" / "ontologia" / "emociones.json"
    ontologia = json.dumps(
        cargar_ontologia(path=str(ontologia_path)),
        indent=2,
        ensure_ascii=False
    )

    prompt = construir_prompt_emociones(
        frase=frase,
        frases_contexto=frases_contexto,
        resumen_global=fila_disc.get("resumen", ""),
        tipo_discurso=fila_disc.get("tipo_discurso", ""),
        fecha=fila_disc.get("fecha", ""),
        lugar_justificacion=fila_disc.get("lugar_justificacion", ""),
        enunciador=fila_disc.get("enunciador_actor", ""),
        enunciatarios="\n".join(enunciatarios),
        actores="\n".join(actores_en_frase),
        heuristicas=heuristicas,
        ontologia=ontologia,
        prompt_base=prompt_emociones,
    )

    df_emociones, data = llamar_llm_y_parsear(
        modelo_llm=modelo_llm,
        prompt=prompt,
        schema=ListaEmocionesSchema,
        mostrar_prompt=mostrar_prompt,
        path_errores=path_errores,
        index=frase_idx,
    )

    df_emociones["frase_idx"] = frase_idx
    df_emociones["recorte_id"] = recorte_id
    df_emociones["codigo"] = codigo

    return df_emociones, prompt, data

def identificar_emociones_con_contexto(
    df_recortes,
    df_discursos,
    df_actores,
    schema,
    path_errores=None,
    output_path=None,
    modelo_llm=None,
    prompt_emociones=None,
    mostrar_prompts=False,
    guardar=True,
    mostrar_tiempo=False,
    checkpoint_interval=50,
    procesador=None,
    max_context=2,
):
    """
    Loop sobre frases de df_recortes para identificar emociones con contexto.
    """
    start_time = time.time()
    if modelo_llm is None:
        modelo_llm = get_model_ollama(modelo="gpt-oss:20b", temperature=0.0, output_format="text")
    if procesador is None:
        procesador = procesar_una_frase

    resultados = []

    for i in tqdm(range(len(df_recortes))):
        try:
            df_emociones, prompt, data = procesador(
                frase_idx=i,
                df_recortes=df_recortes,
                df_discursos=df_discursos,
                df_actores=df_actores,
                modelo_llm=modelo_llm,
                prompt_emociones=prompt_emociones,
                schema=schema,
                mostrar_prompt=mostrar_prompts,
                max_context=max_context,
                path_errores=path_errores,
            )
            resultados.append(df_emociones)

            if guardar and output_path and checkpoint_interval and (i + 1) % checkpoint_interval == 0:
                df_parcial = pd.concat(resultados, ignore_index=True)
                checkpoint_path = Path(output_path)
                checkpoint_path = checkpoint_path.with_name(checkpoint_path.stem + "_checkpoint.csv")
                guardar_csv(df_parcial, checkpoint_path)

        except Exception as e:
            logging.warning(f"[identificar_emociones_con_contexto] Error en frase_idx={i}: {e}")
            continue

    if not resultados:
        raise ValueError("No se generaron resultados. Verificá si hubo errores.")

    df_resultado = pd.concat(resultados, ignore_index=True)
    if guardar and output_path:
        guardar_csv(df_resultado, output_path)

    if mostrar_tiempo:
        mostrar_tiempo_procesamiento(start_time, mensaje="Tiempo de identificar_emociones_con_contexto")

    return df_resultado