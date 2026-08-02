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

    def replace_for_codigo(self, codigo: str, rows: list[dict[str, Any]]) -> int:
        """Reemplaza las entidades de un discurso (idempotente).

        Cada row: {unit_idx, tipo, valor, valor_norm, inicio, fin, extra}.
        `extra` puede venir como dict: se serializa a JSON.
        """
        with self._db.transaction() as cur:
            cur.execute("DELETE FROM tecno_entidades WHERE codigo = ?", (codigo,))
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
                        codigo,
                        int(r["unit_idx"]),
                        r["tipo"],
                        r["valor"],
                        r["valor_norm"],
                        int(r["inicio"]),
                        int(r["fin"]),
                        extra,
                    ),
                )
        return len(rows)

    def list_for_unit(self, codigo: str, unit_idx: int) -> list[dict[str, Any]]:
        """Entidades de una unidad, en orden de aparición."""
        rows = self._db.execute(
            "SELECT * FROM tecno_entidades WHERE codigo = ? AND unit_idx = ? ORDER BY inicio",
            (codigo, unit_idx),
        ).fetchall()
        return [_row_to_entidad(r) for r in rows]

    def list_for_codigo(self, codigo: str) -> list[dict[str, Any]]:
        """Entidades de un discurso completo."""
        rows = self._db.execute(
            "SELECT * FROM tecno_entidades WHERE codigo = ? ORDER BY unit_idx, inicio",
            (codigo,),
        ).fetchall()
        return [_row_to_entidad(r) for r in rows]

    def counts_by_tipo(self) -> dict[str, int]:
        """Conteo de entidades por tipo en todo el corpus."""
        rows = self._db.execute(
            "SELECT tipo, COUNT(*) AS n FROM tecno_entidades GROUP BY tipo"
        ).fetchall()
        return {str(r["tipo"]): int(r["n"]) for r in rows}

    def top_valores(self, tipo: str, limit: int = 50) -> list[tuple[str, int]]:
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

    def set_extra_key(self, entidad_id: int, key: str, value: Any) -> None:
        """Registra un valor bajo una clave del `extra` de una entidad."""
        self.set_extra_keys(entidad_id, {key: value})

    def set_extra_keys(self, entidad_id: int, valores: dict[str, Any]) -> None:
        """Registra varias claves del `extra` en una sola lectura-escritura.

        Las stages que anotan más de un bloque por entidad (afecto y su
        repetición, por ejemplo) evitan así un round-trip por clave.
        """
        row = self._db.execute(
            "SELECT extra FROM tecno_entidades WHERE id = ?", (entidad_id,)
        ).fetchone()
        if row is None:
            return
        extra = _parse_extra(row["extra"])
        extra.update(valores)
        with self._db.transaction() as cur:
            cur.execute(
                "UPDATE tecno_entidades SET extra = ? WHERE id = ?",
                (json.dumps(extra, ensure_ascii=False), entidad_id),
            )

    def set_afecto(self, entidad_id: int, afecto: dict[str, Any]) -> None:
        """Registra el afecto resuelto de un emoji dentro de su `extra`."""
        self.set_extra_key(entidad_id, "afecto", afecto)

    # ── Análisis por uso (hashtags y tecno_usage) ────────────────────────────

    def list_usos_hashtag_sin_funcion(self, valor_norm: str) -> list[dict[str, Any]]:
        """Usos de un hashtag cuyo `extra` aún no registra función resuelta.

        Devuelve cada uso con el texto de su unidad, en orden estable.
        """
        rows = self._db.execute(
            "SELECT t.*, f.frase FROM tecno_entidades t "
            "JOIN frases f ON f.codigo = t.codigo AND f.unit_idx = t.unit_idx "
            "WHERE t.tipo = 'hashtag' AND t.valor_norm = ? "
            "AND (t.extra IS NULL OR t.extra NOT LIKE '%\"funcion\"%') "
            "ORDER BY t.codigo, t.unit_idx, t.inicio",
            (valor_norm,),
        ).fetchall()
        return [dict(r) | {"extra": _parse_extra(r["extra"])} for r in rows]

    def analisis_usos_hashtag(self, valor_norm: str) -> list[dict[str, Any]]:
        """Payloads de función por uso ya registrados para un hashtag."""
        rows = self._db.execute(
            "SELECT extra FROM tecno_entidades "
            "WHERE tipo = 'hashtag' AND valor_norm = ? "
            "AND extra LIKE '%\"funcion\"%'",
            (valor_norm,),
        ).fetchall()
        out: list[dict[str, Any]] = []
        for r in rows:
            payload = _parse_extra(r["extra"]).get("funcion")
            if isinstance(payload, dict):
                out.append(payload)
        return out

    def list_unidades_con_tecno_sin_uso(self) -> list[dict[str, Any]]:
        """Unidades con menciones, tecnografismos o URLs sin uso resuelto.

        Devuelve una entrada por unidad, con el texto de la frase y la lista
        de entidades pendientes (para el análisis en contexto de la stage
        `tecno_usage`). Las URLs se caracterizan de forma barata por su
        función pragmática (fuente/prueba, autopromoción, convocatoria a la
        acción, enlace temático), apoyándose en el dominio ya normalizado.
        """
        rows = self._db.execute(
            "SELECT t.*, f.frase FROM tecno_entidades t "
            "JOIN frases f ON f.codigo = t.codigo AND f.unit_idx = t.unit_idx "
            "WHERE t.tipo IN ('mencion', 'tecnografismo', 'url') "
            "AND (t.extra IS NULL OR t.extra NOT LIKE '%\"uso\"%') "
            "ORDER BY t.codigo, t.unit_idx, t.inicio"
        ).fetchall()
        unidades: dict[tuple[str, int], dict[str, Any]] = {}
        for r in rows:
            key = (str(r["codigo"]), int(r["unit_idx"]))
            u = unidades.setdefault(
                key,
                {
                    "codigo": key[0],
                    "unit_idx": key[1],
                    "frase": str(r["frase"]),
                    "entidades": [],
                },
            )
            u["entidades"].append(dict(r) | {"extra": _parse_extra(r["extra"])})
        return list(unidades.values())

    # ── Muestras de hashtags ─────────────────────────────────────────────────

    def sample_usos_hashtag(self, valor_norm: str, limit: int = 8) -> list[str]:
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
