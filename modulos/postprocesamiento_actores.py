import os
import json
import re
import logging
import pandas as pd
from tqdm import tqdm
from modulos.modelo import get_model_ollama
from modulos.recursos import cargar_ontologia, ErrorLogger
from modulos.identificacion_actores import procesar_una_frase
from modulos.prompts import PROMPT_VALIDAR_ACTORES

# -------------------- PROPAGACIÓN DE ACTORES POR PRONOMBRES --------------------

PRONOMBRES_SUBJETIVOS = {"él", "ella", "ellos", "ellas", "nosotros", "vosotros", "vos"}
PRONOMBRES_OBJETO = {"lo", "la", "los", "las", "le", "les", "nos", "os"}
PRONOMBRES_POSESIVOS = {"su", "sus", "nuestro", "nuestra", "nuestros", "nuestras"}

def propagar_actores_por_pronombres(df_resultado):
    """
    Propaga actores identificados por pronombres en frases posteriores dentro de un mismo discurso.
    """
    antecedentes = {}  # pronombre -> actor más reciente

    for idx, row in df_resultado.iterrows():
        frase = row["frase_idx"]
        actores = df_resultado[df_resultado["frase_idx"] == frase]

        # Actualizar diccionario de antecedentes con actores explícitos
        for _, actor_row in actores.iterrows():
            if actor_row["modo"] == "explícito":
                nombre = actor_row["actor"]
                tipo = actor_row["tipo"]
                # asociar pronombres posibles
                antecedentes.update({
                    "él": nombre if tipo == "humano_individual" else antecedentes.get("él"),
                    "ella": nombre if tipo == "humano_individual" else antecedentes.get("ella"),
                    "ellos": nombre if tipo in {"humano_individual", "colectivo"} else antecedentes.get("ellos"),
                    "ellas": nombre if tipo in {"humano_individual", "colectivo"} else antecedentes.get("ellas"),
                    "nosotros": nombre if tipo in {"humano_individual", "colectivo"} else antecedentes.get("nosotros"),
                    "vos": nombre if tipo == "humano_individual" else antecedentes.get("vos"),
                    "lo": nombre,
                    "la": nombre,
                    "los": nombre,
                    "las": nombre,
                    "le": nombre,
                    "les": nombre,
                    "nos": nombre,
                    "su": nombre,
                    "sus": nombre,
                    "nuestro": nombre,
                    "nuestra": nombre,
                    "nuestros": nombre,
                    "nuestras": nombre
                })

        # Revisar si hay actores inferidos por pronombres en la frase
        texto_frase = actores["actor"].iloc[0] if not actores.empty else ""
        for pron in PRONOMBRES_SUBJETIVOS | PRONOMBRES_OBJETO | PRONOMBRES_POSESIVOS:
            if pron in texto_frase.lower() and pron in antecedentes:
                actor_inferido = antecedentes[pron]
                if not actores[(actores["actor"] == actor_inferido)].any().any():
                    # Agregar fila inferida
                    nueva_fila = {
                        "actor": actor_inferido,
                        "tipo": "humano_individual",  # se puede intentar inferir tipo dinámicamente
                        "modo": "inferido",
                        "justificacion": f"Pronombre '{pron}' se refiere a actor en contexto previo",
                        "frase_idx": frase,
                        "recorte_id": row["recorte_id"],
                        "codigo": row["codigo"]
                    }
                    df_resultado = pd.concat([df_resultado, pd.DataFrame([nueva_fila])], ignore_index=True)

    # Ordenar por frase_idx para mantener coherencia
    df_resultado = df_resultado.sort_values(by=["frase_idx"]).reset_index(drop=True)
    return df_resultado

# -------------------- VALIDACIÓN DE ACTORES SEGÚN ONTOLOGÍA --------------------

def validacion_actores(
    path_df_actores,
    path_df_recortes,
    path_salida_validos,
    path_salida_excluidos,
    modelo_llm=None,
    mostrar_prompts=False
):
    """
    Valida actores identificados previamente usando un LLM.
    Los actores válidos se guardan en `path_salida_validos` y
    los excluidos en `path_salida_excluidos`.
    
    Parámetros:
        path_df_actores: str o pd.DataFrame
        path_df_recortes: str o pd.DataFrame
        path_salida_validos: str
        path_salida_excluidos: str
        modelo_llm: objeto LLM opcional
        mostrar_prompts: bool
    """
    # --- Inicialización del LLM ---
    if modelo_llm is None:
        modelo_llm = get_model_ollama(modelo="gpt-oss:20b", temperature=0.0, output_format="text")

    # --- Cargar archivos o usar DataFrames existentes ---
    if isinstance(path_df_actores, pd.DataFrame):
        df_actores = path_df_actores
    else:
        df_actores = pd.read_csv(path_df_actores, encoding="utf-8-sig")

    if isinstance(path_df_recortes, pd.DataFrame):
        df_recortes = path_df_recortes
    else:
        df_recortes = pd.read_csv(path_df_recortes, encoding="utf-8-sig")

    ontologia = json.dumps(cargar_ontologia(), indent=2, ensure_ascii=False)

    validos = []
    excluidos = []

    # --- Iterar por recorte ---
    for recorte_id, grupo in tqdm(df_actores.groupby("recorte_id"), desc="Procesando recortes"):
        fila_frase = df_recortes.loc[df_recortes["recorte_id"] == recorte_id, "texto_limpio"]
        if fila_frase.empty:
            print(f"⚠️ No se encontró texto para recorte_id={recorte_id}")
            continue
        texto = fila_frase.values[0]
        actores = grupo.to_dict(orient="records")

        for actor_data in tqdm(actores, desc=f"Validando actores recorte {recorte_id}", leave=False):
            actor = actor_data["actor"]
            prompt = PROMPT_VALIDAR_ACTORES.replace("<<FRASE>>", texto)\
                                           .replace("<<ACTOR>>", actor)\
                                           .replace("<<ONTOLOGIA>>", ontologia)

            # --- Llamar al modelo ---
            try:
                respuesta = modelo_llm(prompt)
                contenido = re.sub(r"^```json\s*|\s*```$", "", respuesta.strip(), flags=re.DOTALL)
            except Exception as e:
                print(f"❌ Error validando actor '{actor}' en '{recorte_id}': {e}")
                excluidos.append(actor_data)
                continue

            # --- Clasificar respuesta ---
            contenido_lower = contenido.lower()
            if "válido" in contenido_lower:
                validos.append(actor_data)
            else:
                excluidos.append(actor_data)

    # --- Guardar resultados ---
    if validos:
        pd.DataFrame(validos).to_csv(path_salida_validos, index=False, encoding="utf-8-sig")
        print(f"✅ Guardados {len(validos)} actores validados en '{path_salida_validos}'")

    if excluidos:
        pd.DataFrame(excluidos).to_csv(path_salida_excluidos, index=False, encoding="utf-8-sig")
        print(f"📄 Guardados {len(excluidos)} actores excluidos en '{path_salida_excluidos}'")
    else:
        print("✅ No hubo actores excluidos.")