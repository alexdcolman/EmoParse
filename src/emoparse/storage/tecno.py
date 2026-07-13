# ══════════════════════════════════════════════════════════════════════════════
#  emoparse.storage.tecno
#
#  Repositorio de la tabla `tecno_entidades`.
# ══════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

import json
from typing import Any

from emoparse.storage.db import Database


class TecnoRepository:
    """Repositorio de `tecno_entidades` (salida de la stage technoparse)."""

    def __init__(self, db: Database) -> None:
        self._db = db

    def replace_for_codigo(
        self, codigo: str, rows: list[dict[str, Any]]
    ) -> int:
        """Reemplaza las entidades de un discurso (idempotente).

        Cada row: {unit_idx, tipo, valor, valor_norm, inicio, fin, extra}.
        `extra` puede venir como dict: se serializa a JSON.
        """
        with self._db.transaction() as cur:
            cur.execute(
                "DELETE FROM tecno_entidades WHERE codigo = ?", (codigo,)
            )
            for r in rows:
                extra = r.get("extra")
                if isinstance(extra, dict):
                    extra = json.dumps(extra, ensure_ascii=False) if extra else None
                cur.execute(
                    """
                    INSERT OR IGNORE INTO tecno_entidades
                        (codigo, unit_idx, tipo, valor, valor_norm,
                         inicio, fin, extra)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        codigo, int(r["unit_idx"]), r["tipo"], r["valor"],
                        r["valor_norm"], int(r["inicio"]), int(r["fin"]),
                        extra,
                    ),
                )
        return len(rows)

    def list_for_unit(
        self, codigo: str, unit_idx: int
    ) -> list[dict[str, Any]]:
        """Entidades de una unidad, en orden de aparición."""
        rows = self._db.execute(
            "SELECT * FROM tecno_entidades "
            "WHERE codigo = ? AND unit_idx = ? ORDER BY inicio",
            (codigo, unit_idx),
        ).fetchall()
        return [_row_to_entidad(r) for r in rows]

    def list_for_codigo(self, codigo: str) -> list[dict[str, Any]]:
        """Entidades de un discurso completo."""
        rows = self._db.execute(
            "SELECT * FROM tecno_entidades "
            "WHERE codigo = ? ORDER BY unit_idx, inicio",
            (codigo,),
        ).fetchall()
        return [_row_to_entidad(r) for r in rows]

    def counts_by_tipo(self) -> dict[str, int]:
        """Conteo de entidades por tipo en todo el corpus."""
        rows = self._db.execute(
            "SELECT tipo, COUNT(*) AS n FROM tecno_entidades GROUP BY tipo"
        ).fetchall()
        return {str(r["tipo"]): int(r["n"]) for r in rows}

    def top_valores(
        self, tipo: str, limit: int = 50
    ) -> list[tuple[str, int]]:
        """Valores normalizados más frecuentes de un tipo (p. ej. hashtags)."""
        rows = self._db.execute(
            "SELECT valor_norm, COUNT(*) AS n FROM tecno_entidades "
            "WHERE tipo = ? GROUP BY valor_norm ORDER BY n DESC, valor_norm "
            "LIMIT ?",
            (tipo, limit),
        ).fetchall()
        return [(str(r["valor_norm"]), int(r["n"])) for r in rows]


    # ── Afecto de emojis ─────────────────────────────────────────────────────

    def list_emojis_sin_afecto(self) -> list[dict[str, Any]]:
        """Entidades emoji cuyo `extra` aún no registra afecto resuelto.

        Devuelve cada uso con el texto de su unidad (para desambiguar en
        contexto).
        """
        rows = self._db.execute(
            "SELECT t.*, f.frase FROM tecno_entidades t "
            "JOIN frases f ON f.codigo = t.codigo AND f.unit_idx = t.unit_idx "
            "WHERE t.tipo = 'emoji' "
            "AND (t.extra IS NULL OR t.extra NOT LIKE '%\"afecto\"%') "
            "ORDER BY t.codigo, t.unit_idx, t.inicio"
        ).fetchall()
        return [dict(r) | {"extra": _parse_extra(r["extra"])} for r in rows]

    def set_afecto(self, entidad_id: int, afecto: dict[str, Any]) -> None:
        """Registra el afecto resuelto de un emoji dentro de su `extra`."""
        row = self._db.execute(
            "SELECT extra FROM tecno_entidades WHERE id = ?", (entidad_id,)
        ).fetchone()
        if row is None:
            return
        extra = _parse_extra(row["extra"])
        extra["afecto"] = afecto
        with self._db.transaction() as cur:
            cur.execute(
                "UPDATE tecno_entidades SET extra = ? WHERE id = ?",
                (json.dumps(extra, ensure_ascii=False), entidad_id),
            )

    # ── Muestras de hashtags ─────────────────────────────────────────────────

    def sample_usos_hashtag(
        self, valor_norm: str, limit: int = 8
    ) -> list[str]:
        """Muestra de textos de unidades que usan un hashtag (uno por unidad)."""
        rows = self._db.execute(
            "SELECT DISTINCT f.frase FROM tecno_entidades t "
            "JOIN frases f ON f.codigo = t.codigo AND f.unit_idx = t.unit_idx "
            "WHERE t.tipo = 'hashtag' AND t.valor_norm = ? "
            "ORDER BY t.codigo LIMIT ?",
            (valor_norm, limit),
        ).fetchall()
        return [str(r["frase"]) for r in rows]


def _row_to_entidad(row: Any) -> dict[str, Any]:
    """Convierte una fila SQLite a dict con `extra` parseado."""
    d = dict(row)
    raw = d.get("extra")
    if isinstance(raw, str) and raw:
        try:
            d["extra"] = json.loads(raw)
        except json.JSONDecodeError:
            pass
    return d


def _parse_extra(raw: Any) -> dict[str, Any]:
    """Parsea la columna `extra` a dict (dict vacío si es nula/ilegible)."""
    if isinstance(raw, str) and raw:
        try:
            parsed = json.loads(raw)
            return parsed if isinstance(parsed, dict) else {}
        except json.JSONDecodeError:
            return {}
    return {}
