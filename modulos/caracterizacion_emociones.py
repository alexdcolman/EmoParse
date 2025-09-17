# caracterizacion_emociones.py

# IMPORTS Y FUNCIONES BASE

import os
import re
import json
import time
import logging
import pandas as pd
from tqdm import tqdm
from pathlib import Path

# Recursos internos
from modulos.recursos import (
    cargar_ontologia,
    limpiar_prompt,
    analizar_generico,
    cargar_heuristicas,
)
from modulos.utils_io import guardar_csv, mostrar_tiempo_procesamiento
from modulos.modelo import get_model_ollama_par
from modulos.paths import BASE_DIR
from modulos.tipos_discurso import diccionario_tipos_discurso
from modulos.prompts import PROMPT_FORIA, PROMPT_DOMINANCIA, PROMPT_INTENSIDAD, PROMPT_FUENTE
from modulos.schemas import ForiaSchema, DominanciaSchema, IntensidadSchema, FuenteSchema

def construir_prompt_caracterizacion(frase, experienciador, justificacion, recorte_id,
                                     tipo_emocion, heuristicas, ontologia, prompt_base):
    return limpiar_prompt(
        prompt_base.format(
            frase=frase,
            experienciador=experienciador,
            justificacion=justificacion,
            recorte_id=recorte_id,
            tipo_emocion=tipo_emocion,
            heuristicas=heuristicas,
            ontologia=ontologia
        )
    )

def llamar_llm_y_parsear_caracterizacion(modelo_llm, prompt, campos, mostrar_prompt=False, path_errores=None, index=None, schema=None):
    try:
        data = analizar_generico(
            modelo_llm=modelo_llm,
            prompt_base=prompt,
            campos=campos,
            default={},
            mostrar_prompts=mostrar_prompt,
            path_errores=path_errores,
            delay_between_calls=0.3,
            etiqueta_log=f"Caracterizacion idx={index}",
            schema=schema
        )
        if data:
            if hasattr(data, "dict"):  # si es un objeto Pydantic
                row = data.dict()
            else:
                row = data
            df = pd.DataFrame([row])
        else:
            df = pd.DataFrame()
        return df, data
    except Exception as e:
        logging.warning(f"[llm_parse_caracterizacion] Error en index={index}: {e}")
        return pd.DataFrame(), {}


def procesar_una_emocion(df_emociones, df_recortes, idx, modelo_llm, prompt_base,
                          heuristicas_path, ontologia_path, mostrar_prompt=False,
                          path_errores=None):
    fila = df_emociones.iloc[idx]
    recorte_id = fila["recorte_id"]
    tipo_emocion = fila["tipo_emocion"]
    frase_series = df_recortes[df_recortes["recorte_id"] == recorte_id]["texto_limpio"]

    if frase_series.empty:
        logging.warning(f"[procesar_una_emocion] No se encontró recorte_id={recorte_id}")
        return pd.DataFrame(), {}

    frase = frase_series.values[0]
    experienciador = fila["experienciador"]
    justificacion = fila["justificacion"]

    heuristicas = cargar_heuristicas(heuristicas_path)
    ontologia = json.dumps(cargar_ontologia(ontologia_path), indent=2, ensure_ascii=False)

    prompt = construir_prompt_caracterizacion(
        frase=frase,
        experienciador=experienciador,
        justificacion=justificacion,
        recorte_id=recorte_id,
        tipo_emocion=tipo_emocion,
        heuristicas=heuristicas,
        ontologia=ontologia,
        prompt_base=prompt_base
    )

    if prompt_base == PROMPT_FORIA:
        schema_class = ForiaSchema
    elif prompt_base == PROMPT_DOMINANCIA:
        schema_class = DominanciaSchema
    elif prompt_base == PROMPT_INTENSIDAD:
        schema_class = IntensidadSchema
    elif prompt_base == PROMPT_FUENTE:
        schema_class = FuenteSchema

    df_out, data = llamar_llm_y_parsear_caracterizacion(
        modelo_llm=modelo_llm,
        prompt=prompt,
        campos={"INDEX": str(idx)},
        mostrar_prompt=mostrar_prompt,
        path_errores=path_errores,
        index=idx,
        schema=schema_class
    )

    if df_out.empty:
        return pd.DataFrame(), {}

    df_out["recorte_id"] = recorte_id
    df_out["experienciador"] = experienciador
    df_out["tipo_emocion"] = tipo_emocion

    return df_out, data

def caracterizar_variable(df_emociones, df_recortes, modelo_llm, prompt_base,
                          heuristicas_path, ontologia_path,
                          mostrar_prompt=False, path_errores=None,
                          output_path=None, guardar=True,
                          checkpoint_interval=10):
    import os

    contador = 0

    for idx in tqdm(range(len(df_emociones))):
        df_out, _ = procesar_una_emocion(
            df_emociones=df_emociones,
            df_recortes=df_recortes,
            idx=idx,
            modelo_llm=modelo_llm,
            prompt_base=prompt_base,
            heuristicas_path=heuristicas_path,
            ontologia_path=ontologia_path,
            mostrar_prompt=mostrar_prompt,
            path_errores=path_errores
        )
        if not df_out.empty and guardar and output_path:
            df_out.to_csv(
                output_path,
                index=False,
                mode='a',
                header=not os.path.exists(output_path),
                encoding="utf-8-sig"
            )

        contador += 1
        if checkpoint_interval and contador % checkpoint_interval == 0:
            logging.info(f"[checkpoint] Procesadas {contador} filas")

    # Ya no devuelvo nada pesado, solo el path
    return output_path

# FUNCIONES ESPECÍFICAS

def caracterizar_foria(df_emociones, df_recortes, modelo_llm, mostrar_prompt=False, path_errores=None,
                       output_path=None, guardar=True, checkpoint_interval=10):
    heuristicas_path = Path("modulos/heuristicas/foria.txt")
    ontologia_path = Path("modulos/ontologia/foria.json")
    return caracterizar_variable(
        df_emociones, df_recortes, modelo_llm, PROMPT_FORIA,
        heuristicas_path, ontologia_path,
        mostrar_prompt=mostrar_prompt,
        path_errores=path_errores,
        output_path=output_path,
        guardar=guardar,
        checkpoint_interval=checkpoint_interval
    )

def caracterizar_dominancia(df_emociones, df_recortes, modelo_llm, mostrar_prompt=False, path_errores=None,
                            output_path=None, guardar=True, checkpoint_interval=10):
    heuristicas_path = Path("modulos/heuristicas/dominancia.txt")
    ontologia_path = Path("modulos/ontologia/dominancia.json")
    return caracterizar_variable(
        df_emociones, df_recortes, modelo_llm, PROMPT_DOMINANCIA,
        heuristicas_path, ontologia_path,
        mostrar_prompt=mostrar_prompt,
        path_errores=path_errores,
        output_path=output_path,
        guardar=guardar,
        checkpoint_interval=checkpoint_interval
    )

def caracterizar_intensidad(df_emociones, df_recortes, modelo_llm, mostrar_prompt=False, path_errores=None,
                            output_path=None, guardar=True, checkpoint_interval=10):
    heuristicas_path = Path("modulos/heuristicas/intensidad.txt")
    ontologia_path = Path("modulos/ontologia/intensidad.json")
    return caracterizar_variable(
        df_emociones, df_recortes, modelo_llm, PROMPT_INTENSIDAD,
        heuristicas_path, ontologia_path,
        mostrar_prompt=mostrar_prompt,
        path_errores=path_errores,
        output_path=output_path,
        guardar=guardar,
        checkpoint_interval=checkpoint_interval
    )

def caracterizar_fuente(df_emociones, df_recortes, modelo_llm, mostrar_prompt=False, path_errores=None,
                        output_path=None, guardar=True, checkpoint_interval=10):
    heuristicas_path = Path("modulos/heuristicas/fuente.txt")
    ontologia_path = Path("modulos/ontologia/fuente.json")
    return caracterizar_variable(
        df_emociones, df_recortes, modelo_llm, PROMPT_FUENTE,
        heuristicas_path, ontologia_path,
        mostrar_prompt=mostrar_prompt,
        path_errores=path_errores,
        output_path=output_path,
        guardar=guardar,
        checkpoint_interval=checkpoint_interval
    )

# FUNCIÓN UNIFICADA PARA PIPELINE

def caracterizar_emociones_todas(df_emociones, df_recortes, modelo_llm,
                                 mostrar_prompt=False, path_errores=None,
                                 output_path=None, guardar=True,
                                 checkpoint_interval=None,
                                 carpeta_salida=None):
    import os

    os.makedirs(carpeta_salida, exist_ok=True)

    csv_paths = {
        "foria": os.path.join(carpeta_salida, "foria.csv"),
        "dominancia": os.path.join(carpeta_salida, "dominancia.csv"),
        "intensidad": os.path.join(carpeta_salida, "intensidad.csv"),
        "fuente": os.path.join(carpeta_salida, "fuente.csv")
    }

    # Procesar y generar los CSV parciales
    caracterizar_foria(df_emociones, df_recortes, modelo_llm,
                       mostrar_prompt=mostrar_prompt, path_errores=path_errores,
                       output_path=csv_paths["foria"], guardar=guardar,
                       checkpoint_interval=checkpoint_interval)

    caracterizar_dominancia(df_emociones, df_recortes, modelo_llm,
                            mostrar_prompt=mostrar_prompt, path_errores=path_errores,
                            output_path=csv_paths["dominancia"], guardar=guardar,
                            checkpoint_interval=checkpoint_interval)

    caracterizar_intensidad(df_emociones, df_recortes, modelo_llm,
                            mostrar_prompt=mostrar_prompt, path_errores=path_errores,
                            output_path=csv_paths["intensidad"], guardar=guardar,
                            checkpoint_interval=checkpoint_interval)

    caracterizar_fuente(df_emociones, df_recortes, modelo_llm,
                        mostrar_prompt=mostrar_prompt, path_errores=path_errores,
                        output_path=csv_paths["fuente"], guardar=guardar,
                        checkpoint_interval=checkpoint_interval)

    # Leer los parciales directamente desde disco
    resultados = {k: pd.read_csv(v, encoding="utf-8-sig") if os.path.exists(v) else pd.DataFrame()
                  for k, v in csv_paths.items()}

    # Renombrar columnas de justificación
    rename_map = {
        "foria": {"justificacion": "foria_justificacion"},
        "dominancia": {"justificacion": "dominancia_justificacion"},
        "intensidad": {"justificacion": "intensidad_justificacion"},
        "fuente": {"justificacion": "fuente_justificacion"}
    }
    for key, df in resultados.items():
        if not df.empty and key in rename_map:
            resultados[key] = df.rename(columns=rename_map[key])

    # Merge final
    keys = ["recorte_id", "experienciador", "tipo_emocion"]
    df_final = resultados["foria"]
    for key in ["dominancia", "intensidad", "fuente"]:
        if not resultados[key].empty:
            cols_nuevas = [c for c in resultados[key].columns if c not in df_final.columns or c in keys]
            df_final = df_final.merge(resultados[key][cols_nuevas], on=keys, how="outer")

    # Guardado final
    if guardar and output_path:
        guardar_csv(df_final, output_path)

    return {"final": df_final, **resultados}
