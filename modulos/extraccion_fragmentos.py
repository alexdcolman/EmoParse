from typing import List
from spacy.language import Language


def obtener_intro_cierre(texto: str, n_intro: int, n_cierre: int) -> List[str]:
    """Devuelve los fragmentos de inicio y cierre del texto."""
    fragmentos: List[str] = []
    intro = texto[:n_intro].strip()
    cierre = texto[-n_cierre:].strip()
    if intro:
        fragmentos.append(intro)
    if cierre:
        fragmentos.append(cierre)
    return fragmentos


def filtrar_parrafos(texto: str, min_len: int) -> List[str]:
    """Filtra párrafos que superen cierta longitud mínima."""
    return [p.strip() for p in texto.split("\n") if len(p.strip()) >= min_len]


def calcular_densidad_entidades(
    parrafo: str,
    nlp: Language,
    etiquetas_validas: set[str] = {"PER", "ORG", "LOC"}
) -> float:
    """Calcula la densidad de entidades válidas en un párrafo."""
    doc = nlp(parrafo)
    entidades = [ent for ent in doc.ents if ent.label_ in etiquetas_validas]
    return len(entidades) / (len(parrafo) + 1)  # evitar división por cero


def seleccionar_parrafos_densos(
    parrafos: List[str],
    nlp: Language,
    n: int
) -> List[str]:
    """Selecciona los n párrafos con mayor densidad de entidades."""
    puntuados: List[tuple[float, str]] = [
        (calcular_densidad_entidades(p, nlp), p) for p in parrafos
    ]
    seleccionados = sorted(puntuados, key=lambda x: -x[0])[:n]
    return [p for _, p in seleccionados]


def extraer_fragmentos_relevantes(
    texto: str,
    nlp: Language,
    n_intro: int = 500,
    n_cierre: int = 500,
    n_actores: int = 2,
    min_parrafo_len: int = 200
) -> List[str]:
    """
    Extrae fragmentos relevantes del texto para identificación de actores.
    """
    fragmentos = obtener_intro_cierre(texto, n_intro, n_cierre)
    parrafos_largos = filtrar_parrafos(texto, min_parrafo_len)
    densos = seleccionar_parrafos_densos(parrafos_largos, nlp, n_actores)
    fragmentos.extend(densos)
    return fragmentos
