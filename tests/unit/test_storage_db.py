# ══════════════════════════════════════════════════════════════════════════════
#  tests.unit.test_storage_db
#
#  Tests del wrapper Database. Verifica:
#   - Connection-per-thread.
#   - Transacciones con rollback en excepciones.
#   - WAL y FK habilitados.
#   - Concurrencia básica entre threads (lectura no bloquea escritura).
# ══════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

from pathlib import Path

import pytest

from emoparse.storage.db import Database


# ══════════════════════════════════════════════════════════════════════════════
#  Fixtures
# ══════════════════════════════════════════════════════════════════════════════


@pytest.fixture
def db(tmp_path: Path) -> Database:
    """Database temporal por test. tmp_path se limpia automáticamente."""
    return Database(tmp_path / "test.sqlite")


# ══════════════════════════════════════════════════════════════════════════════
#  Tests
# ══════════════════════════════════════════════════════════════════════════════


class TestBasics:

    def test_db_file_created_on_first_use(self, tmp_path: Path) -> None:
        path = tmp_path / "subdir" / "new.sqlite"
        assert not path.parent.exists()
        db = Database(path)
        # Trigger lazy connection.
        db.execute("CREATE TABLE x (a INT)")
        assert path.exists()

    def test_execute_simple(self, db: Database) -> None:
        db.execute("CREATE TABLE foo (id INT, val TEXT)")
        db.execute("INSERT INTO foo VALUES (?, ?)", (1, "uno"))
        row = db.execute("SELECT * FROM foo").fetchone()
        assert row["id"] == 1
        assert row["val"] == "uno"

    def test_row_factory_allows_named_access(self, db: Database) -> None:
        """sqlite3.Row permite acceso por nombre y por índice."""
        db.execute("CREATE TABLE foo (id INT, val TEXT)")
        db.execute("INSERT INTO foo VALUES (?, ?)", (42, "x"))
        row = db.execute("SELECT * FROM foo").fetchone()
        # Por índice.
        assert row[0] == 42
        # Por nombre.
        assert row["id"] == 42

    def test_table_exists(self, db: Database) -> None:
        assert not db.table_exists("foo")
        db.execute("CREATE TABLE foo (a INT)")
        assert db.table_exists("foo")


class TestPragmas:

    def test_wal_mode_active(self, db: Database) -> None:
        row = db.execute("PRAGMA journal_mode").fetchone()
        assert row[0].lower() == "wal"

    def test_foreign_keys_active(self, db: Database) -> None:
        row = db.execute("PRAGMA foreign_keys").fetchone()
        assert row[0] == 1

    def test_foreign_key_violation_raises(self, db: Database) -> None:
        """Con FKs activas, violar una constraint lanza error."""
        db.execute_script(
            """
            CREATE TABLE parent (id INT PRIMARY KEY);
            CREATE TABLE child (
                id INT,
                parent_id INT,
                FOREIGN KEY (parent_id) REFERENCES parent(id)
            );
            """
        )
        with pytest.raises(Exception):
            # parent_id=99 no existe en parent.
            db.execute("INSERT INTO child VALUES (1, 99)")


class TestTransactions:

    def test_transaction_commits_on_success(self, db: Database) -> None:
        db.execute("CREATE TABLE foo (a INT)")
        with db.transaction() as cur:
            cur.execute("INSERT INTO foo VALUES (1)")
            cur.execute("INSERT INTO foo VALUES (2)")
        # Después del with, ambos commits.
        rows = db.execute("SELECT * FROM foo ORDER BY a").fetchall()
        assert [r[0] for r in rows] == [1, 2]

    def test_transaction_rollback_on_exception(self, db: Database) -> None:
        db.execute("CREATE TABLE foo (a INT)")
        try:
            with db.transaction() as cur:
                cur.execute("INSERT INTO foo VALUES (1)")
                raise RuntimeError("simulated")
        except RuntimeError:
            pass
        # La fila no se persistió.
        rows = db.execute("SELECT * FROM foo").fetchall()
        assert rows == []

    def test_executemany_inside_transaction(self, db: Database) -> None:
        """Bulk insert dentro de transaction es eficiente."""
        db.execute("CREATE TABLE foo (a INT)")
        with db.transaction() as cur:
            cur.executemany(
                "INSERT INTO foo VALUES (?)",
                [(i,) for i in range(100)],
            )
        rows = db.execute("SELECT COUNT(*) FROM foo").fetchone()
        assert rows[0] == 100


class TestThreadSafety:

    def test_separate_connections_per_thread(self, db: Database) -> None:
        """Cada hilo abre su propia conexión.

        Verificamos que el connection-per-thread funciona: dos hilos
        pueden leer simultáneamente sin compartir estado.
        """
        import threading

        db.execute("CREATE TABLE foo (a INT)")
        db.execute("INSERT INTO foo VALUES (42)")

        results: dict[int, int] = {}

        def reader(tid: int) -> None:
            row = db.execute("SELECT a FROM foo").fetchone()
            results[tid] = row[0]

        threads = [threading.Thread(target=reader, args=(i,)) for i in range(3)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert results == {0: 42, 1: 42, 2: 42}
