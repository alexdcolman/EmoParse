"""Contratos de las utilidades compartidas por la suite."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, RootModel

from tests.factories import FakeBackend, model_from_schema


class _Child(BaseModel):
    label: Literal["ok"]


class _Payload(BaseModel):
    name: str
    count: int
    child: _Child


class _Batch(RootModel[list[_Payload]]):
    pass


def test_model_factory_derives_nested_fields_from_schema() -> None:
    payload = model_from_schema(_Payload)

    assert payload.name
    assert payload.count == 1
    assert payload.child.label == "ok"


def test_model_factory_respects_root_collection_length() -> None:
    batch = model_from_schema(_Batch, collection_length=3)

    assert len(batch.root) == 3
    assert all(item.child.label == "ok" for item in batch.root)


def test_fake_backend_builds_requested_schema_and_records_call() -> None:
    backend = FakeBackend()

    response = backend.generate(
        "sistema",
        "usuario",
        schema=_Batch,
        max_items=2,
        temperature=0.2,
        seed=7,
    )

    assert isinstance(response.parsed, _Batch)
    assert len(response.parsed.root) == 2
    assert backend.calls[0].schema is _Batch
    assert backend.calls[0].temperature == 0.2
    assert backend.calls[0].seed == 7
