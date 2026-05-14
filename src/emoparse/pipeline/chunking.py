# ══════════════════════════════════════════════════════════════════════════════
#  emoparse.pipeline.chunking
#
#  Splitter de texto en oraciones.
# ══════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

import re

#: Abreviaciones comunes en español que no deben terminar oración.
_ABBREVIATIONS: frozenset[str] = frozenset({
    "sr", "sra", "srta",
    "dr", "dra",
    "ing", "lic", "prof",
    "av", "avda", "calle",
    "ej", "etc", "vs", "p", "pp",
    "no",  # "n.°" se escribe a veces "no.",
})

#: Regex para detectar fin de oración.
_SENTENCE_END = re.compile(
    r"([.!?]+[\")\]]?)\s+(?=[A-ZÁÉÍÓÚÑÜ¡¿])"
)


def split_into_sentences(
    text: str,
    *,
    max_chars: int = 400,
    min_chars: int = 15,
) -> list[str]:
    """Parte un texto en oraciones para análisis por-frase."""
    if not text or not text.strip():
        return []

    raw_sentences = _split_with_abbreviations(text)

    expanded: list[str] = []
    for s in raw_sentences:
        if len(s) <= max_chars:
            expanded.append(s)
        else:
            expanded.extend(_split_long_sentence(s, max_chars))

    merged = _merge_short_sentences(expanded, min_chars)

    return [s.strip() for s in merged if s.strip()]


# ══════════════════════════════════════════════════════════════════════════════
#  Helpers internos
# ══════════════════════════════════════════════════════════════════════════════


def _split_with_abbreviations(text: str) -> list[str]:
    """Split por fin de oración respetando abreviaciones."""
    sentences: list[str] = []
    last_end = 0

    for match in _SENTENCE_END.finditer(text):
        end_punct = match.group(1)
        word_before = _last_word_before(text, match.start())
        if word_before.lower() in _ABBREVIATIONS:
            continue

        sentence = text[last_end:match.start() + len(end_punct)]
        sentences.append(sentence.strip())
        last_end = match.end()

    tail = text[last_end:].strip()
    if tail:
        sentences.append(tail)

    return sentences


def _last_word_before(text: str, idx: int) -> str:
    """Devuelve la palabra que termina justo antes de `idx`."""
    end = idx
    start = end - 1
    while start >= 0 and not text[start].isspace():
        start -= 1
    return text[start + 1:end]


def _split_long_sentence(sentence: str, max_chars: int) -> list[str]:
    """Sub-divide una oración demasiado larga."""
    if len(sentence) <= max_chars:
        return [sentence]

    parts = [p.strip() for p in sentence.split(";") if p.strip()]
    if len(parts) > 1 and all(len(p) <= max_chars for p in parts):
        return parts

    comma_parts = [p.strip() for p in sentence.split(",") if p.strip()]
    if len(comma_parts) > 1:
        result: list[str] = []
        current = ""
        for p in comma_parts:
            candidate = p if not current else f"{current}, {p}"
            if len(candidate) <= max_chars:
                current = candidate
            else:
                if current:
                    result.append(current)
                current = p
        if current:
            result.append(current)
        if all(len(r) <= max_chars for r in result):
            return result

    return [sentence]


def _merge_short_sentences(
    sentences: list[str],
    min_chars: int,
) -> list[str]:
    """Combina oraciones cortas con la siguiente."""
    if not sentences:
        return []

    result: list[str] = []
    buffer = ""

    for s in sentences:
        if buffer:
            buffer = f"{buffer} {s}"
        else:
            buffer = s

        if len(buffer) >= min_chars:
            result.append(buffer)
            buffer = ""

    # Si quedó algo en el buffer (oración(es) corta(s) al final), juntarlo
    # con la última unidad ya emitida. Si no hay unidad previa, emitir solo.
    if buffer:
        if result:
            result[-1] = f"{result[-1]} {buffer}"
        else:
            result.append(buffer)

    return result
