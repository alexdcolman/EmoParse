# reprocesamiento.py

import os
import json
import unidecode
import pandas as pd
import modulos.paths as paths
from datetime import datetime
from modulos.recursos import ErrorLogger, analizar_generico
from modulos.identificacion_actores import procesar_una_frase
from modulos.schemas import LugarSchema, TipoDiscursoSchema, EnunciacionSchema
from modulos.enunciacion import analizar_enunciacion
from modulos.metadatos import procesar_metadatos_llm

# Helpers
def _guardar_errores_persistentes(errores, path_errores, intento):
    """Guarda errores persistentes en un nuevo archivo _intentoX.jsonl"""
    nuevo_path = f"{os.path.splitext(path_errores)[0]}_intento{intento}.jsonl"
    if errores:
        ErrorLogger(nuevo_path).guardar_varios(errores, overwrite=True)
        print(f"📄 Guardados {len(errores)} errores persistentes en '{nuevo_path}'")
    else:
        # siempre creamos el archivo vacío
        open(nuevo_path, "w", encoding="utf-8-sig").close()
        print("✅ Todos los errores fueron corregidos. Archivo persistente vacío creado.")

def _get_index_from_reg(reg):
    """Extrae un índice entero desde varias claves posibles del registro."""
    for k in ("INDEX", "index", "_index", "fila_idx", "frase_idx"):
        v = reg.get(k)
        if v is not None:
            try:
                return int(v)
            except Exception:
                try:
                    return int(str(v).strip())
                except Exception:
                    continue
    return None

def _remove_successful_errors(logger, exitosos, path_errores):
    """Elimina del archivo original los errores que se corrigieron, siempre reescribiendo."""
    if not exitosos:
        return

    errores = logger.cargar()

    def same_err(a, b):
        ia = _get_index_from_reg(a)
        ib = _get_index_from_reg(b)
        if ia is None or ib is None or ia != ib:
            return False
        # comparar etiqueta solo si existe en ambos
        if "etiqueta" in a and "etiqueta" in b:
            return a["etiqueta"] == b["etiqueta"]
        return True

    filtrados = [err for err in errores if not any(same_err(err, e) for e in exitosos)]

    # reescribir siempre, incluso si no cambió la longitud
    with open(path_errores, "w", encoding="utf-8-sig") as f:
        for err in filtrados:
            f.write(json.dumps(err, ensure_ascii=False) + "\n")

# Reprocesar metadatos
def reprocesar_metadatos_nan(
    df_original,
    modelo_llm,
    diccionario,
    prompt_tipo,
    prompt_lugar,
    guardar=False,
    output_path=None,
    mostrar_prompts=False
):
    cols_tipo = ["tipo_discurso", "tipo_discurso_justificacion"]
    cols_lugar = ["lugar_ciudad","lugar_provincia","lugar_pais","lugar_justificacion"]

    df = df_original.copy()

    def is_empty(val):
        if pd.isna(val):
            return True
        if isinstance(val, str):
            val_norm = unidecode.unidecode(val.strip().lower())
            if val_norm in ["sin respuesta", "sin justificacion"]:
                return True
        return False

    mask_nan = df[cols_tipo + cols_lugar].applymap(is_empty).any(axis=1)
    if not mask_nan.any():
        print("✅ No se detectaron filas vacías o 'Sin respuesta/Sin justificación'.")
        return df_original.copy()

    df_a_reprocesar = df.loc[mask_nan].copy()
    df_restante = df.loc[~mask_nan].copy()
    print(f"🔁 Reprocesando {len(df_a_reprocesar)} filas con valores vacíos...")

    df_reprocesado = procesar_metadatos_llm(
        df=df_a_reprocesar,
        modelo_llm=modelo_llm,
        diccionario=diccionario,
        prompt_tipo=prompt_tipo,
        prompt_lugar=prompt_lugar,
        guardar=False,
        mostrar_prompts=mostrar_prompts
    )

    df_final = pd.concat([df_restante, df_reprocesado], ignore_index=True)

    if 'codigo' in df_final.columns:
        df_final = df_final.sort_values('codigo').reset_index(drop=True)

    if guardar and output_path:
        df_final.to_csv(output_path, index=False, encoding="utf-8-sig")
        print(f"✅ CSV actualizado guardado en {output_path}")

    return df_final

# Reprocesar enunciación
def reprocesar_enunciacion_nan(
    df_original,
    modelo_llm,
    diccionario,
    prompt_enunciacion,
    guardar=False,
    output_path=None,
    mostrar_prompts=False,
    path_errores=None
):
    import unidecode
    import pandas as pd
    from modulos.enunciacion import procesar_enunciacion_llm

    cols_enun = [c for c in df_original.columns if c.startswith("enunciador_") or c.startswith("enunciatario_")]
    df = df_original.copy()

    def is_empty(val):
        if pd.isna(val):
            return True
        if isinstance(val, str):
            val_norm = unidecode.unidecode(val.strip().lower())
            if val_norm in ["", "sin respuesta", "sin justificacion"]:
                return True
        return False

    mask_nan = df[cols_enun].applymap(is_empty).any(axis=1)
    if not mask_nan.any():
        print("✅ No se detectaron filas vacías o 'Sin respuesta/Sin justificación' en enunciación.")
        return df_original.copy()

    df_a_reprocesar = df.loc[mask_nan].copy()
    df_restante = df.loc[~mask_nan].copy()
    print(f"🔁 Reprocesando {len(df_a_reprocesar)} filas de enunciación con valores vacíos...")

    df_reprocesado = procesar_enunciacion_llm(
        df=df_a_reprocesar,
        modelo_llm=modelo_llm,
        diccionario=diccionario,
        prompt_enunciacion=prompt_enunciacion,
        guardar=False,
        mostrar_prompts=mostrar_prompts,
        path_errores=path_errores
    )

    df_final = pd.concat([df_restante, df_reprocesado], ignore_index=True)

    if "codigo" in df_final.columns:
        df_final = df_final.sort_values("codigo").reset_index(drop=True)

    if guardar and output_path:
        df_final.to_csv(output_path, index=False, encoding="utf-8-sig")
        print(f"✅ CSV actualizado guardado en {output_path}")

    return df_final

# Reprocesar errores de identificación de actores
def reprocesar_errores_identificacion(
    path_errores,
    df_recortes,
    df_enunc,
    path_salida,
    prompt_actores,
    modelo_llm,
    mostrar_prompts=False,
    max_context=500,
):
    """
    Reprocesa errores de identificación de actores usando directamente recorte_id.

    - path_errores: archivo JSONL con errores previos.
    - df_recortes: DataFrame original con todos los recortes (columna recorte_id).
    - df_enunc: DataFrame con enunciadores.
    - path_salida: CSV donde guardar resultados de reprocesos exitosos.
    - prompt_actores: prompt base para identificación de actores.
    - modelo_llm: modelo LLM a usar.
    - mostrar_prompts: si True, imprime los prompts enviados.
    - max_context: límite de caracteres para el recorte enviado al LLM.
    """

    if not os.path.exists(path_errores):
        print(f"[reprocesar_errores_identificacion] No existe {path_errores}")
        return

    # --- cargar errores ---
    with open(path_errores, "r", encoding="utf-8-sig") as f:
        errores = [json.loads(line) for line in f if line.strip()]

    if not errores:
        print("[reprocesar_errores_identificacion] No hay errores que reprocesar.")
        return

    resultados = []
    errores_persistentes = []

    for err in errores:
        recorte_id = err.get("campos", {}).get("RECORTE_ID")
        if recorte_id is None:
            print(f"[⚠️] Error sin recorte_id, se omite: {err}")
            errores_persistentes.append(err)
            continue

        # coincidencia robusta por string
        fila = df_recortes[df_recortes["recorte_id"].astype(str) == str(recorte_id)]
        if fila.empty:
            print(f"[⚠️] recorte_id={recorte_id} no encontrado en df_recortes")
            errores_persistentes.append(err)
            continue

        try:
            frase_idx_real = fila.index[0]

            df_actores, prompt, data = procesar_una_frase(
                frase_idx=frase_idx_real,
                df_recortes=df_recortes,
                df_enunc=df_enunc,
                prompt_actores=prompt_actores,
                modelo_llm=modelo_llm,
                mostrar_prompt=mostrar_prompts,
            )

            if not isinstance(df_actores, pd.DataFrame) or df_actores.empty:
                print(f"[⚠️] Resultado vacío para recorte_id={recorte_id}; se registra como persistente.")
                errores_persistentes.append(err)
                continue

            # eliminar columna transitoria 'frase_idx'
            if "frase_idx" in df_actores.columns:
                df_actores = df_actores.drop(columns=["frase_idx"])

            # forzar recorte_id correcto
            df_actores["recorte_id"] = recorte_id

            # asegurar que 'codigo' toma el valor correcto del recorte/discurso
            codigo_val = ""
            if "codigo" in df_recortes.columns:
                try:
                    codigo_val = df_recortes.loc[frase_idx_real, "codigo"]
                except Exception:
                    codigo_val = ""
            df_actores["codigo"] = codigo_val

            resultados.append(df_actores)

        except Exception as e:
            print(f"[❌] Error reprocesando recorte_id={recorte_id}: {e}")
            errores_persistentes.append(err)

    # --- guardar reprocesos exitosos ---
    if resultados:
        df_out = pd.concat(resultados, ignore_index=True)

        if "frase_idx" in df_out.columns:
            df_out = df_out.drop(columns=["frase_idx"])

        if os.path.exists(path_salida):
            try:
                df_existente = pd.read_csv(path_salida, nrows=0, encoding="utf-8-sig")
                existing_cols = df_existente.columns.tolist()
            except Exception:
                existing_cols = ["actor", "tipo", "modo", "justificacion", "recorte_id", "codigo"]
        else:
            existing_cols = ["actor", "tipo", "modo", "justificacion", "recorte_id", "codigo"]

        for col in existing_cols:
            if col not in df_out.columns:
                df_out[col] = ""

        df_out = df_out[existing_cols]

        if os.path.exists(path_salida):
            df_out.to_csv(path_salida, mode="a", header=False, index=False, encoding="utf-8-sig")
        else:
            df_out.to_csv(path_salida, index=False, encoding="utf-8-sig")

        print(f"[✔] Guardados {len(df_out)} reprocesos en {path_salida}")

    # --- reescribir archivo de errores ---
    # Ahora eliminamos los errores reprocesados con éxito
    with open(path_errores, "w", encoding="utf-8-sig") as f:
        for err in errores_persistentes:
            f.write(json.dumps(err, ensure_ascii=False) + "\n")

    if errores_persistentes:
        print(f"[ℹ] {len(errores_persistentes)} errores persisten en {path_errores}")
    else:
        # truncamos archivo si todos reprocesos fueron exitosos
        open(path_errores, "w", encoding="utf-8-sig").close()
        print(f"[ℹ] Todos los errores fueron reprocesados; {path_errores} quedó vacío.")
