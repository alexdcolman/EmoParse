# ══════════════════════════════════════════════════════════════════════════════
#  emoparse.storage.emociones
#
#  Repositorio de la tabla `emociones`.
# ══════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

import json
from collections.abc import Iterable
from datetime import datetime, timezone
from typing import Any

from emoparse.storage.db import Database


class EmocionesRepository:
    """Repositorio de emociones individuales."""

    def __init__(self, db: Database) -> None:
        self._db = db

    # ── Insert (explode) ─────────────────────────────────────────────────────

    def upsert_emocion(
        self,
        codigo: str,
        frase_idx: int,
        emocion_idx: int,
        experienciador: str,
        experienciador_marca: str,
        tipo_emocion: str,
        fuente_marca: str,
        fuente_inferencia: str,
        modo_existencia: str,
        tipo_configuracion: str | None = None,
    ) -> None:
        """Insert/update de una emoción individual."""
        with self._db.transaction() as cur:
            cur.execute(
                """
                INSERT INTO emociones (
                    codigo, frase_idx, emocion_idx,
                    experienciador, experienciador_marca, tipo_emocion, fuente_marca,
                    fuente_inferencia, modo_existencia,
                    tipo_configuracion
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(codigo, frase_idx, emocion_idx) DO UPDATE SET
                    experienciador          = excluded.experienciador,
                    experienciador_marca    = excluded.experienciador_marca,
                    tipo_emocion            = excluded.tipo_emocion,
                    fuente_marca            = excluded.fuente_marca,
                    fuente_inferencia       = excluded.fuente_inferencia,
                    modo_existencia         = excluded.modo_existencia,
                    tipo_configuracion      = excluded.tipo_configuracion,
                    updated_at              = ?
                """,
                (
                    codigo, frase_idx, emocion_idx,
                    experienciador, experienciador_marca, 
                    tipo_emocion, fuente_marca,
                    fuente_inferencia, modo_existencia,
                    tipo_configuracion,
                    datetime.now(timezone.utc),
                ),
            )

    def upsert_emociones(
        self,
        rows: Iterable[dict[str, Any]],
    ) -> None:
        """Bulk insert/update de emociones."""
        now = datetime.now(timezone.utc)
        params = [
            (
                r["codigo"], r["frase_idx"], r["emocion_idx"],
                r["experienciador"], r["experienciador_marca"],
                r["tipo_emocion"], r["fuente_marca"],
                r["fuente_inferencia"], r["modo_existencia"],
                r.get("tipo_configuracion"),
                now,
            )
            for r in rows
        ]
        with self._db.transaction() as cur:
            cur.executemany(
                """
                INSERT INTO emociones (
                    codigo, frase_idx, emocion_idx,
                    experienciador, experienciador_marca, tipo_emocion, fuente_marca,
                    fuente_inferencia, modo_existencia,
                    tipo_configuracion
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(codigo, frase_idx, emocion_idx) DO UPDATE SET
                    experienciador          = excluded.experienciador,
                    experienciador_marca    = excluded.experienciador_marca,
                    tipo_emocion            = excluded.tipo_emocion,
                    fuente_marca            = excluded.fuente_marca,
                    fuente_inferencia       = excluded.fuente_inferencia,
                    modo_existencia         = excluded.modo_existencia,
                    tipo_configuracion      = excluded.tipo_configuracion,
                    updated_at              = ?
                """,
                params,
            )

    # ── Caracterización ──────────────────────────────────────────────────────

    def set_caracterizacion(
        self,
        codigo: str,
        frase_idx: int,
        emocion_idx: int,
        payload: dict[str, Any],
        version: str | None = None,
    ) -> None:
        """Marca una emoción como caracterizada exitosamente."""
        payload_str = json.dumps(payload, ensure_ascii=False, default=str)
        with self._db.transaction() as cur:
            cur.execute(
                """
                UPDATE emociones SET
                    caracterizacion_payload = ?,
                    caracterizacion_version = ?,
                    caracterizacion_error   = NULL,
                    updated_at              = ?
                WHERE codigo = ? AND frase_idx = ? AND emocion_idx = ?
                """,
                (
                    payload_str, version,
                    datetime.now(timezone.utc),
                    codigo, frase_idx, emocion_idx,
                ),
            )

    def set_caracterizacion_error(
        self,
        codigo: str,
        frase_idx: int,
        emocion_idx: int,
        error_message: str,
    ) -> None:
        """Marca una emoción como fallida en caracterización."""
        with self._db.transaction() as cur:
            cur.execute(
                """
                UPDATE emociones SET
                    caracterizacion_payload = NULL,
                    caracterizacion_version = NULL,
                    caracterizacion_error   = ?,
                    updated_at              = ?
                WHERE codigo = ? AND frase_idx = ? AND emocion_idx = ?
                """,
                (
                    error_message,
                    datetime.now(timezone.utc),
                    codigo, frase_idx, emocion_idx,
                ),
            )

    # ── Actantes ─────────────────────────────────────────────────────────────

    def set_actantes(
        self,
        codigo: str,
        frase_idx: int,
        emocion_idx: int,
        payload: dict[str, Any],
        version: str | None = None,
    ) -> None:
        """Marca una emoción como analizada actancialmente."""
        payload_str = json.dumps(payload, ensure_ascii=False, default=str)
        with self._db.transaction() as cur:
            cur.execute(
                """
                UPDATE emociones SET
                    actantes_payload = ?,
                    actantes_version = ?,
                    actantes_error   = NULL,
                    updated_at       = ?
                WHERE codigo = ? AND frase_idx = ? AND emocion_idx = ?
                """,
                (
                    payload_str, version,
                    datetime.now(timezone.utc),
                    codigo, frase_idx, emocion_idx,
                ),
            )

    def set_actantes_error(
        self,
        codigo: str,
        frase_idx: int,
        emocion_idx: int,
        error_message: str,
    ) -> None:
        """Marca una emoción como fallida en análisis actancial."""
        with self._db.transaction() as cur:
            cur.execute(
                """
                UPDATE emociones SET
                    actantes_payload = NULL,
                    actantes_version = NULL,
                    actantes_error   = ?,
                    updated_at       = ?
                WHERE codigo = ? AND frase_idx = ? AND emocion_idx = ?
                """,
                (
                    error_message,
                    datetime.now(timezone.utc),
                    codigo, frase_idx, emocion_idx,
                ),
            )

    def list_pending_actantes(
        self,
        codigo: str | None = None,
    ) -> list[tuple[str, int, int]]:
        """Emociones pendientes de análisis actancial (sin error)."""
        base_sql = (
            "SELECT codigo, frase_idx, emocion_idx FROM emociones "
            "WHERE actantes_payload IS NULL "
            "AND actantes_error IS NULL"
        )
        if codigo is None:
            rows = self._db.execute(base_sql).fetchall()
        else:
            rows = self._db.execute(
                base_sql + " AND codigo = ?", (codigo,)
            ).fetchall()
        return [
            (row["codigo"], row["frase_idx"], row["emocion_idx"])
            for row in rows
        ]

    def clear_actantes_errors(self, codigo: str | None = None) -> int:
        """Limpia errors de actantes para reintento."""
        sql = (
            "UPDATE emociones SET actantes_error = NULL "
            "WHERE actantes_error IS NOT NULL"
        )
        params: tuple = ()
        if codigo is not None:
            sql += " AND codigo = ?"
            params = (codigo,)
        with self._db.transaction() as cur:
            cur.execute(sql, params)
            return cur.rowcount

    # ── Lookup ───────────────────────────────────────────────────────────────

    def list_emociones_of_discurso(
        self,
        codigo: str,
    ) -> list[dict[str, Any]]:
        """Todas las emociones de un discurso, ordenadas por (frase, emocion)."""
        rows = self._db.execute(
            """
            SELECT * FROM emociones
            WHERE codigo = ?
            ORDER BY frase_idx, emocion_idx
            """,
            (codigo,),
        ).fetchall()
        return [dict(row) for row in rows]

    def list_pending_caracterizacion(
        self,
        codigo: str | None = None,
    ) -> list[tuple[str, int, int]]:
        """Emociones pendientes de caracterización (sin error)."""
        base_sql = (
            "SELECT codigo, frase_idx, emocion_idx FROM emociones "
            "WHERE caracterizacion_payload IS NULL "
            "AND caracterizacion_error IS NULL"
        )
        if codigo is None:
            rows = self._db.execute(base_sql).fetchall()
        else:
            rows = self._db.execute(
                base_sql + " AND codigo = ?", (codigo,)
            ).fetchall()
        return [
            (row["codigo"], row["frase_idx"], row["emocion_idx"])
            for row in rows
        ]

    # ── Normalización ────────────────────────────────────────────────────────

    def get_emocion(
        self,
        codigo: str,
        frase_idx: int,
        emocion_idx: int,
    ) -> dict[str, Any] | None:
        """Devuelve una emoción individual como dict, o None si no existe."""
        row = self._db.execute(
            "SELECT * FROM emociones "
            "WHERE codigo = ? AND frase_idx = ? AND emocion_idx = ?",
            (codigo, frase_idx, emocion_idx),
        ).fetchone()
        return dict(row) if row is not None else None

    def set_normalized_emotion(
        self,
        codigo: str,
        frase_idx: int,
        emocion_idx: int,
        tipo_emocion_canonico: str | None,
        version: str | None = None,
    ) -> None:
        """Escribe el canónico de emoción (NULL si no matchea ontología)."""
        with self._db.transaction() as cur:
            cur.execute(
                """
                UPDATE emociones SET
                    tipo_emocion_canonico      = ?,
                    normalize_emotions_version = ?,
                    updated_at                 = ?
                WHERE codigo = ? AND frase_idx = ? AND emocion_idx = ?
                """,
                (
                    tipo_emocion_canonico, version,
                    datetime.now(timezone.utc),
                    codigo, frase_idx, emocion_idx,
                ),
            )

    def list_pending_normalization(
        self,
        codigo: str | None = None,
    ) -> list[tuple[str, int, int]]:
        """Emociones con tipo_emocion no nulo y tipo_emocion_canonico nulo."""
        base_sql = (
            "SELECT codigo, frase_idx, emocion_idx FROM emociones "
            "WHERE tipo_emocion IS NOT NULL "
            "AND tipo_emocion_canonico IS NULL"
        )
        if codigo is None:
            rows = self._db.execute(base_sql).fetchall()
        else:
            rows = self._db.execute(
                base_sql + " AND codigo = ?", (codigo,)
            ).fetchall()
        return [
            (row["codigo"], row["frase_idx"], row["emocion_idx"])
            for row in rows
        ]

    def clear_errors(self, codigo: str | None = None) -> int:
        """Limpia errors de caracterización para reintento."""
        sql = (
            "UPDATE emociones SET caracterizacion_error = NULL "
            "WHERE caracterizacion_error IS NOT NULL"
        )
        params: tuple = ()
        if codigo is not None:
            sql += " AND codigo = ?"
            params = (codigo,)
        with self._db.transaction() as cur:
            cur.execute(sql, params)
            return cur.rowcount

    # ── Normalización de experienciador ──────────────────────────────────────

    def list_distinct_experiencers(
        self,
        codigo: str,
    ) -> list[tuple[str, int]]:
        """Experienciadores crudos distintos de un discurso, con su frecuencia.

        Ordenados por frecuencia descendente. Excluye vacíos.
        """
        rows = self._db.execute(
            """
            SELECT experienciador AS exp, COUNT(*) AS n
            FROM emociones
            WHERE codigo = ? AND TRIM(experienciador) <> ''
            GROUP BY experienciador
            ORDER BY n DESC, exp ASC
            """,
            (codigo,),
        ).fetchall()
        return [(row["exp"], int(row["n"])) for row in rows]

    def set_experienciador_canonico(
        self,
        codigo: str,
        raw_experienciador: str,
        canonical: str,
        version: str | None = None,
    ) -> int:
        """Escribe el canónico en todas las filas de un discurso que tienen
        ese experienciador crudo. Devuelve el nº de filas afectadas."""
        with self._db.transaction() as cur:
            cur.execute(
                """
                UPDATE emociones SET
                    experienciador_canonico = ?,
                    updated_at              = ?
                WHERE codigo = ? AND experienciador = ?
                """,
                (
                    canonical,
                    datetime.now(timezone.utc),
                    codigo, raw_experienciador,
                ),
            )
            return cur.rowcount

    # ── Atribución por emoción (revisión) ────────────────────────────────────

    def set_experienciador_canonico_at(
        self,
        codigo: str,
        frase_idx: int,
        emocion_idx: int,
        canonical: str | None,
        version: str | None = None,
    ) -> bool:
        """Fija (o limpia) el experienciador canónico de UNA emoción puntual.

        Devuelve True si el valor cambió respecto del que había. Como
        characterizer/actants/judge prefieren `experienciador_canonico` cuando
        existe (helper `_effective_experiencer`), un cambio debe invalidarlos
        vía `invalidate_downstream`. `version` se acepta por simetría de API;
        no se persiste (igual que `set_experienciador_canonico`)."""
        return self._set_canonico_at(
            "experienciador_canonico",
            codigo, frase_idx, emocion_idx, canonical,
        )

    def set_fuente_canonico_at(
        self,
        codigo: str,
        frase_idx: int,
        emocion_idx: int,
        canonical: str | None,
        version: str | None = None,
    ) -> bool:
        """Fija (o limpia) la fuente canónica de UNA emoción puntual.

        Devuelve True si el valor cambió. A diferencia del experienciador, la
        fuente canónica es una etiqueta de referente (no la consume ningún
        stage LLM), por lo que no requiere invalidación downstream."""
        return self._set_canonico_at(
            "fuente_canonico",
            codigo, frase_idx, emocion_idx, canonical,
        )

    def _set_canonico_at(
        self,
        column: str,
        codigo: str,
        frase_idx: int,
        emocion_idx: int,
        canonical: str | None,
    ) -> bool:
        """Setea una columna canónica por emoción; True si cambió."""
        row = self._db.execute(
            f"SELECT {column} AS val FROM emociones "
            "WHERE codigo = ? AND frase_idx = ? AND emocion_idx = ?",
            (codigo, frase_idx, emocion_idx),
        ).fetchone()
        if row is None:
            return False
        new = canonical if (canonical or "").strip() else None
        if (row["val"] or None) == new:
            return False
        with self._db.transaction() as cur:
            cur.execute(
                f"UPDATE emociones SET {column} = ?, updated_at = ? "
                "WHERE codigo = ? AND frase_idx = ? AND emocion_idx = ?",
                (new, datetime.now(timezone.utc), codigo, frase_idx, emocion_idx),
            )
        return True

    def invalidate_downstream(
        self,
        codigo: str,
        frase_idx: int,
        emocion_idx: int,
    ) -> None:
        """Anula characterizer y actants de UNA emoción para forzar su
        recálculo (vuelven a `list_pending_*`). Se usa tras cambiar el
        experienciador canónico por emoción. El juicio se invalida por separado
        (`JudgmentsRepository.invalidate`)."""
        with self._db.transaction() as cur:
            cur.execute(
                """
                UPDATE emociones SET
                    caracterizacion_payload = NULL,
                    caracterizacion_version = NULL,
                    caracterizacion_error   = NULL,
                    actantes_payload        = NULL,
                    actantes_version        = NULL,
                    actantes_error          = NULL,
                    updated_at              = ?
                WHERE codigo = ? AND frase_idx = ? AND emocion_idx = ?
                """,
                (datetime.now(timezone.utc), codigo, frase_idx, emocion_idx),
            )
    # ── Resolución de canónicos por marca (refleja tab Referentes) ────────────

    _MARCA_FIELDS = {"experienciador_marca", "fuente_marca"}

    def resolve_canonico_map(
        self,
        codigo: str,
        funcion: str,
        marca_field: str,
    ) -> dict[tuple[int, int], list[str]]:
        """(frase_idx, emocion_idx) → [canonical_id] resueltos desde las marcas y
        los vínculos mención↔referente de una `funcion`
        ('experienciador'/'fuente').

        Es la MISMA resolución que usa el dashboard (Referentes/Simulacros): por
        eso refleja las ediciones hechas en la tab Referentes. Devuelve {} si no
        hay base de menciones todavía."""
        if marca_field not in self._MARCA_FIELDS:
            raise ValueError(f"marca_field inválido: {marca_field}")
        tables = {
            r["name"]
            for r in self._db.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        if not {"menciones", "mencion_funcion", "mencion_canonico"} <= tables:
            return {}
        rank = {"accepted": 0, "proposed": 1}
        origin_rank = {"deixis_llm": 0, "human": 1, "auto": 2, "coref": 3, "llm": 4}
        per: dict[int, dict[str, dict[str, tuple[int, int]]]] = {}
        for r in self._db.execute(
            "SELECT m.unit_idx AS u, m.marca AS marca, mc.canonical_id AS cid, "
            "mc.status AS status, mc.origin AS origin "
            "FROM menciones m "
            "JOIN mencion_funcion mf ON mf.mencion_id = m.id AND mf.funcion = ? "
            "JOIN mencion_canonico mc ON mc.mencion_id = m.id "
            "WHERE mc.status != 'rejected' AND m.codigo = ?",
            (funcion, codigo),
        ).fetchall():
            cid = r["cid"]
            mm = (r["marca"] or "").strip().lower()
            if not cid or not mm:
                continue
            score = (rank.get(r["status"], 9), origin_rank.get(r["origin"], 9))
            d = per.setdefault(int(r["u"]), {}).setdefault(mm, {})
            if cid not in d or score < d[cid]:
                d[cid] = score
        if not per:
            return {}
        out: dict[tuple[int, int], list[str]] = {}
        for r in self._db.execute(
            f"SELECT frase_idx, emocion_idx, {marca_field} AS marca "
            "FROM emociones WHERE codigo = ?",
            (codigo,),
        ).fetchall():
            marca_map = per.get(int(r["frase_idx"]))
            if not marca_map:
                continue
            cids = _match_canonicos_emo(
                marca_map, str(r["marca"] or "").strip().lower()
            )
            if cids:
                out[(int(r["frase_idx"]), int(r["emocion_idx"]))] = cids
        return out


def _match_canonicos_emo(
    marca_map: dict[str, dict[str, tuple[int, int]]] | None, fm: str
) -> list[str]:
    """Resuelve la marca `fm` (normalizada) contra las menciones de la frase.

    Match exacto; si no, por contención en ambos sentidos. Dedup por
    canonical_id, ordenado por preferencia (aceptado/deixis primero)."""
    if not marca_map or not fm:
        return []
    if fm in marca_map:
        matched = {fm: marca_map[fm]}
    else:
        matched = {mm: c for mm, c in marca_map.items() if mm in fm or fm in mm}
    scored: dict[str, tuple[int, int]] = {}
    for cids in matched.values():
        for cid, sc in cids.items():
            if cid not in scored or sc < scored[cid]:
                scored[cid] = sc
    return [cid for cid, _ in sorted(scored.items(), key=lambda kv: (kv[1], kv[0]))]
