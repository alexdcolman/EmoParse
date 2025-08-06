import re
import spacy

# Cargar modelo spaCy para español (mediano)
nlp = spacy.load("es_core_news_md")

def limpiar_texto(texto):
    if texto is None:
        return ""
    texto = texto.strip().lower()
    texto = re.sub(r'\s+', ' ', texto)  # múltiples espacios a uno
    texto = re.sub(r'[“”‘’´`¨]', '"', texto)  # normalizar comillas
    texto = re.sub(r'[^\w\s¡!¿?.,;:()"-]', '', texto, flags=re.UNICODE)  # eliminar caracteres raros
    return texto

def preprocesar_texto(texto):
    """
    Aplica limpieza y análisis lingüístico con spaCy.
    Devuelve un diccionario con tokens, lemas, POS, entidades y dependencias enriquecidas.
    """
    texto_limpio = limpiar_texto(texto)
    doc = nlp(texto_limpio)

    tokens_data = []
    lemmas = []
    pos_tags = []
    dependencias = []

    for token in doc:
        tokens_data.append(token.text)
        lemmas.append(token.lemma_)
        pos_tags.append(token.pos_)
        dependencias.append({
            "token": token.text,
            "dep": token.dep_,
            "head": token.head.text,
            "morph": token.morph.to_dict(),
            "idx": token.idx,
            "is_stop": token.is_stop,
            "is_alpha": token.is_alpha
        })

    entidades = [
        {
            "texto": ent.text,
            "etiqueta": ent.label_,
            "inicio": ent.start_char,
            "fin": ent.end_char,
            "contexto": doc[ent.start : ent.end + 3].text  # contexto opcional
        }
        for ent in doc.ents
    ]

    resultado = {
        "texto_limpio": texto_limpio,
        "tokens": tokens_data,
        "lemmas": lemmas,
        "pos_tags": pos_tags,
        "entidades": entidades,
        "dependencias": dependencias
    }

    return resultado
