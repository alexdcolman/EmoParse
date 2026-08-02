"""Configuración y fixtures compartidas de la suite estable."""

from __future__ import annotations

import sys
from collections.abc import Iterator
from pathlib import Path

import pytest
from loguru import logger

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from emoparse.storage.db import Database  # noqa: E402
from emoparse.storage.models import RunContext  # noqa: E402
from emoparse.storage.runs import RunsRepository  # noqa: E402
from tests.factories import FakeBackend  # noqa: E402


@pytest.fixture(autouse=True)
def _isolate_resources(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Cierra conexiones creadas por cada test y aísla los sinks de Loguru."""
    databases: list[Database] = []
    original_init = Database.__init__

    def tracked_init(self: Database, *args, **kwargs) -> None:
        original_init(self, *args, **kwargs)
        databases.append(self)

    monkeypatch.setattr(Database, "__init__", tracked_init)
    logger.remove()
    logger.add(lambda _: None)
    yield
    for db in reversed(databases):
        db.close_thread_connection()
    logger.remove()
    logger.add(lambda _: None)


@pytest.fixture
def project_root() -> Path:
    return ROOT


@pytest.fixture
def database(tmp_path: Path) -> Iterator[Database]:
    db = Database(tmp_path / "run_test.sqlite")
    yield db
    db.close_thread_connection()


@pytest.fixture
def run_context() -> RunContext:
    return RunContext(run_id="run_test")


@pytest.fixture
def bootstrapped_db(database: Database, run_context: RunContext) -> Database:
    RunsRepository(database).bootstrap(run_context)
    return database


@pytest.fixture
def fake_backend() -> FakeBackend:
    return FakeBackend()


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """Marca por capa sin repetir decoradores en cada archivo."""
    for item in items:
        path = Path(str(item.path))
        if "contrato" in path.parts:
            item.add_marker(pytest.mark.unit)
            item.add_marker(pytest.mark.contract)
        elif "andamio" in path.parts:
            item.add_marker(pytest.mark.unit)
            item.add_marker(pytest.mark.scaffold)
        elif "integracion_llm" in path.parts:
            item.add_marker(pytest.mark.integration)
            item.add_marker(pytest.mark.llm)
