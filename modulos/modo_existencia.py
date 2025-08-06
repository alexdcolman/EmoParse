# modules/modo_existencia.py
"""
Módulo M4: Modo de existencia emocional (virtual, actual, realizado...)
"""
from transformers import pipeline

def inferir_modo_existencia(texto):
    """
    Usa LLM y reglas heurísticas para inferir si la emoción está potencial, actual o evocada.
    """
    inferidor = pipeline("text2text-generation", model="mistralai/Mistral-7B-Instruct-v0.1")
    prompt = f"¿La emoción expresada en este texto está virtual, actual o realizada?: '{texto}'"
    return inferidor(prompt)[0]['generated_text']