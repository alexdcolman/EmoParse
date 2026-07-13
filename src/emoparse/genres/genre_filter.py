# ══════════════════════════════════════════════════════════════════════════════
#  emoparse.knowledge.genre_filter
#
#  Filtrado por género de la ontología de emociones (base compartida).
#
#  Desde v2, cada entrada de `emociones_ontologia.json` puede declarar un
#  campo opcional `generos: ["tuit", ...]`: la emoción solo se OFRECE como
#  candidata en los prompts de esos géneros. Una entrada sin `generos`
#  pertenece a la base compartida (todos los géneros).
#
#  Importante: este filtro aplica a la ontología QUE VE EL PROMPT. La
#  normalización de aliases (normalize_emotions) debe operar siempre sobre
#  la base completa: si un discurso presidencial expresa burla, se
#  normaliza igual aunque el prompt no la ofreciera.
#
#  Punto de integración: KnowledgeLoader.load_ontology debería aplicar
#  `filtrar_ontologia_por_genero(data, genre_id)` antes de formatear el
#  texto del prompt (pendiente de cablear; ver PENDIENTES.md).
# ══════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

from typing import Any


def filtrar_ontologia_por_genero(
    ontologia: dict[str, Any],
    genre_id: str | None,
) -> dict[str, Any]:
    """Devuelve una copia de la ontología con las emociones visibles para
    un género.

    Args:
        ontologia: El dict completo de emociones_ontologia.json.
        genre_id: Género activo (p. ej. 'tuit', 'discurso_presidencial').
            None conserva la base completa (comportamiento para
            normalización de aliases y para herramientas transversales).

    Returns:
        Copia superficial del dict con `emociones` filtrado: quedan las
        entradas sin campo `generos` (base compartida) y las que incluyan
        `genre_id` en su lista.
    """
    if genre_id is None:
        return ontologia
    emociones = ontologia.get("emociones")
    if not isinstance(emociones, dict):
        return ontologia
    filtradas = {
        nombre: entry
        for nombre, entry in emociones.items()
        if _visible(entry, genre_id)
    }
    out = dict(ontologia)
    out["emociones"] = filtradas
    return out


def _visible(entry: Any, genre_id: str) -> bool:
    """True si la entrada pertenece a la base compartida o incluye el género."""
    if not isinstance(entry, dict):
        return True
    generos = entry.get("generos")
    if generos is None:
        return True  # base compartida
    if not isinstance(generos, (list, tuple)):
        return True  # malformado: mejor incluir que ocultar
    return genre_id in {str(g) for g in generos}
