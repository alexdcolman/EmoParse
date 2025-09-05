import pandas as pd
import re
import time
import spacy
import os
import json
from modulos.utils_io import guardar_csv, mostrar_tiempo_procesamiento

# Cargar modelo base de spaCy
nlp = spacy.load("es_core_news_md")


# ---------- Submódulo 2.1: segmentación de discursos ----------

def normalizar_texto(texto):
    texto = re.sub(r'\[\.["”]\]', '[".]', texto)
    return texto


def segmentar_en_frases(contenido):
    contenido = normalizar_texto(contenido)
    contenido = contenido.replace('\n', ' ')
    frases = re.split(r'(?<=[.!?])\s+', contenido)
    frases = [f.strip() for f in frases if len(f.strip()) > 1]
    return frases


def generar_recortes(
    df_discursos,
    agregar_codigo=True,
    prefijo_codigo="DISCURSO",
    guardar=False,
    output_path=None,
    mostrar_tiempo=True
):
    start_time = time.time()

    if agregar_codigo or 'codigo' not in df_discursos.columns:
        df_discursos["codigo"] = [f"{prefijo_codigo}_{i:03d}" for i in range(1, len(df_discursos) + 1)]

    codigos, recorte_ids, posiciones, frases_lista = [], [], [], []

    for _, row in df_discursos.iterrows():
        codigo = row["codigo"]
        titulo = row.get("titulo", "").strip()
        contenido = row.get("contenido", "").strip()

        if contenido.startswith(titulo):
            contenido = contenido[len(titulo):].strip()

        frases = segmentar_en_frases(contenido)

        for i, frase in enumerate(frases, start=1):
            codigos.append(codigo)
            recorte_ids.append(f"{codigo}_FR_{i:03d}")
            posiciones.append(i)
            frases_lista.append(frase)

    df_recortes = pd.DataFrame({
        "codigo": codigos,
        "recorte_id": recorte_ids,
        "posicion": posiciones,
        "frase": frases_lista
    })

    # 🚀 Agregar columna INDEX explícita
    df_recortes = df_recortes.reset_index().rename(columns={"index": "INDEX"})

    if guardar:
        if output_path is None:
            raise ValueError("Debés especificar un 'output_path' si guardar=True.")
        guardar_csv(df_recortes, output_path)
        print(f"🧾 La base tiene {len(df_recortes)} observaciones (frases).")

    if mostrar_tiempo:
        mostrar_tiempo_procesamiento(start_time, mensaje="Tiempo de generar_recortes")

    return df_recortes


# ---------- Submódulo 2.2: filtrado por cantidad de frases ----------

def filtrar_discursos(
    df,
    df_recortes,
    umbral=24,
    guardar=False,
    path_discursos=None,
    path_recortes=None,
    path_codigos_eliminados=None,
    mostrar_tiempo=True
):
    start_time = time.time()

    # 1) Conteo por código
    conteo_frases = df_recortes.groupby("codigo").size().reset_index(name="cantidad_frases")
    print("Cantidad de frases por código (primeras filas):")
    print(conteo_frases.head())

    # 2) Filtrar códigos
    codigos_validos = conteo_frases.loc[conteo_frases["cantidad_frases"] >= umbral, "codigo"].tolist()
    codigos_eliminados = conteo_frases.loc[conteo_frases["cantidad_frases"] < umbral, "codigo"].tolist()

    print(f"\n✅ Códigos con al menos {umbral} frases: {len(codigos_validos)}")
    print(f"❌ Códigos eliminados (menos de {umbral} frases): {len(codigos_eliminados)}")

    # 3) Filtrar dataframes
    df_filtrado = df[df["codigo"].isin(codigos_validos)].copy()
    df_recortes_filtrado = df_recortes[df_recortes["codigo"].isin(codigos_validos)].copy()

    print(f"\n📄 Textos originales tras el filtro: {len(df_filtrado)}")
    print(f"🧾 Frases tras el filtro: {len(df_recortes_filtrado)}")

    # 4) Guardado opcional
    if guardar:
        if not all([path_discursos, path_recortes, path_codigos_eliminados]):
            raise ValueError("⚠️ Para guardar, se deben especificar todos los paths de salida.")

        guardar_csv(df_filtrado, path_discursos)
        guardar_csv(df_recortes_filtrado, path_recortes)
        with open(path_codigos_eliminados, "w", encoding="utf-8") as f:
            for codigo in codigos_eliminados:
                f.write(codigo + "\n")
        print(f"\n💾 Códigos eliminados guardados en: {path_codigos_eliminados}")

    if mostrar_tiempo:
        mostrar_tiempo_procesamiento(start_time, mensaje="Tiempo de filtrar_discursos")

    return df_filtrado, df_recortes_filtrado, codigos_eliminados, codigos_validos, conteo_frases


# ---------- Submódulo 2.3: limpieza y preprocesamiento de texto ----------

def limpiar_texto(texto):
    if texto is None:
        return ""
    texto = texto.strip().lower()
    texto = re.sub(r'[“”‘’´`¨]', '"', texto)
    texto = re.sub(r'[^\w\s¡!¿?.,;:()"\n-]', '', texto, flags=re.UNICODE)
    texto = re.sub(r'[ \t]+', ' ', texto)
    texto = re.sub(r'\n{2,}', '\n', texto)
    return texto


def marcar_sujeto_omitido_por_frase(texto):
    doc = nlp(texto)
    resultado = []
    for sent in doc.sents:
        tiene_sujeto = any(tok.dep_ in ("nsubj", "nsubj:pass") for tok in sent)
        resultado.append({
            "frase": sent.text.strip(),
            "sujeto_explicito": tiene_sujeto
        })
    return resultado


def preprocesar_texto(texto, extraer_tokens=True, extraer_lemmas=True,
                      extraer_pos=True, extraer_entidades=True,
                      extraer_dependencias=True, marcar_sujetos=True):
    
    texto_limpio = limpiar_texto(texto)
    doc = nlp(texto_limpio)

    resultado = {"texto_limpio": texto_limpio}

    if extraer_tokens:
        resultado["tokens"] = [token.text for token in doc]

    if extraer_lemmas:
        resultado["lemmas"] = [token.lemma_ for token in doc]

    if extraer_pos:
        resultado["pos_tags"] = [token.pos_ for token in doc]

    if extraer_dependencias:
        resultado["dependencias"] = [
            {
                "token": token.text,
                "dep": token.dep_,
                "head": token.head.text,
                "morph": token.morph.to_dict(),
                "idx": token.idx,
                "is_stop": token.is_stop,
                "is_alpha": token.is_alpha
            }
            for token in doc
        ]

    if extraer_entidades:
        resultado["entidades"] = [
            {
                "texto": ent.text,
                "etiqueta": ent.label_,
                "inicio": ent.start_char,
                "fin": ent.end_char,
                "contexto": doc[ent.start : ent.end + 3].text
            }
            for ent in doc.ents
        ]

    if marcar_sujetos:
        resultado["frases_con_sujeto"] = marcar_sujeto_omitido_por_frase(texto_limpio)

    return resultado


def procesar_textos(df, columna_texto, texto_limpio=True, tokens=True, lemmas=True, pos_tags=True,
                    dependencias=True, entidades=True, sujetos=True, guardar=False, path_salida=None,
                    mostrar_tiempo=True):
    start_time = time.time()

    if columna_texto not in df.columns:
        raise ValueError(f"La columna '{columna_texto}' no está en el DataFrame.")

    resultados = df[columna_texto].apply(
        lambda x: preprocesar_texto(
            x,
            extraer_tokens=tokens,
            extraer_lemmas=lemmas,
            extraer_pos=pos_tags,
            extraer_dependencias=dependencias,
            extraer_entidades=entidades,
            marcar_sujetos=sujetos
        )
    )

    df_expandido = pd.json_normalize(resultados)

    # Convertir algunas columnas complejas a JSON string (opcional)
    if "entidades" in df_expandido.columns:
        df_expandido["entidades_json"] = df_expandido["entidades"].apply(lambda x: json.dumps(x, ensure_ascii=False))

    if "dependencias" in df_expandido.columns:
        df_expandido["dependencias_json"] = df_expandido["dependencias"].apply(lambda x: json.dumps(x, ensure_ascii=False))

    df_final = pd.concat([df.reset_index(drop=True), df_expandido], axis=1)

    if guardar:
        if path_salida is None:
            raise ValueError("Debe especificarse `path_salida` si `guardar=True`.")
        guardar_csv(df_final, path_salida)

    if mostrar_tiempo:
        mostrar_tiempo_procesamiento(start_time, mensaje="Tiempo de procesar_textos")

    return df_final