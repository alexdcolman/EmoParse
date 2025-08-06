# modules/foria_dominancia.py
"""
Módulo M5: Evaluación de foria y dominancia
"""
from .diccionario_foria import FORIA_DICT

import spacy
nlp = spacy.load("es_core_news_md")

def evaluar_foria_dominancia(texto):
    """
    Evalúa polaridad energética y direccionalidad desde un diccionario emocional extendido.
    """
    doc = nlp(texto)
    score_foria = sum(FORIA_DICT.get(token.lemma_, 0) for token in doc)
    return {"foria": score_foria}