# --- Función de identificación de actores robusta ---

import os
import json
import time
import logging
import pandas as pd
from tqdm import tqdm
from pydantic import ValidationError, parse_obj_as

from modulos.recursos import cargar_heuristicas, cargar_ontologia, limpiar_prompt, analizar_generico
from modulos.parsers import extraer_texto_respuesta
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

def llamar_llm_y_parsear(modelo_llm, prompt, schema, mostrar_prompt=False):
    try:
        data = analizar_generico(
            modelo_llm=modelo_llm,
            prompt_base=prompt,
            campos={},  
            default=[],
            schema=schema,
            mostrar_prompts=mostrar_prompt
        )

        # --- Extraer lista interna si es RootModel ---
        if data:
            # Si es lista (ya parseado correctamente)
            if isinstance(data, list):
                lista_actores = data
            # Si es RootModel (Pydantic v2)
            elif hasattr(data, "root"):
                lista_actores = data.root
            # Si es tuple (por compatibilidad con versiones antiguas)
            elif isinstance(data, tuple):
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
        logging.warning(f"[llm_parse] Error: {e}")
        columnas = list(ActorSchema.__fields__.keys())
        return pd.DataFrame(columns=columnas), []


def procesar_una_frase(
    frase_idx, df_recortes, df_enunc, modelo_llm, prompt_actores, mostrar_prompt=False
):
    frase = df_recortes.loc[frase_idx, "texto_limpio"]
    recorte_id = df_recortes.loc[frase_idx, "recorte_id"]
    codigo = df_recortes.loc[frase_idx, "codigo"]

    frases_contexto = extraer_contexto(df_recortes, frase_idx)
    fila_enunc, enunciatarios = obtener_metadatos(df_enunc, codigo)
    
    heuristicas = cargar_heuristicas()
    ontologia = json.dumps(cargar_ontologia(), indent=2, ensure_ascii=False)

    prompt = construir_prompt(
        frase, frases_contexto, fila_enunc.get("resumen", ""),
        fila_enunc.get("tipo_discurso", ""), fila_enunc.get("fecha", ""),
        fila_enunc.get("lugar_justificacion", ""), fila_enunc.get("enunciador_actor", ""),
        "\n".join(enunciatarios), heuristicas, ontologia, prompt_base=prompt_actores
    )

    df_actores, data = llamar_llm_y_parsear(modelo_llm, prompt, ListaActoresSchema, mostrar_prompt)

    df_actores["frase_idx"] = frase_idx
    df_actores["recorte_id"] = recorte_id
    df_actores["codigo"] = codigo

    return df_actores, prompt, data

# -------------------- IDENTIFICAR ACTORES CON CONTEXTO --------------------

def identificar_actores_con_contexto(
    df_recortes,
    df_enunc,
    path_errores=None,
    output_path=None,
    modelo_llm=None,
    mostrar_prompts=False,
    guardar=True,
    mostrar_tiempo=False,
    checkpoint_interval=50,
    procesador=None,
    prompt_actores=None
):
    """
    Identifica actores por frase usando un LLM con StructuredOutputParser.
    Permite guardar checkpoints y mostrar tiempos.
    """
    start_time = time.time()

    if modelo_llm is None:
        modelo_llm = get_model_ollama(modelo="gpt-oss:20b", temperature=0.0, output_format="text")

    if procesador is None:
        procesador = procesar_una_frase

    resultados = []

    for i in tqdm(range(len(df_recortes))):
        prompt = None
        data = None
        try:
            df_actores, prompt, data = procesador(
                frase_idx=i,
                df_recortes=df_recortes,
                df_enunc=df_enunc,
                modelo_llm=modelo_llm,
                mostrar_prompt=mostrar_prompts,
                prompt_actores=prompt_actores
            )
            resultados.append(df_actores)

            # --- checkpoint parcial ---
            if guardar and output_path and checkpoint_interval and (i + 1) % checkpoint_interval == 0:
                df_parcial = pd.concat(resultados, ignore_index=True)
                checkpoint_path = output_path.replace(".csv", "_checkpoint.csv")
                guardar_csv(df_parcial, checkpoint_path)

        except Exception as e:
            logging.warning(f"[identificar_actores_con_contexto] Error en frase_idx={i}: {e}")
            registro_error = {
                "frase_idx": i,
                "recorte_id": df_recortes.loc[i, "recorte_id"],
                "codigo": df_recortes.loc[i, "codigo"],
                "error": str(e),
                "respuesta_cruda": str(data) if data else "",
                "prompt_usado": prompt if prompt else ""
            }
            if path_errores:
                with open(path_errores, "a", encoding="utf-8") as f:
                    f.write(json.dumps(registro_error, ensure_ascii=False) + "\n")

    if not resultados:
        raise ValueError("No se generaron resultados. Verificá si hubo errores.")

    df_resultado = pd.concat(resultados, ignore_index=True)

    # --- guardado final ---
    if guardar and output_path:
        guardar_csv(df_resultado, output_path)

    # --- métrica de tiempo ---
    if mostrar_tiempo:
        mostrar_tiempo_procesamiento(start_time, mensaje="Tiempo de identificar_actores_con_contexto")

    return df_resultado


# Función de reprocesamiento de errores

import os
import json
import pandas as pd

def archivo_existe(ruta):
    return os.path.exists(ruta)

def cargar_errores(path_errores):
    errores = []
    with open(path_errores, "r", encoding="utf-8") as f:
        for line in f:
            try:
                errores.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return errores

def guardar_errores(path, errores):
    with open(path, "w", encoding="utf-8") as f:
        for err in errores:
            f.write(json.dumps(err, ensure_ascii=False) + "\n")

def reprocesar_errores_identificacion(
    df_recortes,
    df_enunc,
    path_errores,
    path_salida,
    prompt_template,
    intento=1,
    evitar_duplicados=True,
    modelo_llm=None,
    mostrar_prompts=False,
):
    errores = cargar_errores(path_errores)

    if not errores:
        print("✅ No hay errores para reprocesar.")
        return

    print(f"🔁 Reprocesando {len(errores)} errores...")

    resultados = []
    errores_persistentes = []

    for registro in errores:
        frase_idx = registro.get("frase_idx")
        recorte_id = registro.get("recorte_id")
        codigo = registro.get("codigo")

        try:
            # Verificación y filtrado robusto
            if frase_idx not in df_recortes.index:
                raise KeyError(f"frase_idx={frase_idx} no está en df_recortes")

            fila = df_recortes.loc[frase_idx]
            if fila["recorte_id"] != recorte_id or fila["codigo"] != codigo:
                raise ValueError(f"Datos inconsistentes en frase_idx={frase_idx}")

            df_recorte_filtrado = pd.DataFrame([fila])
            df_enunc_filtrado = df_enunc[df_enunc["codigo"] == codigo]
            if df_enunc_filtrado.empty:
                raise ValueError(f"No se encontró código={codigo} en df_enunc")

            # Procesar con el mismo pipeline original
            df_result, prompt, respuesta = procesar_una_frase(
                frase_idx=frase_idx,
                df_recortes=df_recorte_filtrado,
                df_enunc=df_enunc_filtrado,
                prompt_template=prompt_template,
                modelo_llm=modelo_llm,
                mostrar_prompt=mostrar_prompts
            )

            resultados.append(df_result)

        except Exception as e:
            print(f"❌ Falló nuevamente en recorte_id={recorte_id}: {e}")
            registro_error = {
                "frase_idx": frase_idx,
                "recorte_id": recorte_id,
                "codigo": codigo,
                "error": str(e)
            }
            errores_persistentes.append(registro_error)

    # Combinar resultados
    if resultados:
        df_total = pd.concat(resultados, ignore_index=True)
    else:
        df_total = pd.DataFrame()

    # Eliminar duplicados si corresponde
    if evitar_duplicados and archivo_existe(path_salida) and not df_total.empty:
        df_existente = pd.read_csv(path_salida, encoding="utf-8-sig")
        if "frase_idx" in df_existente.columns:
            idx_existentes = set(df_existente["frase_idx"])
            df_total = df_total[~df_total["frase_idx"].isin(idx_existentes)]

    # Guardar resultados nuevos
    if not df_total.empty:
        modo = "a" if archivo_existe(path_salida) else "w"
        df_total.to_csv(path_salida, mode=modo, header=not archivo_existe(path_salida), index=False, encoding="utf-8-sig")
        print(f"✅ Agregados {len(df_total)} nuevos registros a '{path_salida}'")
    else:
        print("⚠️ Ninguna respuesta recuperable en este intento.")

    # Guardar errores persistentes
    if errores_persistentes:
        nuevo_path_errores = f"{os.path.splitext(path_errores)[0]}_intento{intento}.jsonl"
        guardar_errores(nuevo_path_errores, errores_persistentes)
        print(f"📄 Guardados {len(errores_persistentes)} errores persistentes en '{nuevo_path_errores}'")
    else:
        print("✅ Todos los errores fueron corregidos.")



# Función de postprocesamiento

import json
import re
import os
import pandas as pd
from tqdm import tqdm
from langchain.schema import HumanMessage
from modulos.modelo import get_model_ollama
from modulos.recursos import BASE_DIR, cargar_prompt_template, cargar_ontologia

def validacion_actores(
    path_df_actores,
    path_df_recortes,
    path_salida_validos,
    path_salida_excluidos
):
    # --- 1. Cargar archivos
    df_actores = pd.read_csv(path_df_actores)
    df_recortes = pd.read_csv(path_df_recortes)
    ontologia = json.dumps(cargar_ontologia(), indent=2, ensure_ascii=False)
    prompt_template_path = os.path.join(BASE_DIR, "prompts", "validar_actores.txt")
    prompt_template = cargar_prompt_template(prompt_template_path)

    validos = []
    excluidos = []

    # --- 2. Iterar por frase con tqdm
    for recorte_id, grupo in tqdm(df_actores.groupby("recorte_id"), desc="Procesando recortes"):
        frase = df_recortes.loc[df_recortes["recorte_id"] == recorte_id, "texto_limpio"]
        if frase.empty:
            print(f"⚠️ No se encontró texto para recorte_id={recorte_id}")
            continue
        texto = frase.values[0]
        actores = grupo.to_dict(orient="records")

        for actor_data in tqdm(actores, desc=f"Validando actores recorte {recorte_id}", leave=False):
            actor = actor_data["actor"]
            prompt = prompt_template.format(
                actor=actor,
                frase=texto,
                ontologia=ontologia
            )

            # --- 5. Llamar al modelo
            try:
                respuesta = llm([HumanMessage(content=prompt)]).content
                contenido = re.sub(r"^```json\s*|\s*```$", "", respuesta.strip(), flags=re.DOTALL)
            except Exception as e:
                print(f"❌ Error validando actor '{actor}' en '{recorte_id}': {e}")
                continue

            # --- 6. Clasificar respuesta
            contenido_lower = contenido.lower()
            if "válido" in contenido_lower:
                print(f"{recorte_id} - {actor}: ✅ válido")
                validos.append(actor_data)
            elif "excluido" in contenido_lower or "no válido" in contenido_lower:
                print(f"{recorte_id} - {actor}: ❌ excluido")
                excluidos.append(actor_data)
            else:
                print(f"{recorte_id} - {actor}: ⚠️ respuesta ambigua")
                excluidos.append(actor_data)

    # --- 3. Guardar resultados
    if validos:
        pd.DataFrame(validos).to_csv(path_salida_validos, index=False)
        print(f"✅ Guardados {len(validos)} actores validados en '{path_salida_validos}'")

    if excluidos:
        pd.DataFrame(excluidos).to_csv(path_salida_excluidos, index=False)
        print(f"📄 Guardados {len(excluidos)} actores excluidos en '{path_salida_excluidos}'")
    else:
        print("✅ No hubo actores excluidos.")
