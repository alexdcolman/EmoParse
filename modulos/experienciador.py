# modules/experienciador.py
"""
Módulo M7: Experienciador de la emoción
"""
import spacy
from transformers import pipeline

def extraer_experienciador(texto):
    """
    Busca sujetos emocionales mediante SRL o NER con modelo fine-tuned.
    """
    nlp = spacy.load("es_core_news_md")
    doc = nlp(texto)
    experienciadores = [ent.text for ent in doc.ents if ent.label_ in ["PER"]]
    return experienciadores