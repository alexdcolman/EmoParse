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


def strip_accents_lower(value: str | None) -> str:
    """Normaliza a minúsculas sin tildes, para comparación tolerante."""
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(c for c in text if not unicodedata.combining(c))
    return text.lower()


def slugify(value: str | None) -> str:
    """Normaliza un texto a un identificador estable (canonical_id).

    Quita acentos, pasa a minúsculas y colapsa todo lo no alfanumérico en
    guiones bajos. Devuelve "" para entradas vacías.
    """
    text = strip_accents_lower(value)
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
    text = strip_accents_lower(value)
    tokens = [t for t in re.split(r"[^a-z0-9]+", text) if t and t not in STOPWORDS]
    return "_".join(tokens)[:_SLUG_MAXLEN]


# ══════════════════════════════════════════════════════════════════════════════
#  Saneamiento de etiquetas devueltas por el LLM
#
#  Un modelo puede devolver, en un campo que admite una sola categoría, dos
#  denominaciones alternativas ("Argentina / Estado argentino"), una
#  enumeración ("frustración, arrepentimiento"), una perífrasis ("sentirse
#  engañado") o restos de la sintaxis JSON de una generación truncada
#  ("indignación',"). El prompt lo desalienta; esto lo garantiza. Se aplica
#  solo a los campos de INFERENCIA: las marcas se transcriben literalmente y
#  no se tocan.
# ══════════════════════════════════════════════════════════════════════════════

#: Separadores con que un modelo ofrece alternativas dentro de un campo.
#: Solo vale la primera categoría.
_ALTERNATIVAS_RE = re.compile(r"\s*(?:/|\||\sy/o\s|\so\s)\s*")

#: Separadores de enumeración y de glosa dentro de una etiqueta de emoción.
_ENUMERACION_RE = re.compile(r"\s*[,;:]\s*")

#: Perífrasis que nominalizan mal una emoción ("sentirse engañado").
_PERIFRASIS_RE = re.compile(
    r"^(?:sentirse|sentir|estar|sentimiento\s+de|emoci[oó]n\s+de)\s+",
    re.IGNORECASE,
)

#: Signos que nunca abren ni cierran una etiqueta. Incluye los restos
#: tipográficos de una generación truncada (comillas, comas sueltas). Los
#: paréntesis quedan fuera: suelen ser parte de la etiqueta ("personas que
#: festejan (colectivo)").
_BORDES = " \t\r\n\"'“”‘’.,;:!¡¿?«»-–—_*"


def sanitize_referent_label(value: str | None) -> str:
    """Primera categoría de un campo de referente inferido, sin adornos.

    Recorta las alternativas ("Argentina / Estado argentino" da "Argentina"),
    los signos de borde y los espacios redundantes. No parte enumeraciones
    con coma, que en un referente suelen ser aposiciones ("Milei, el
    presidente"); esas las resuelve el desdoblamiento.
    """
    texto = _ALTERNATIVAS_RE.split(str(value or ""), maxsplit=1)[0]
    return re.sub(r"\s+", " ", texto.strip(_BORDES)).strip()


def sanitize_emotion_label(value: str | None) -> str:
    """Nombre de UNA emoción, sin alternativas, enumeraciones ni perífrasis.

    "curiosidad / ironía" da "curiosidad"; "frustración, arrepentimiento" da
    "frustración"; "alegría, justificación: …" da "alegría"; "sentirse
    engañado" da "engañado"; "indignación'," da "indignación".
    """
    texto = _ALTERNATIVAS_RE.split(str(value or ""), maxsplit=1)[0]
    texto = _ENUMERACION_RE.split(texto, maxsplit=1)[0]
    texto = _PERIFRASIS_RE.sub("", texto.strip(_BORDES))
    return re.sub(r"\s+", " ", texto.strip(_BORDES)).strip()
