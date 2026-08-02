# ══════════════════════════════════════════════════════════════════════════════
#  tests/andamio/test_database_transaction
#
#  Regresiones del ciclo de vida de transacciones SQLite.
# ══════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

import pytest

from emoparse.storage.db import Database


class _Cursor:
    def __init__(self) -> None:
        self.closed = False

    def close(self) -> None:
        self.closed = True


class _Connection:
    def __init__(
        self,
        *,
        fail_begin: Exception | None = None,
        fail_commit: Exception | None = None,
        fail_rollback: Exception | None = None,
    ) -> None:
        self.fail_begin = fail_begin
        self.fail_commit = fail_commit
        self.fail_rollback = fail_rollback
        self.in_transaction = False
        self.statements: list[str] = []
        self.cursor_instance = _Cursor()

    def execute(self, sql: str, params: Any = ()) -> None:
        del params
        self.statements.append(sql)
        if sql == "BEGIN IMMEDIATE":
            if self.fail_begin is not None:
                raise self.fail_begin
            self.in_transaction = True
        elif sql == "COMMIT":
            if self.fail_commit is not None:
                raise self.fail_commit
            self.in_transaction = False
        elif sql == "ROLLBACK":
            if self.fail_rollback is not None:
                raise self.fail_rollback
            self.in_transaction = False

    def cursor(self) -> _Cursor:
        return self.cursor_instance


def _database_with_connection(tmp_path: Path, conn: _Connection) -> Database:
    db = Database(tmp_path / "transaction.sqlite")
    db_as_any: Any = db
    db_as_any._get_connection = lambda: conn
    return db


@pytest.mark.unit
def test_begin_error_is_not_replaced_by_rollback_error(tmp_path: Path) -> None:
    original = sqlite3.OperationalError("database is locked")
    conn = _Connection(
        fail_begin=original,
        fail_rollback=sqlite3.OperationalError("no transaction is active"),
    )
    db = _database_with_connection(tmp_path, conn)

    with pytest.raises(sqlite3.OperationalError, match="database is locked"):
        with db.transaction():
            pytest.fail("el cuerpo no debe ejecutarse")

    assert conn.statements == ["BEGIN IMMEDIATE"]


@pytest.mark.unit
def test_body_error_rolls_back_and_closes_cursor(tmp_path: Path) -> None:
    conn = _Connection()
    db = _database_with_connection(tmp_path, conn)

    with pytest.raises(ValueError, match="fallo del cuerpo"):
        with db.transaction():
            raise ValueError("fallo del cuerpo")

    assert conn.statements == ["BEGIN IMMEDIATE", "ROLLBACK"]
    assert conn.cursor_instance.closed is True


@pytest.mark.unit
def test_commit_error_attempts_rollback_without_masking_original(tmp_path: Path) -> None:
    conn = _Connection(
        fail_commit=sqlite3.OperationalError("disk I/O error"),
        fail_rollback=sqlite3.OperationalError("rollback error"),
    )
    db = _database_with_connection(tmp_path, conn)

    with pytest.raises(sqlite3.OperationalError, match="disk I/O error"):
        with db.transaction():
            pass

    assert conn.statements == ["BEGIN IMMEDIATE", "COMMIT", "ROLLBACK"]
    assert conn.cursor_instance.closed is True
