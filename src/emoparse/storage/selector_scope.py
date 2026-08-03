# ══════════════════════════════════════════════════════════════════════════════
#  emoparse.storage.selector_scope
#
#  Alcance por stage producido por selectores sobre payloads previos.
# ══════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

from emoparse.storage.db import Database


class SelectorScopeRepository:
    """Persiste el alcance vigente de cada stage a nivel discurso."""

    def __init__(self, db: Database) -> None:
        self._db = db

    def replace_stage(
        self,
        stage: str,
        all_codes: list[str],
        in_scope: set[str] | frozenset[str] | None,
        selector: str | None,
    ) -> None:
        """Reemplaza el alcance de una stage.

        `in_scope=None` significa que no hay selector de payload activo para
        esa stage; en ese caso se elimina cualquier alcance previo.
        """
        with self._db.transaction() as cur:
            cur.execute("DELETE FROM stage_selector_scope WHERE stage = ?", (stage,))
            if in_scope is None:
                return
            cur.executemany(
                "INSERT INTO stage_selector_scope "
                "(stage, codigo, en_alcance, selector) VALUES (?, ?, ?, ?)",
                [(stage, codigo, 1 if codigo in in_scope else 0, selector) for codigo in all_codes],
            )

    def clear_all(self) -> None:
        """Elimina el alcance dinámico persistido."""
        with self._db.transaction() as cur:
            cur.execute("DELETE FROM stage_selector_scope")
