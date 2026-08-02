"""Propiedades estables del conversor Pydantic a GBNF."""

from __future__ import annotations

import inspect
from typing import Literal

import pytest
from pydantic import BaseModel, RootModel

import emoparse.core.schemas as schemas_module
from emoparse.core.grammar import PRIMITIVE_RULES, schema_to_gbnf


class _Simple(BaseModel):
    name: str
    count: int
    enabled: bool


class _NumericLiteral(BaseModel):
    value: Literal[1, 2, 3]


class _Item(BaseModel):
    unit_idx: int
    text: str


class _Batch(RootModel[list[_Item]]):
    pass


def _public_schema_classes() -> list[type[BaseModel]]:
    result: list[type[BaseModel]] = []
    for name, value in vars(schemas_module).items():
        if name.startswith("_") or not inspect.isclass(value):
            continue
        if value.__module__ != schemas_module.__name__:
            continue
        if not issubclass(value, BaseModel) or value is schemas_module.StrictBase:
            continue
        result.append(value)
    return result


def test_grammar_has_root_and_reusable_primitives() -> None:
    grammar = schema_to_gbnf(_Simple)

    assert grammar.startswith("root ::=")
    for rule in ("string", "integer", "number", "boolean", "null", "ws"):
        assert f"{rule} ::=" in grammar


def test_string_primitive_forbids_empty_strings_without_unbounded_whitespace() -> None:
    assert 'string ::= "\\\"" strchar' in PRIMITIVE_RULES
    assert "strsep? strchar" in PRIMITIVE_RULES
    assert "strunit*" not in PRIMITIVE_RULES


def test_required_fields_appear_as_json_literals() -> None:
    grammar = schema_to_gbnf(_Simple)

    for field in _Simple.model_fields:
        assert f'\\"{field}\\"' in grammar


def test_root_list_honors_exact_max_items() -> None:
    grammar = schema_to_gbnf(_Batch, max_items=3)
    root_line = next(line for line in grammar.splitlines() if line.startswith("root ::="))

    assert "root" in root_line
    assert grammar.count('\\"unit_idx\\"') >= 1
    assert grammar.count('\\"text\\"') >= 1
    assert root_line.count("Item") == 3


def test_numeric_literals_are_supported() -> None:
    grammar = schema_to_gbnf(_NumericLiteral)

    assert '"1"' in grammar
    assert '"2"' in grammar
    assert '"3"' in grammar


@pytest.mark.parametrize("schema", _public_schema_classes(), ids=lambda cls: cls.__name__)
def test_all_public_llm_schemas_compile(schema: type[BaseModel]) -> None:
    grammar = schema_to_gbnf(schema)

    assert "root ::=" in grammar
    assert "<<placeholder>>" not in grammar
