# ══════════════════════════════════════════════════════════════════════════════
#  emoparse.storage.db
#
#  Wrapper finito de sqlite3 stdlib.
# ══════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

import sqlite3
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any

from loguru import logger


# ══════════════════════════════════════════════════════════════════════════════
#  Adaptadores explícitos para datetime
#
#  Python 3.12 deprecó los adaptadores default para datetime.
#  Convención: se serializa como ISO 8601 string (legible, ordenable, portable).
# ══════════════════════════════════════════════════════════════════════════════

def _adapt_datetime_iso(val: datetime) -> str:
    """datetime → str ISO 8601."""
    return val.isoformat()


def _convert_datetime_iso(val: bytes) -> datetime:
    """bytes ISO → datetime."""
    return datetime.fromisoformat(val.decode("utf-8"))


sqlite3.register_adapter(datetime, _adapt_datetime_iso)
sqlite3.register_converter("TIMESTAMP", _convert_datetime_iso)


class Database:
    """Wrapper de sqlite3 con connection-per-thread."""

    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._local = threading.local()

    def _get_connection(self) -> sqlite3.Connection:
        """Devuelve la connection del hilo actual, creándola si no existe."""
        conn = getattr(self._local, "conn", None)
        if conn is None:
            conn = sqlite3.connect(
                self.path,
                isolation_level=None, # Control manual de transacciones.
                detect_types=sqlite3.PARSE_DECLTYPES, # TIMESTAMP → datetime.
            )
            conn.row_factory = sqlite3.Row
            self._init_pragmas(conn)
            self._local.conn = conn
            logger.debug(f"[Database] Connection abierta en thread {threading.get_ident()}")
        return conn

    @staticmethod
    def _init_pragmas(conn: sqlite3.Connection) -> None:
        """PRAGMAs por conexión.

            - WAL: lecturas/escrituras no se bloquean.
            - synchronous=NORMAL: trade-off durabilidad vs velocidad razonable.
            - foreign_keys=ON: enforcement de FKs declaradas.
            - busy_timeout: tolerancia a locks de SQLite (tipico durante WAL checkpoints).
        """
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA busy_timeout=5000")

    # ── Ejecución ───────────────────────────────────────────────────────────

    def execute(self, sql: str, params: tuple[Any, ...] | dict[str, Any] = ()) -> sqlite3.Cursor:
        """Ejecuta un statement sin transacción explícita."""
        return self._get_connection().execute(sql, params)

    def executemany(
        self,
        sql: str,
        seq_of_params: list[tuple[Any, ...]] | list[dict[str, Any]],
    ) -> sqlite3.Cursor:
        """Ejecuta un statement múltiples veces."""
        return self._get_connection().executemany(sql, seq_of_params)

    # ── Transacciones ───────────────────────────────────────────────────────

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Cursor]:
        """Context manager para transacciones explícitas con BEGIN IMMEDIATE."""
        conn = self._get_connection()
        try:
            conn.execute("BEGIN IMMEDIATE")
            cur = conn.cursor()
            yield cur
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise

    # ── Operaciones de schema ───────────────────────────────────────────────

    def execute_script(self, sql: str) -> None:
        """Ejecuta un script SQL multi-statement."""
        self._get_connection().executescript(sql)

    def table_exists(self, name: str) -> bool:
        """True si la tabla existe en la DB."""
        row = self.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
            (name,),
        ).fetchone()
        return row is not None

    # ── Lifecycle ───────────────────────────────────────────────────────────

    def close_thread_connection(self) -> None:
        """Cierra la connection del hilo actual."""
        conn = getattr(self._local, "conn", None)
        if conn is not None:
            conn.close()
            self._local.conn = None
            logger.debug(f"[Database] Connection cerrada en thread {threading.get_ident()}")

    def __repr__(self) -> str:
        return f"<Database path={self.path}>"
