# modules/fuente_emocional.py
"""
Módulo M8: Fuente de la emoción
"""
from transformers import pipeline

def detectar_fuente_emocion(texto):
    """
    Usa SRL o generación con LLM para inferir la causa o fuente de la emoción.
    """
    model = pipeline("text2text-generation", model="mistralai/Mistral-7B-Instruct-v0.1")
    prompt = f"¿Qué causa o provoca la emoción en este texto?: '{texto}'"
    return model(prompt)[0]['generated_text']