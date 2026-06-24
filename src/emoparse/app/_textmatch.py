# ══════════════════════════════════════════════════════════════════════════════
#  emoparse.app._textmatch
#
#  Utilidades de matching de texto para la búsqueda del dashboard.
#
#  Soporta tres formas de consulta combinables:
#    - palabras sueltas        → cada palabra debe aparecer (AND).
#    - "frase exacta"          → la secuencia entre comillas debe aparecer.
#    - "… (la) …"              → término opcional entre paréntesis/corchetes:
#                                matchea con y sin ese término.
# ══════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

import itertools
import re
import unicodedata

#: Tope de variantes generadas por una frase con términos opcionales.
_MAX_VARIANTS = 16


def normalize(s: str | None) -> str:
    """Minúsculas, sin acentos, espacios colapsados."""
    text = unicodedata.normalize("NFKD", str(s or ""))
    text = "".join(c for c in text if not unicodedata.combining(c)).lower()
    return re.sub(r"\s+", " ", text).strip()


def _expand_optionals(phrase: str) -> list[str]:
    """Expande términos opcionales entre () o [] en todas sus variantes.

    "abandono del modelo de (la) libertad" →
        ["abandono del modelo de la libertad", "abandono del modelo de libertad"].
    """
    parts: list[tuple[str, bool]] = []  # (texto, es_opcional)
    last = 0
    for m in re.finditer(r"[\(\[]([^\)\]]*)[\)\]]", phrase):
        if m.start() > last:
            parts.append((phrase[last:m.start()], False))
        parts.append((m.group(1), True))
        last = m.end()
    if last < len(phrase):
        parts.append((phrase[last:], False))

    optional_idx = [i for i, (_, opt) in enumerate(parts) if opt]
    variants: list[str] = []
    for combo in itertools.product([True, False], repeat=len(optional_idx)):
        keep = dict(zip(optional_idx, combo))
        chunks = [
            txt for i, (txt, opt) in enumerate(parts)
            if not opt or keep.get(i, False)
        ]
        variants.append(normalize("".join(chunks)))
        if len(variants) >= _MAX_VARIANTS:
            break
    # Dedup preservando orden.
    seen: set[str] = set()
    out: list[str] = []
    for v in variants:
        if v and v not in seen:
            seen.add(v)
            out.append(v)
    return out or [normalize(phrase)]


def parse_query(query: str) -> list[list[str]]:
    """Parsea la query a una lista de 'matchers'.

    Cada matcher es una lista de variantes: la frase matchea si, para CADA
    matcher, al menos una de sus variantes es substring del texto normalizado.
    """
    matchers: list[list[str]] = []
    pos = 0
    pattern = re.compile(r"\"([^\"]*)\"|'([^']*)'|(\S+)")
    for m in pattern.finditer(query):
        phrase = m.group(1) if m.group(1) is not None else m.group(2)
        if phrase is not None:  # entre comillas → frase exacta (con opcionales)
            matchers.append(_expand_optionals(phrase))
        else:
            word = m.group(3)
            if "(" in word or "[" in word:
                matchers.append(_expand_optionals(word))
            else:
                matchers.append([normalize(word)])
    return [mt for mt in matchers if any(mt)]


def matches(text_norm: str, matchers: list[list[str]]) -> bool:
    """True si `text_norm` (ya normalizado) satisface todos los matchers."""
    if not matchers:
        return False
    return all(
        any(v and v in text_norm for v in matcher)
        for matcher in matchers
    )
