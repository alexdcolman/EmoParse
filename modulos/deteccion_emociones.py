# deteccion_emociones.py

# IMPORTS Y FUNCIONES BASE

import os
import re
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
from modulos.modelo import get_model_ollama_par
from modulos.schemas import ListaEmocionesSchema
from modulos.paths import BASE_DIR
from modulos.tipos_discurso import diccionario_tipos_discurso

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
    prompt_base,
    diccionario=None,
    titulo=""
):
    """
    Arma el prompt para pedirle al LLM identificación de emociones discursivas.
    """
    return limpiar_prompt(
        prompt_base.format(
            titulo=titulo,
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
            actores=actores,
            diccionario=json.dumps(diccionario, indent=2, ensure_ascii=False) if diccionario else ""
        )
    )

def extraer_contexto(df_recortes, frase_idx, window=3):
    idx_inicio = max(frase_idx - window, 0)
    idx_fin = min(frase_idx + window, len(df_recortes) - 1)
    # 🔹 usar iloc para asegurar posiciones absolutas
    return df_recortes.iloc[idx_inicio:idx_fin+1]["texto_limpio"].tolist()

def obtener_metadatos(df_discursos, df_actores, codigo):
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
    
    titulo = fila.get("titulo", "")
    return fila, enunciatarios, actores, titulo

def llamar_llm_y_parsear(
    modelo_llm, prompt, schema, mostrar_prompt=False, path_errores=None, index=None, recorte_id=None
):
    try:
        campos = {"INDEX": str(index) if index is not None else None}
        if recorte_id is not None:
            campos["RECORTE_ID"] = str(recorte_id)

        data = analizar_generico(
            modelo_llm=modelo_llm,
            prompt_base=prompt,
            campos=campos,
            default=[],
            schema=schema,
            mostrar_prompts=mostrar_prompt,
            path_errores=path_errores,
            delay_between_calls=0.3,
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
        if "root" in df.columns:
            df = df.drop(columns=["root"])
        return df, lista

    except Exception as e:
        logging.warning(f"[llm_parse_emociones] Error inesperado en index={index}: {e}")
        columnas = list(schema.__fields__.keys())
        return pd.DataFrame(columns=columnas), []

def procesar_una_frase(
    recorte_id,
    df_recortes,
    df_discursos,
    df_actores,
    modelo_llm,
    prompt_emociones,
    schema,
    mostrar_prompt=False,
    max_context=2,
    path_errores=None,
    diccionario=None
):
    """
    Reprocesa una frase identificada por su recorte_id en lugar de usar frase_idx.
    """
    # buscar la fila correspondiente al recorte_id
    fila = df_recortes[df_recortes["recorte_id"].astype(str) == str(recorte_id)]
    if fila.empty:
        raise ValueError(f"recorte_id={recorte_id} no encontrado en df_recortes")
    fila = fila.iloc[0]

    frase = fila["texto_limpio"]
    codigo = fila["codigo"]

    # obtener contexto alrededor de la frase
    idx_real = fila.name  # posición absoluta en df_recortes
    frases_contexto = extraer_contexto(df_recortes, idx_real, window=max_context)

    # obtener metadatos
    fila_disc, enunciatarios, actores, titulo = obtener_metadatos(df_discursos, df_actores, codigo)

    # actores detectados exactamente para esa frase
    actores_en_frase = df_actores[df_actores["recorte_id"].astype(str) == str(recorte_id)]["actor"].dropna().tolist()
    actores_prompt = ", ".join(actores_en_frase) if actores_en_frase else ""

    # cargar heurísticas y ontología
    heuristicas_path = Path(BASE_DIR) / "modulos" / "heuristicas" / "inferencia_emociones.txt"
    heuristicas = cargar_heuristicas(path=str(heuristicas_path))
    ontologia_path = Path(BASE_DIR) / "modulos" / "ontologia" / "emociones.json"
    ontologia = json.dumps(cargar_ontologia(path=str(ontologia_path)), indent=2, ensure_ascii=False)

    # construir prompt
    prompt = construir_prompt_emociones(
        frase=frase,
        frases_contexto=frases_contexto,
        titulo=titulo,
        resumen_global=fila_disc.get("resumen", ""),
        tipo_discurso=fila_disc.get("tipo_discurso", ""),
        fecha=fila_disc.get("fecha", ""),
        lugar_justificacion=fila_disc.get("lugar_justificacion", ""),
        enunciador=fila_disc.get("enunciador_actor", ""),
        enunciatarios="\n".join(enunciatarios),
        actores=actores_prompt,
        heuristicas=heuristicas,
        ontologia=ontologia,
        prompt_base=prompt_emociones,
        diccionario=diccionario
    )

    # llamar al LLM
    df_emociones, data = llamar_llm_y_parsear(
        modelo_llm=modelo_llm,
        prompt=prompt,
        schema=schema,
        mostrar_prompt=mostrar_prompt,
        path_errores=path_errores,
        index=idx_real,
        recorte_id=recorte_id,
    )

    # asignar columnas finales correctas
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
    diccionario=None,
):
    start_time = time.time()
    if modelo_llm is None:
        modelo_llm = get_model_ollama_par(modelo="gpt-oss:20b", temperature=0.0, output_format="text")
    if procesador is None:
        procesador = procesar_una_frase

    resultados = []

    # recorrer recorte_id en lugar de índice
    for recorte_id in tqdm(df_recortes["recorte_id"].astype(str)):
        try:
            df_emociones, prompt, data = procesador(
                recorte_id=recorte_id,
                df_recortes=df_recortes,
                df_discursos=df_discursos,
                df_actores=df_actores,
                modelo_llm=modelo_llm,
                prompt_emociones=prompt_emociones,
                schema=schema,
                mostrar_prompt=mostrar_prompts,
                max_context=max_context,
                path_errores=path_errores,
                diccionario=diccionario,
            )
            if not df_emociones.empty:
                resultados.append(df_emociones)

            # --- Guardado incremental ---
            if guardar and output_path and checkpoint_interval and len(resultados) >= checkpoint_interval:
                df_parcial = pd.concat(resultados, ignore_index=True)
                checkpoint_path = Path(output_path)
                checkpoint_path = checkpoint_path.with_name(checkpoint_path.stem + "_checkpoint.csv")
                guardar_csv(df_parcial, checkpoint_path)
                resultados = []  # limpiar memoria
                logging.info(f"[checkpoint] Guardado parcial hasta recorte_id={recorte_id}")

        except Exception as e:
            logging.warning(f"[identificar_emociones_con_contexto] Error en recorte_id={recorte_id}: {e}")
            continue

    # --- Guardado final de lo que quede ---
    df_resultado = pd.concat(resultados, ignore_index=True) if resultados else pd.DataFrame()
    if guardar and output_path and not df_resultado.empty:
        guardar_csv(df_resultado, output_path)

    if mostrar_tiempo:
        mostrar_tiempo_procesamiento(start_time, mensaje="Tiempo de identificar_emociones_con_contexto")

    return df_resultado

# NUEVAS FUNCIONES ESPECIALIZADAS

def identificar_emociones_enunciador(**kwargs):
    return identificar_emociones_con_contexto(
        prompt_emociones=kwargs.pop("prompt_emociones"),
        **kwargs
    )

def identificar_emociones_enunciatarios(**kwargs):
    return identificar_emociones_con_contexto(
        prompt_emociones=kwargs.pop("prompt_emociones"),
        **kwargs
    )

def identificar_emociones_actores(**kwargs):
    return identificar_emociones_con_contexto(
        prompt_emociones=kwargs.pop("prompt_emociones"),
        **kwargs
    )

# Helper pequeño (local)
def _add_suffix_to_path(path, suffix):
    """Si path es None devuelve None. Si es str, inserta _suffix antes de la extensión."""
    if not path:
        return None
    p = Path(path)
    return str(p.with_name(f"{p.stem}_{suffix}{p.suffix}"))

# FUNCIÓN INTEGRADORA

def identificar_emociones_todas(
    df_recortes,
    df_discursos,
    df_actores,
    schema,
    modelo_llm,
    prompt_enunciador,
    prompt_enunciatarios,
    prompt_actores,
    diccionario=None,
    **kwargs
):
    output_path_base = kwargs.pop("output_path", None)
    path_errores_base = kwargs.pop("path_errores", None)

    resultados = {}

    # Enunciador
    out_enunciador = _add_suffix_to_path(output_path_base, "enunciador")
    err_enunciador = _add_suffix_to_path(path_errores_base, "enunciador")
    resultados["enunciador"] = identificar_emociones_con_contexto(
        df_recortes=df_recortes,
        df_discursos=df_discursos,
        df_actores=df_actores,
        schema=schema,
        modelo_llm=modelo_llm,
        prompt_emociones=prompt_enunciador,
        path_errores=err_enunciador,
        output_path=out_enunciador,
        diccionario=None,
        **kwargs
    )

    # Enunciatarios
    out_enunciatarios = _add_suffix_to_path(output_path_base, "enunciatarios")
    err_enunciatarios = _add_suffix_to_path(path_errores_base, "enunciatarios")
    resultados["enunciatarios"] = identificar_emociones_con_contexto(
        df_recortes=df_recortes,
        df_discursos=df_discursos,
        df_actores=df_actores,
        schema=schema,
        modelo_llm=modelo_llm,
        prompt_emociones=prompt_enunciatarios,
        diccionario=diccionario,
        path_errores=err_enunciatarios,
        output_path=out_enunciatarios,
        **kwargs
    )

    # Actores
    out_actores = _add_suffix_to_path(output_path_base, "actores")
    err_actores = _add_suffix_to_path(path_errores_base, "actores")
    resultados["actores"] = identificar_emociones_con_contexto(
        df_recortes=df_recortes,
        df_discursos=df_discursos,
        df_actores=df_actores,
        schema=schema,
        modelo_llm=modelo_llm,
        prompt_emociones=prompt_actores,
        path_errores=err_actores,
        output_path=out_actores,
        diccionario=None,
        **kwargs
    )

    return resultados