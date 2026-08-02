"""Fábricas compartidas para pruebas de EmoParse."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from datetime import UTC, date, datetime
from enum import Enum
from types import NoneType, UnionType
from typing import Annotated, Any, Literal, Union, get_args, get_origin

from pydantic import BaseModel, RootModel

from emoparse.core.backend.base import LLMBackend, LLMResponse, TokenUsage


@dataclass(frozen=True, slots=True)
class LLMCall:
    """Registro inmutable de una llamada realizada al backend falso."""

    system: str
    user: str
    schema: type[BaseModel] | None
    max_tokens: int | None
    temperature: float | None
    seed: int | None
    stop: tuple[str, ...]
    reset_before: bool
    max_items: int | None
    images: tuple[str, ...]


def _unwrap_annotated(annotation: Any) -> Any:
    while get_origin(annotation) is Annotated:
        annotation = get_args(annotation)[0]
    return annotation


def minimal_value(annotation: Any, *, collection_length: int = 1) -> Any:
    """Construye un valor mínimo válido a partir de una anotación tipada.

    La fábrica deriva la estructura del schema vigente. No replica listas de
    campos ni payloads de agentes en los tests.
    """
    annotation = _unwrap_annotated(annotation)
    origin = get_origin(annotation)
    args = get_args(annotation)

    if annotation in (Any, object):
        return "valor"
    if annotation is NoneType:
        return None
    if origin is Literal:
        return args[0]
    if origin in (Union, UnionType):
        candidates = [arg for arg in args if arg is not NoneType]
        return (
            minimal_value(candidates[0], collection_length=collection_length)
            if candidates
            else None
        )
    if origin in (list, set, frozenset):
        item = minimal_value(args[0] if args else Any)
        values = [item for _ in range(max(1, collection_length))]
        if origin is set:
            return set(values)
        if origin is frozenset:
            return frozenset(values)
        return values
    if origin is tuple:
        if len(args) == 2 and args[1] is Ellipsis:
            return (minimal_value(args[0]),)
        return tuple(minimal_value(arg) for arg in args)
    if origin is dict:
        return {}

    if isinstance(annotation, type) and issubclass(annotation, Enum):
        return next(iter(annotation)).value
    if isinstance(annotation, type) and issubclass(annotation, BaseModel):
        return model_from_schema(annotation, collection_length=collection_length)
    if annotation is str:
        return "texto"
    if annotation is int:
        return 1
    if annotation is float:
        return 1.0
    if annotation is bool:
        return True
    if annotation is datetime:
        return datetime(2026, 1, 1, tzinfo=UTC)
    if annotation is date:
        return date(2026, 1, 1)

    try:
        return annotation()
    except Exception:
        return "valor"


def model_from_schema(
    schema: type[BaseModel],
    *,
    collection_length: int = 1,
    overrides: dict[str, Any] | None = None,
) -> BaseModel:
    """Construye una instancia válida leyendo los campos del modelo Pydantic."""
    overrides = dict(overrides or {})

    if issubclass(schema, RootModel):
        root_annotation = schema.model_fields["root"].annotation
        root_value = minimal_value(
            root_annotation,
            collection_length=collection_length,
        )
        if "root" in overrides:
            root_value = overrides["root"]
        return schema.model_validate(root_value)

    payload: dict[str, Any] = {}
    for name, field in schema.model_fields.items():
        if name in overrides:
            payload[name] = overrides[name]
            continue
        if field.alias and field.alias in overrides:
            payload[field.alias] = overrides[field.alias]
            continue
        if not field.is_required():
            continue
        key = field.alias if isinstance(field.alias, str) else name
        payload[key] = minimal_value(field.annotation)

    payload.update({k: v for k, v in overrides.items() if k not in payload})
    return schema.model_validate(payload)


class FakeBackend(LLMBackend):
    """Backend determinista que deriva respuestas de los schemas solicitados."""

    def __init__(
        self,
        alias: str = "fake",
        responses: list[Any] | None = None,
        *,
        healthy: bool = True,
    ) -> None:
        self.alias = alias
        self.calls: list[LLMCall] = []
        self._responses = deque(responses or [])
        self._healthy = healthy
        self.closed = False
        self.reset_count = 0

    def generate(
        self,
        system: str,
        user: str,
        *,
        schema: type[BaseModel] | None = None,
        max_tokens: int | None = None,
        temperature: float | None = None,
        seed: int | None = None,
        stop: list[str] | None = None,
        reset_before: bool = False,
        max_items: int | None = None,
        images: list[str] | None = None,
    ) -> LLMResponse:
        self.calls.append(
            LLMCall(
                system=system,
                user=user,
                schema=schema,
                max_tokens=max_tokens,
                temperature=temperature,
                seed=seed,
                stop=tuple(stop or ()),
                reset_before=reset_before,
                max_items=max_items,
                images=tuple(images or ()),
            )
        )
        if reset_before:
            self.reset_state()

        queued = self._responses.popleft() if self._responses else None
        if isinstance(queued, Exception):
            raise queued
        if isinstance(queued, LLMResponse):
            return queued

        if schema is None:
            raw = "respuesta" if queued is None else str(queued)
            parsed = None
        else:
            if queued is None:
                parsed = model_from_schema(
                    schema,
                    collection_length=max_items or 1,
                )
            elif isinstance(queued, BaseModel):
                parsed = queued
            else:
                parsed = schema.model_validate(queued)
            raw = parsed.model_dump_json(by_alias=True)

        return LLMResponse(
            parsed=parsed,
            raw=raw,
            usage=TokenUsage(prompt_tokens=1, completion_tokens=1),
            latency_ms=1.0,
            model_alias=self.alias,
            cache_hit=False,
            finish_reason="stop",
        )

    def healthcheck(self) -> bool:
        return self._healthy

    def close(self) -> None:
        self.closed = True

    def reset_state(self) -> None:
        self.reset_count += 1
