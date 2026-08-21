"""Controles conservadores de calidad sobre texto libre generado por LLM.

La validación estructural garantiza la forma del payload, pero no el idioma de
los strings abiertos. Este módulo detecta spans con letras no latinas que no
provienen de la entrada y permite reparar, como máximo, una ocurrencia sin
regenerar ni reinterpretar el resto del análisis estructurado.
"""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from emoparse.core.backend.base import LLMBackend
from emoparse.core.backend.exceptions import BackendError
from emoparse.core.prompts import output_quality as prompts


class OutputQualityError(BackendError):
    """El payload es estructuralmente válido pero falla un control de calidad."""


class _ReplacementSchema(BaseModel):
    """Respuesta mínima para una reparación léxica puntual."""

    model_config = ConfigDict(extra="forbid")

    reemplazo: str = Field(min_length=1, max_length=80)


@dataclass(frozen=True)
class UnexpectedScriptSpan:
    """Span de texto con al menos una letra de escritura no latina."""

    start: int
    end: int
    text: str


TextFieldPath = tuple[str, ...]


def find_unexpected_script_spans(
    text: str,
    *,
    source_text: str = "",
) -> tuple[UnexpectedScriptSpan, ...]:
    """Detecta palabras con letras no latinas que no aparecen en la entrada.

    Se usa la base Unicode de Python en lugar de una lista cerrada de idiomas:
    toda letra cuyo nombre Unicode no pertenezca al alfabeto latino se considera
    candidata. Marcas combinantes adyacentes se incorporan al mismo span para no
    fragmentar escrituras como devanagari.

    Un span se acepta cuando aparece literalmente, tras normalización Unicode y
    ``casefold``, en ``source_text``. Esto preserva nombres propios, citas,
    hashtags u otro material no latino que el modelo haya copiado de la unidad.
    """
    if not text:
        return ()

    source_tokens = {
        _normalise_for_match(span.text) for span in _raw_unexpected_script_spans(source_text)
    }
    return tuple(
        span
        for span in _raw_unexpected_script_spans(text)
        if _normalise_for_match(span.text) not in source_tokens
    )


def _raw_unexpected_script_spans(text: str) -> tuple[UnexpectedScriptSpan, ...]:
    """Extrae spans no latinos sin aplicar todavía la excepción por fuente."""
    spans: list[UnexpectedScriptSpan] = []
    seen: set[tuple[int, int]] = set()
    i = 0
    while i < len(text):
        if not _is_unexpected_letter(text[i]):
            i += 1
            continue

        start = i
        while start > 0 and _is_word_script_char(text[start - 1]):
            start -= 1
        end = i + 1
        while end < len(text) and _is_word_script_char(text[end]):
            end += 1

        key = (start, end)
        if key not in seen:
            seen.add(key)
            spans.append(UnexpectedScriptSpan(start=start, end=end, text=text[start:end]))
        i = end
    return tuple(spans)


def repair_model_text_fields_once(
    model: BaseModel,
    *,
    field_paths: tuple[TextFieldPath, ...],
    source_text: str,
    backend: LLMBackend,
    context_chars: int = 64,
) -> BaseModel:
    """Repara como máximo un span contaminado dentro de campos seleccionados.

    Sólo cambia el substring detectado. El resto del payload se conserva a
    partir de ``model_dump`` y el modelo completo se revalida con su schema
    original. Si queda otra contaminación, si la reparación falla o si el
    reemplazo rompe el contrato, se eleva ``OutputQualityError`` para que el
    caller deje pendiente únicamente ese ítem.
    """
    first: tuple[TextFieldPath, str, UnexpectedScriptSpan] | None = None
    for path in field_paths:
        value = _get_path(model, path)
        if not isinstance(value, str) or not value:
            continue
        spans = find_unexpected_script_spans(value, source_text=source_text)
        if spans:
            first = (path, value, spans[0])
            break

    if first is None:
        return model

    path, value, span = first
    left = max(0, span.start - context_chars)
    right = min(len(value), span.end + context_chars)
    context = value[left:right]
    replacement = _request_replacement(
        backend,
        contaminated=span.text,
        context=context,
    )

    repaired_value = value[: span.start] + replacement + value[span.end :]
    payload = model.model_dump(mode="python")
    _set_path(payload, path, repaired_value)
    try:
        repaired = type(model).model_validate(payload)
    except ValidationError as exc:
        raise OutputQualityError("la reparación puntual dejó el payload fuera de contrato") from exc

    remaining = _remaining_contamination(
        repaired,
        field_paths=field_paths,
        source_text=source_text,
    )
    if remaining is not None:
        remaining_path, remaining_span = remaining
        joined = ".".join(remaining_path)
        raise OutputQualityError(
            f"persistió escritura inesperada en {joined}: {remaining_span.text!r}"
        )
    return repaired


def _request_replacement(
    backend: LLMBackend,
    *,
    contaminated: str,
    context: str,
) -> str:
    response = backend.generate(
        system=prompts.render_system(),
        user=prompts.render_user(contaminated=contaminated, context=context),
        schema=_ReplacementSchema,
        max_tokens=48,
        temperature=0.0,
    )
    parsed = response.parsed
    if not isinstance(parsed, _ReplacementSchema):
        raise OutputQualityError("la reparación no devolvió un reemplazo estructurado")

    replacement = parsed.reemplazo.strip()
    if not replacement:
        raise OutputQualityError("la reparación devolvió un reemplazo vacío")
    if any(char in replacement for char in ('"', "\\", "\r", "\n")):
        raise OutputQualityError("la reparación devolvió caracteres no permitidos")
    if find_unexpected_script_spans(replacement):
        raise OutputQualityError(f"la reparación conservó escritura inesperada: {replacement!r}")
    return replacement


def _remaining_contamination(
    model: BaseModel,
    *,
    field_paths: tuple[TextFieldPath, ...],
    source_text: str,
) -> tuple[TextFieldPath, UnexpectedScriptSpan] | None:
    for path in field_paths:
        value = _get_path(model, path)
        if not isinstance(value, str) or not value:
            continue
        spans = find_unexpected_script_spans(value, source_text=source_text)
        if spans:
            return path, spans[0]
    return None


def _get_path(model: BaseModel, path: TextFieldPath) -> Any:
    value: Any = model
    for part in path:
        value = getattr(value, part)
    return value


def _set_path(payload: dict[str, Any], path: TextFieldPath, value: str) -> None:
    target: dict[str, Any] = payload
    for part in path[:-1]:
        child = target[part]
        if not isinstance(child, dict):
            raise OutputQualityError(f"ruta de texto inválida: {'.'.join(path)}")
        target = child
    target[path[-1]] = value


def _is_unexpected_letter(char: str) -> bool:
    if not char.isalpha():
        return False
    name = unicodedata.name(char, "")
    return bool(name) and "LATIN" not in name


def _is_word_script_char(char: str) -> bool:
    category = unicodedata.category(char)
    return char.isalpha() or category.startswith("M") or char in {"\u200c", "\u200d"}


def _normalise_for_match(text: str) -> str:
    return unicodedata.normalize("NFKC", text).casefold()
