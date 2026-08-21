# ══════════════════════════════════════════════════════════════════════════════
#  emoparse.pipeline.deixis
#
#  Resolución determinista de las marcas y las inferencias que nombran una
#  posición del dispositivo enunciativo en vez de un referente.
#
#  Las menciones de actor en 1ª persona ("yo", "mí", "nosotros"…) refieren al
#  enunciador del discurso, y una inferencia que devuelve la etiqueta del rol
#  ("el enunciador") refiere a quien lo ocupa. Se resuelven por discurso
#  (nunca a la KB).
# ══════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

import re
from typing import Any

from emoparse.storage.referencia import is_deictic as is_deictic
from emoparse.storage.referencia import (
    is_first_person_deictic,
    normalize_deictic,
)

#: Etiquetas de rol enunciativo que el modelo devuelve como si fueran
#: referentes ("el enunciador", "los enunciatarios"). Nombran una posición del
#: dispositivo, no designan a nadie: el referente concreto está en la
#: estructura enunciativa del discurso.
_ROL_ENUNCIADOR = frozenset(
    {
        "enunciador",
        "enunciadora",
        "enunciante",
        "el que enuncia",
    }
)
_ROL_ENUNCIATARIO = frozenset(
    {
        "enunciatario",
        "enunciataria",
        "enunciatarios",
        "enunciatarias",
        "auditorio",
        "destinatario",
        "destinatarios",
        "destinataria",
        "destinatarias",
        "publico",
        "audiencia",
    }
)

#: Determinantes iniciales que no cambian el rol nombrado ("el enunciador").
_DETERMINANTE_RE = re.compile(r"^(?:el|la|los|las|un|una|unos|unas)\s+")


def resolver_rol_enunciativo(
    inferencia: str,
    enunciador: str,
    enunciatarios: list[str] | None = None,
) -> str:
    """Referente concreto de una inferencia que solo nombra un rol enunciativo.

    El modelo devuelve a veces "el enunciador" o "los enunciatarios" en el
    campo de inferencia, que pide un referente. La etiqueta se resuelve contra
    la estructura enunciativa del discurso: el enunciador, o el enunciatario
    cuando hay uno solo (con varios no se adivina). Devuelve "" si la
    inferencia no es una etiqueta de rol o si el rol no tiene referente
    conocido; en ese caso el valor original queda intacto.
    """
    s = _DETERMINANTE_RE.sub("", normalize_deictic(inferencia))
    if not s:
        return ""
    if s in _ROL_ENUNCIADOR:
        return str(enunciador or "").strip()
    if s in _ROL_ENUNCIATARIO:
        nombres = [str(e).strip() for e in (enunciatarios or []) if str(e).strip()]
        return nombres[0] if len(nombres) == 1 else ""
    return ""


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
