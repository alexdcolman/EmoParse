import json
import re
import spacy
import pandas as pd
from tqdm import tqdm

from modulos.extraccion_fragmentos import extraer_fragmentos_relevantes
from modulos.recursos import limpiar_prompt, limpiar_respuesta_modelo

# Modelo spaCy
nlp = spacy.load("es_core_news_md")

def preparar_fragmentos_str(fragmentos):
    return "\n".join([f"Fragmento {i+1}:\n{frag}" for i, frag in enumerate(fragmentos)])

def analizar_tipo_discurso(resumen, fragmentos, modelo_llm, prompt_base, diccionario=None, mostrar_prompts=False):
    diccionario_str = json.dumps(diccionario, indent=2, ensure_ascii=False) if diccionario else ""
    prompt = prompt_base.replace("<<RESUMEN>>", resumen)
    prompt = prompt.replace("<<FRAGMENTOS>>", preparar_fragmentos_str(fragmentos))
    prompt = prompt.replace("<<DICCIONARIO>>", diccionario_str)
    prompt = limpiar_prompt(prompt)
    
    if mostrar_prompts:
        print("\n📤 Prompt - Tipo de discurso:\n", prompt)

    respuesta = modelo_llm.invoke(prompt)
    return limpiar_respuesta_modelo(respuesta.content) or {"tipo": "", "justificación": "Sin justificación"}

def analizar_enunciacion(resumen, fragmentos, modelo_llm, prompt_base, diccionario=None, mostrar_prompts=False):
    diccionario_str = json.dumps(diccionario, indent=2, ensure_ascii=False) if diccionario else ""
    prompt = prompt_base.replace("<<RESUMEN>>", resumen)
    prompt = prompt.replace("<<FRAGMENTOS>>", preparar_fragmentos_str(fragmentos))
    prompt = prompt.replace("<<DICCIONARIO>>", diccionario_str)
    prompt = limpiar_prompt(prompt)

    if mostrar_prompts:
        print("\n📤 Prompt - Enunciación:\n", prompt)

    respuesta = modelo_llm.invoke(prompt)
    return limpiar_respuesta_modelo(respuesta.content) or {
        "enunciador": {"actor": "", "justificación": "Sin justificación"},
        "enunciatarios": []
    }

def analizar_lugar(titulo, resumen, fragmentos, modelo_llm, prompt_base, mostrar_prompts=False):
    prompt = prompt_base.replace("<<TITULO>>", titulo)
    prompt = prompt.replace("<<RESUMEN>>", resumen)
    prompt = prompt.replace("<<FRAGMENTOS>>", preparar_fragmentos_str(fragmentos))
    prompt = limpiar_prompt(prompt)

    if mostrar_prompts:
        print("\n📤 Prompt - Lugar:\n", prompt)

    respuesta = modelo_llm.invoke(prompt)
    return limpiar_respuesta_modelo(respuesta.content) or {
        "ciudad": "", "provincia": "", "país": "", "justificación": "Sin justificación"
    }

def procesar_discursos_llm(
    df,
    modelo_llm,
    diccionario,
    prompt_tipo,
    prompt_enunciacion,
    prompt_lugar,
    guardar_csv=True,
    output_path=None,
    analizar_tipo=True,
    analizar_enunc=True,
    analizar_lug=True,
    mostrar_prompts=False
):
    filas = []

    for _, row in tqdm(df.iterrows(), total=len(df), desc="Procesando discursos"):
        codigo = row.get("codigo", "SIN_CODIGO")
        texto = row["texto_limpio"]
        titulo = row["titulo"]
        resumen = row["resumen"]
        fragmentos = extraer_fragmentos_relevantes(texto, nlp)
        base = row.to_dict()

        # --- Tipo de discurso ---
        if analizar_tipo:
            tipo_result = analizar_tipo_discurso(resumen, fragmentos, modelo_llm, prompt_tipo, diccionario, mostrar_prompts)
            tipo = tipo_result.get("tipo", "")
            dicc_tipo = diccionario.get(tipo, {})
            base.update({
                "tipo_discurso": tipo,
                "tipo_discurso_justificacion": tipo_result.get("justificación", "")
            })
        else:
            tipo = ""
            dicc_tipo = {}
            base.update({
                "tipo_discurso": "",
                "tipo_discurso_justificacion": ""
            })

        # --- Enunciación ---
        if analizar_enunc:
            enun_result = analizar_enunciacion(resumen, fragmentos, modelo_llm, prompt_enunciacion, dicc_tipo, mostrar_prompts)
            base.update({
                "enunciador_actor": enun_result.get("enunciador", {}).get("actor", ""),
                "enunciador_justificacion": enun_result.get("enunciador", {}).get("justificación", "")
            })
            for i, e in enumerate(enun_result.get("enunciatarios", [])):
                base[f"enunciatario_{i}_actor"] = e.get("actor", "")
                base[f"enunciatario_{i}_tipo"] = e.get("tipo", "")
                base[f"enunciatario_{i}_justificacion"] = e.get("justificación", "")
        else:
            base.update({
                "enunciador_actor": "",
                "enunciador_justificacion": ""
            })

        # --- Lugar ---
        if analizar_lug:
            lugar_result = analizar_lugar(titulo, resumen, fragmentos, modelo_llm, prompt_lugar, mostrar_prompts)
            base.update({
                "lugar_ciudad": lugar_result.get("ciudad", ""),
                "lugar_provincia": lugar_result.get("provincia", ""),
                "lugar_pais": lugar_result.get("país", ""),
                "lugar_justificacion": lugar_result.get("justificación", "")
            })
        else:
            base.update({
                "lugar_ciudad": "",
                "lugar_provincia": "",
                "lugar_pais": "",
                "lugar_justificacion": ""
            })

        # Log básico
        print(f"\n🎤 Código: {codigo}")
        if analizar_tipo:
            print("✔️ Tipo de discurso:", base['tipo_discurso'])
        if analizar_enunc:
            print("✔️ Enunciador:", base['enunciador_actor'])
            print("📨 Enunciatarios:")
            for i in range(10):
                actor = base.get(f"enunciatario_{i}_actor", "")
                tipo_dest = base.get(f"enunciatario_{i}_tipo", "")
                if actor:
                    print(f"   {i+1}. {actor} ({tipo_dest})")
        if analizar_lug:
            print("✔️ Lugar:", base['lugar_ciudad'], base['lugar_provincia'], base['lugar_pais'])

        filas.append(base)

    df_final = pd.DataFrame(filas)

    if guardar_csv and output_path:
        df_final.to_csv(output_path, index=False)
        print(f"\n✅ Archivo guardado como {output_path}")

    return df_final

