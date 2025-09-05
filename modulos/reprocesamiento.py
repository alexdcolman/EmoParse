# reprocesamiento.py

import os
import json
import pandas as pd
import modulos.paths as paths
from datetime import datetime
from modulos.recursos import ErrorLogger, analizar_generico
from modulos.identificacion_actores import procesar_una_frase
from modulos.schemas import LugarSchema, TipoDiscursoSchema, EnunciacionSchema
from modulos.enunciacion import analizar_enunciacion

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
def reprocesar_errores_metadatos(
    df_original,
    path_errores,
    modelo_llm,
    intento=1,
    mostrar_prompts=False,
    path_salida=None
):
    import os
    import pandas as pd
    from datetime import datetime

    logger = ErrorLogger(path_errores)
    errores = logger.cargar()
    if not errores:
        print("✅ No hay errores de metadatos para reprocesar.")
        return df_original.copy()

    print(f"🔁 Reprocesando {len(errores)} errores de metadatos...")

    errores_persistentes = []
    exitosos = []

    if "INDEX" in df_original.columns:
        df_original["INDEX"] = df_original["INDEX"].astype(int)

    for reg in errores:
        etiqueta = reg.get("etiqueta")
        campos = reg.get("campos", {}) or {}
        prompt_usado = reg.get("prompt_usado", "")
        idx = reg.get("INDEX") or campos.get("INDEX")
        try:
            idx = int(idx)
        except Exception:
            idx = None

        if idx is None or idx not in df_original["INDEX"].values:
            reg["error_reproceso"] = "INDEX inválido o no encontrado"
            reg["timestamp_reproceso"] = datetime.now().isoformat()
            errores_persistentes.append(reg)
            continue

        if etiqueta == "Lugar":
            schema = LugarSchema
            default_obj = LugarSchema(ciudad="", provincia="", pais="", justificacion="Sin respuesta")
            cols_update = ['lugar_ciudad','lugar_provincia','lugar_pais','lugar_justificacion']
        elif etiqueta == "Tipo de discurso":
            schema = TipoDiscursoSchema
            default_obj = TipoDiscursoSchema(tipo="", justificacion="Sin justificación")
            cols_update = ['tipo_discurso','tipo_discurso_justificacion']
        else:
            errores_persistentes.append(reg)
            continue

        try:
            resultado = analizar_generico(
                modelo_llm=modelo_llm,
                prompt_base=prompt_usado,
                campos=campos,
                default=default_obj,
                schema=schema,
                etiqueta_log=f"{etiqueta} (reproceso intento {intento})",
                mostrar_prompts=mostrar_prompts,
                path_errores=None  # NO registrar en JSONL original
            )

            # --- Validación ---
            success = False
            if etiqueta == "Lugar":
                if any(getattr(resultado, f, None) and str(getattr(resultado, f)).strip() for f in ("ciudad","provincia","pais")):
                    success = True
                elif getattr(resultado, "justificacion", None) and str(resultado.justificacion).strip() != default_obj.justificacion:
                    success = True
            else:  # Tipo de discurso
                tipo_val = getattr(resultado, "tipo", None)
                if tipo_val and str(tipo_val).strip():
                    success = True

            if success:
                mask = df_original["INDEX"] == idx
                df_original.loc[mask, cols_update] = [getattr(resultado, c.split("_")[-1]) if etiqueta=="Lugar" else getattr(resultado, c.split("_")[-2]) for c in cols_update]
                exitosos.append(reg)
                print(f"✅ Corregido {etiqueta} fila {idx}")
            else:
                reg["error_reproceso"] = "Resultado vacío/inválido"
                reg["timestamp_reproceso"] = datetime.now().isoformat()
                errores_persistentes.append(reg)
                print(f"⚠️ Reproceso NO exitoso {etiqueta} fila {idx}")

        except Exception as e:
            reg["error_reproceso"] = str(e)
            reg["timestamp_reproceso"] = datetime.now().isoformat()
            errores_persistentes.append(reg)
            print(f"❌ Error persistente {etiqueta} fila {idx}: {e}")

    # Guardar CSV actualizado
    if path_salida:
        df_original.to_csv(path_salida, index=False, encoding="utf-8-sig")
        print(f"✅ CSV actualizado guardado en {path_salida}")

    # Guardar persistentes
    if errores_persistentes:
        path_persistentes = os.path.join(os.path.dirname(path_errores), "errores_metadatos_persistentes.jsonl")
        persist_logger = ErrorLogger(path_persistentes)
        for reg in errores_persistentes:
            reg["reproceso_intento"] = intento
        persist_logger.guardar_varios(errores_persistentes, overwrite=True)
        print(f"✅ Guardados {len(errores_persistentes)} persistentes en {path_persistentes}")

    # Eliminar exitosos del JSONL original
    if exitosos:
        for reg in exitosos:
            logger.eliminar_error(reg)
        print(f"✅ Eliminados {len(exitosos)} exitosos del JSONL original")

    return df_original

# Reprocesar actores
def reprocesar_errores_identificacion(
    df_recortes,
    df_enunc,
    path_errores,
    path_salida,
    prompt_actores,
    intento=1,
    evitar_duplicados=True,
    modelo_llm=None,
    mostrar_prompts=False,
    max_context=2,
):
    """
    Reprocesa errores de identificación de actores:
    - Actualiza registros procesados con df_result de cada fila INDEX.
    - Elimina errores exitosos del JSONL original.
    - Guarda persistentes en errores_actores_persistentes.jsonl.
    - Devuelve un DataFrame con las filas corregidas.
    """
    import os
    import pandas as pd
    from datetime import datetime

    logger = ErrorLogger(path_errores)
    errores = logger.cargar()
    if not errores:
        print("✅ No hay errores para reprocesar.")
        return pd.DataFrame()

    print(f"🔁 Reprocesando {len(errores)} errores de identificación...")

    df_corr = pd.DataFrame()  # solo filas actualizadas
    errores_persistentes = []
    exitosos = []

    # Asegurar que INDEX es int
    if "INDEX" in df_recortes.columns:
        df_recortes["INDEX"] = df_recortes["INDEX"].astype(int)

    for reg in errores:
        campos = reg.get("campos", {}) or {}
        idx = reg.get("INDEX") or campos.get("INDEX")
        try:
            idx = int(idx)
        except Exception:
            idx = None

        codigo = reg.get("codigo")

        if idx is None or idx not in df_recortes["INDEX"].values:
            print(f"⚠️ INDEX no encontrado: {idx}")
            reg["error_reproceso"] = "INDEX inválido o no encontrado"
            reg["timestamp_reproceso"] = datetime.now().isoformat()
            errores_persistentes.append(reg)
            continue

        fila = df_recortes.loc[df_recortes["INDEX"] == idx].copy().iloc[0]

        try:
            # Filtrar df_enunc por código si existe
            df_enunc_filtrado = df_enunc[df_enunc["codigo"] == codigo].copy() if codigo else df_enunc.copy()

            df_result, prompt_usado, respuesta_cruda = procesar_una_frase(
                df_recortes=pd.DataFrame([fila]),
                df_enunc=df_enunc_filtrado,
                modelo_llm=modelo_llm,
                prompt_actores=prompt_actores,
                mostrar_prompt=mostrar_prompts,
                max_context=max_context,
                frase_idx=idx
            )

            if isinstance(df_result, pd.DataFrame) and not df_result.empty:
                df_result["INDEX"] = idx
                df_corr = pd.concat([df_corr, df_result], ignore_index=True)
                exitosos.append(reg)
                print(f"✅ Reprocesado INDEX={idx}")
            else:
                reg["error_reproceso"] = "Resultado vacío/inválido"
                reg["timestamp_reproceso"] = datetime.now().isoformat()
                errores_persistentes.append(reg)
                print(f"⚠️ Resultado vacío/inválido INDEX={idx}")

        except Exception as e:
            print(f"❌ Error persistente INDEX={idx}: {e}")
            reg["error_reproceso"] = str(e)
            reg["timestamp_reproceso"] = datetime.now().isoformat()
            errores_persistentes.append(reg)

    # Guardar CSV actualizado si se indicó path_salida
    if path_salida and not df_corr.empty:
        modo = "a" if os.path.exists(path_salida) else "w"
        df_corr.to_csv(path_salida, mode=modo, header=not os.path.exists(path_salida), index=False, encoding="utf-8-sig")
        print(f"✅ CSV actualizado guardado en {path_salida}")

    # Guardar errores persistentes
    if errores_persistentes:
        path_persistentes = os.path.join(os.path.dirname(path_errores), "errores_actores_persistentes.jsonl")
        persist_logger = ErrorLogger(path_persistentes)
        for reg in errores_persistentes:
            reg["reproceso_intento"] = intento
        persist_logger.guardar_varios(errores_persistentes, overwrite=True)
        print(f"✅ Guardados {len(errores_persistentes)} errores persistentes en {path_persistentes}")

    # Eliminar errores exitosos del JSONL original
    if exitosos:
        for reg in exitosos:
            logger.eliminar_error(reg)
        print(f"✅ Eliminados {len(exitosos)} errores exitosos del JSONL original")

    return df_corr

# Reprocesar enunciación
def reprocesar_enunciacion(
    df_original,
    path_errores,
    modelo_llm,
    intento=1,
    mostrar_prompts=False,
    path_salida=None
):
    """
    Reprocesa errores de enunciación:
    - Actualiza df_original solo en las columnas de enunciación.
    - Elimina errores exitosos del JSONL original.
    - Guarda persistentes en errores_persistentes.jsonl.
    - Devuelve df con las filas corregidas.
    """
    import os
    import json
    import pandas as pd
    from datetime import datetime

    # Cargar errores
    logger = ErrorLogger(path_errores)
    errores = logger.cargar()
    if not errores:
        print("✅ No hay errores de enunciación para reprocesar.")
        return pd.DataFrame()

    print(f"🔁 Reprocesando {len(errores)} errores de enunciación...")

    df_corr = pd.DataFrame()  # solo filas actualizadas
    errores_persistentes = []
    exitosos = []

    # Asegurar que INDEX es int en el df_original
    if "INDEX" in df_original.columns:
        df_original["INDEX"] = df_original["INDEX"].astype(int)

    for reg in errores:
        campos = reg.get("campos", {}) or {}
        prompt_usado = reg.get("prompt_usado", "")
        idx = reg.get("INDEX") or campos.get("INDEX")
        try:
            idx = int(idx)
        except Exception:
            idx = None

        if idx is None or idx not in df_original["INDEX"].values:
            print(f"⚠️ Fila {idx} no encontrada en df_original")
            reg["error_reproceso"] = "INDEX inválido o no encontrado"
            reg["timestamp_reproceso"] = datetime.now().isoformat()
            errores_persistentes.append(reg)
            continue

        try:
            resultado = analizar_enunciacion(
                resumen=campos.get("RESUMEN"),
                fragmentos=campos.get("FRAGMENTOS", "").split("\n"),
                modelo_llm=modelo_llm,
                prompt_base=prompt_usado,
                diccionario=json.loads(campos.get("DICCIONARIO", "{}")),
                mostrar_prompts=mostrar_prompts,
                path_errores=None,
                index=idx
            )

            enun = resultado.enunciador
            lista = resultado.enunciatarios
            ok = (hasattr(enun, "actor") and enun.actor and str(enun.actor).strip()) \
                 or (isinstance(lista, (list, tuple)) and len(lista) > 0)

            if ok:
                # Crear dict solo con las columnas de enunciación
                base = {
                    "INDEX": idx,
                    "enunciador_actor": enun.actor,
                    "enunciador_justificacion": enun.justificacion
                }
                for i, e in enumerate(lista):
                    base[f"enunciatario_{i}_actor"] = e.actor
                    base[f"enunciatario_{i}_tipo"] = e.tipo
                    base[f"enunciatario_{i}_justificacion"] = e.justificacion

                # Actualizar df_original en las columnas correctas
                mask = df_original["INDEX"] == idx
                for col, val in base.items():
                    if col in df_original.columns:
                        df_original.loc[mask, col] = val

                df_corr = pd.concat([df_corr, df_original.loc[mask]], ignore_index=True)
                exitosos.append(reg)
                print(f"✅ Reprocesado enunciación INDEX={idx}")

            else:
                print(f"⚠️ Resultado vacío/inválido INDEX={idx}")
                reg["error_reproceso"] = "Resultado vacío/inválido"
                reg["timestamp_reproceso"] = datetime.now().isoformat()
                errores_persistentes.append(reg)

        except Exception as e:
            print(f"❌ Error persistente INDEX={idx}: {e}")
            reg["error_reproceso"] = str(e)
            reg["timestamp_reproceso"] = datetime.now().isoformat()
            errores_persistentes.append(reg)

    # Guardar CSV actualizado si se indicó path_salida
    if path_salida:
        df_original.to_csv(path_salida, index=False, encoding="utf-8-sig")
        print(f"✅ CSV actualizado guardado en {path_salida}")

    # Guardar errores persistentes
    if errores_persistentes:
        path_persistentes = os.path.join(os.path.dirname(path_errores), "errores_persistentes.jsonl")
        persist_logger = ErrorLogger(path_persistentes)
        for reg in errores_persistentes:
            reg["reproceso_intento"] = intento
        persist_logger.guardar_varios(errores_persistentes, overwrite=True)
        print(f"✅ Guardados {len(errores_persistentes)} errores persistentes en {path_persistentes}")

    # Eliminar errores exitosos del JSONL original
    if exitosos:
        for reg in exitosos:
            logger.eliminar_error(reg)
        print(f"✅ Eliminados {len(exitosos)} errores exitosos del JSONL original")

    return df_corr