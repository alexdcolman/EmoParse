import os
import json
import pandas as pd
import modulos.paths as paths
from datetime import datetime
from modulos.recursos import ErrorLogger
from modulos.deteccion_emociones import procesar_una_frase

def reprocesar_errores_emociones(
    df_recortes,
    df_discursos,
    df_actores,
    path_errores,
    path_salida,
    prompt_emociones,
    schema,
    intento=1,
    modelo_llm=None,
    mostrar_prompts=False,
    max_context=2
):
    """
    Reprocesa errores de identificación de emociones usando directamente recorte_id (mayúscula o minúscula).

    - path_errores: archivo JSONL con errores previos.
    - df_recortes: DataFrame original con todos los recortes (columna recorte_id).
    - df_discursos: DataFrame con metadata de discursos.
    - df_actores: DataFrame con actores identificados.
    - path_salida: CSV donde guardar resultados de reprocesos exitosos.
    - prompt_emociones: prompt base para identificación de emociones.
    - schema: esquema pydantic para parsear respuesta del LLM.
    - intento: número de intento de reprocesamiento.
    - modelo_llm: modelo LLM a usar.
    - mostrar_prompts: si True, imprime los prompts enviados.
    - max_context: cantidad de frases de contexto a usar.
    """

    if not os.path.exists(path_errores):
        print(f"[reprocesar_errores_emociones] No existe {path_errores}")
        return pd.DataFrame()

    # --- cargar errores ---
    with open(path_errores, "r", encoding="utf-8-sig") as f:
        errores = [json.loads(line) for line in f if line.strip()]

    if not errores:
        print("[reprocesar_errores_emociones] No hay errores que reprocesar.")
        return pd.DataFrame()

    resultados = []
    errores_persistentes = []

    for reg in errores:
        campos = reg.get("campos", {}) or {}
        recorte_id = reg.get("recorte_id") or reg.get("RECORTE_ID") or campos.get("recorte_id") or campos.get("RECORTE_ID")
        codigo = reg.get("codigo") or campos.get("codigo")

        if recorte_id is None:
            print(f"[⚠️] Error sin recorte_id, se omite: {reg}")
            errores_persistentes.append(reg)
            continue

        fila = df_recortes[df_recortes["recorte_id"].astype(str) == str(recorte_id)]
        if fila.empty:
            print(f"[⚠️] recorte_id={recorte_id} no encontrado en df_recortes")
            errores_persistentes.append(reg)
            continue

        try:
            frase_idx_real = fila.index[0]

            # Llamar a procesar_una_frase
            df_emociones, prompt_usado, data = procesar_una_frase(
                recorte_id=recorte_id,
                df_recortes=df_recortes,
                df_discursos=df_discursos,
                df_actores=df_actores,
                modelo_llm=modelo_llm,
                prompt_emociones=prompt_emociones,
                schema=schema,
                mostrar_prompt=mostrar_prompts,
                max_context=max_context,
            )

            if not df_emociones.empty:
                # Asignar columnas finales
                df_emociones["recorte_id"] = recorte_id
                df_emociones["codigo"] = codigo if codigo is not None else fila.iloc[0]["codigo"]
                resultados.append(df_emociones)
                print(f"✅ Reprocesado recorte_id={recorte_id} (frase_idx={frase_idx_real})")
            else:
                reg["error_reproceso"] = "Resultado vacío/inválido"
                reg["timestamp_reproceso"] = datetime.now().isoformat()
                errores_persistentes.append(reg)
                print(f"[⚠️] Resultado vacío/inválido recorte_id={recorte_id}")

        except Exception as e:
            print(f"[❌] Error persistente recorte_id={recorte_id}: {e}")
            reg["error_reproceso"] = str(e)
            reg["timestamp_reproceso"] = datetime.now().isoformat()
            errores_persistentes.append(reg)

    # --- guardar reprocesos exitosos ---
    if resultados:
        df_out = pd.concat(resultados, ignore_index=True)
        if os.path.exists(path_salida):
            df_out.to_csv(path_salida, mode="a", header=False, index=False, encoding="utf-8-sig")
        else:
            df_out.to_csv(path_salida, index=False, encoding="utf-8-sig")
        print(f"[✔] Guardados {len(df_out)} reprocesos en {path_salida}")
        # Mostrar print incorporado de filas reprocesadas
        print(f"✅ Reprocesadas {len(df_out)} filas de emociones.")

    # --- reescribir archivo de errores solo con los persistentes ---
    with open(path_errores, "w", encoding="utf-8-sig") as f:
        for reg in errores_persistentes:
            reg["reproceso_intento"] = intento
            f.write(json.dumps(reg, ensure_ascii=False) + "\n")
    if errores_persistentes:
        print(f"[ℹ] {len(errores_persistentes)} errores persisten en {path_errores}")
    else:
        print(f"[ℹ] Todos los errores fueron reprocesados con éxito. {path_errores} queda vacío.")

    return pd.concat(resultados, ignore_index=True) if resultados else pd.DataFrame()

