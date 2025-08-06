# modules/clasificacion_emocional.py
"""
Módulo M3: Clasificación emocional compleja
"""
from transformers import pipeline

def clasificar_emocion(texto):
    """
    Usa modelo tipo FLAN-T5 + reglas para clasificar emoción y categoría semiótica.
    """
    clasificador = pipeline("text2text-generation", model="google/flan-t5-base")
    prompt = f"Clasificá la emoción principal en el siguiente texto: '{texto}'"
    return clasificador(prompt)[0]['generated_text']