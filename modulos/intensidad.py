# modules/intensidad.py
"""
Módulo M6: Medición de intensidad emocional
"""
from sentence_transformers import SentenceTransformer, util

modelo = SentenceTransformer("distilbert-base-nli-mean-tokens")

EMOCIONES_BASE = {
    "alegría": "Estoy eufórico y feliz",
    "tristeza": "Me siento muy triste y vacío",
    "miedo": "Estoy aterrado, lleno de miedo",
    "ira": "Estoy furioso y molesto"
}

def medir_intensidad(texto):
    """
    Compara texto con emociones base usando embeddings + coseno.
    """
    emb_texto = modelo.encode(texto, convert_to_tensor=True)
    similitudes = {emo: float(util.cos_sim(emb_texto, modelo.encode(frase, convert_to_tensor=True)))
                   for emo, frase in EMOCIONES_BASE.items()}
    return similitudes