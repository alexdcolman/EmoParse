# ══════════════════════════════════════════════════════════════════════════════
#  emoparse.core.text
#
#  Utilidades de texto compartidas (sin dependencias de storage ni de app).
# ══════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

import re
import unicodedata

#: Longitud máxima de un slug (consistente con los canonical_id en la DB).
_SLUG_MAXLEN = 64


#: Palabras funcionales que no aportan a la identidad de un referente:
#: artículos, demostrativos, preposiciones y conjunciones de uso frecuente.
#: Se descartan al construir un canónico para que "la población mundial" y
#: "una población mundial" colapsen en el mismo referente. Es la misma lista
#: que usa el clustering léxico (`pipeline.coref`), de modo que el match por
#: tokens y la construcción del slug compartan criterio.
STOPWORDS: frozenset[str] = frozenset({
    "el", "la", "los", "las", "lo",
    "un", "una", "unos", "unas",
    "de", "del", "al",
    "y", "o", "u",
    "a", "en", "con", "por", "para", "sobre",
    "que", "se", "su", "sus",
    "mi", "tu",
    "este", "esta", "estos", "estas",
    "ese", "esa", "esos", "esas",
    "aquel", "aquella", "aquellos", "aquellas",
})


def _strip_accents_lower(value: str | None) -> str:
    """Normaliza a minúsculas sin tildes."""
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(c for c in text if not unicodedata.combining(c))
    return text.lower()


def slugify(value: str | None) -> str:
    """Normaliza un texto a un identificador estable (canonical_id).

    Quita acentos, pasa a minúsculas y colapsa todo lo no alfanumérico en
    guiones bajos. Devuelve "" para entradas vacías.
    """
    text = _strip_accents_lower(value)
    text = re.sub(r"[^a-z0-9]+", "_", text)
    return text.strip("_")[:_SLUG_MAXLEN]


def canonical_slug(value: str | None) -> str:
    """Construye un canonical_id descartando palabras funcionales.

    Igual que `slugify`, pero elimina los tokens de `STOPWORDS` (artículos,
    demostrativos, preposiciones y conjunciones). Así "la población mundial" y
    "una población mundial" producen `poblacion_mundial`, y "el presidente de
    la nación argentina" produce `presidente_nacion_argentina`.

    Es idempotente sobre slugs ya limpios (un canonical_id sin palabras
    funcionales se devuelve igual).
    """
    text = _strip_accents_lower(value)
    tokens = [t for t in re.split(r"[^a-z0-9]+", text) if t and t not in STOPWORDS]
    return "_".join(tokens)[:_SLUG_MAXLEN]
