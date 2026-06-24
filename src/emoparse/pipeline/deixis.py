# ══════════════════════════════════════════════════════════════════════════════
#  emoparse.pipeline.deixis
#
#  Resolución determinista de deícticos de 1ª persona al enunciador del discurso.
#
#  Las menciones de actor en 1ª persona ("yo", "mí", "nosotros"…) refieren al
#  enunciador del discurso. Se resuelven por discurso (nunca a la KB).
# ══════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

import re
import unicodedata
from typing import Any

#: Deícticos de 1ª persona que refieren al enunciador del discurso.
FIRST_PERSON_DEICTICS = frozenset({
    "yo", "mi", "me", "conmigo", "mio", "mia", "mios", "mias",
    "nosotros", "nosotras", "nos", "nuestro", "nuestra", "nuestros", "nuestras",
})

#: Deícticos de 2ª persona (refieren al auditorio / enunciatario).
SECOND_PERSON_DEICTICS = frozenset({
    "vos", "tu", "te", "ti", "contigo", "tuyo", "tuya", "tuyos", "tuyas",
    "usted", "ustedes", "ud", "uds", "vosotros", "vosotras", "os",
    "su", "sus", "le", "les",
})

#: Sufijos verbales típicos de 1ª persona del plural ("tenemos", "vamos",
#: "logramos"). Recall-oriented: la stage LLM filtra los falsos positivos.
_FIRST_PERSON_PLURAL_SUFFIXES = ("emos", "amos", "imos", "remos")


def _normalize_deictic(mencion: str) -> str:
    """Normaliza una marca: sin acentos, minúsculas, sin parentéticos ni comillas."""
    s = unicodedata.normalize("NFKD", str(mencion or ""))
    s = "".join(c for c in s if not unicodedata.combining(c)).lower()
    s = re.sub(r"\(.*?\)", "", s)
    return s.strip().strip("'\"").strip()


def is_first_person_deictic(mencion: str) -> bool:
    """True si la mención es un deíctico de 1ª persona (refiere al enunciador).

    Normaliza (sin acentos, minúsculas), quita parentéticos y comillas, y
    compara contra una lista cerrada. Conservador: 'nosotros (gobierno)' → sí;
    'mi gobierno' o 'el enunciador y sus seguidores' → no.
    """
    return _normalize_deictic(mencion) in FIRST_PERSON_DEICTICS


def is_deictic(mencion: str) -> bool:
    """True si la marca contiene deixis de 1ª o 2ª persona (candidata a resolver).

    Recall-oriented: detecta pronombres/posesivos de 1ª y 2ª persona (incluso
    dentro de sintagmas, p. ej. "nuestro equipo") y verbos de 1ª persona del
    plural por sufijo ("tenemos"). Pensada como pre-filtro barato antes de la
    resolución por LLM, que descarta los falsos positivos.
    """
    s = _normalize_deictic(mencion)
    if not s:
        return False
    tokens = re.split(r"[^a-z0-9]+", s)
    for t in tokens:
        if not t:
            continue
        if t in FIRST_PERSON_DEICTICS or t in SECOND_PERSON_DEICTICS:
            return True
        if len(t) > 4 and t.endswith(_FIRST_PERSON_PLURAL_SUFFIXES):
            return True
    return False


def resolve_deictic_to_enunciador(
    link: dict[str, Any],
    enunciador: str,
) -> dict[str, Any]:
    """Atribuye un deíctico de 1ª persona al enunciador, en este discurso.

    Muta y devuelve `link`. Solo actúa si la mención es deíctica de 1ª persona,
    aún no tiene `actor_canonico`, y se conoce el enunciador. No toca la KB y no
    genera discovery (deja `es_nuevo=False`). Si ya hay canónico, se respeta.
    """
    if not enunciador:
        return link
    if link.get("actor_canonico"):
        return link
    if not is_first_person_deictic(str(link.get("actor_mencionado", ""))):
        return link
    link["actor_canonico"] = enunciador
    link["es_nuevo"] = False
    link["resuelto_por"] = "deixis_enunciador"
    return link
