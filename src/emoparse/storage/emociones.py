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
from emoparse.storage.referencia import (
    marca_canonicos_index,
    resolver_canonico,
    resolver_canonicos,
)


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
        """Bulk insert/update de emociones.

        Los canónicos por emoción (`experienciador_canonico`,
        `fuente_canonico`) que trae el explode son de procedencia automática:
        fijan el referente de las filas desdobladas cuya marca compartida no
        los distinguiría. Se escriben con `*_origin = 'auto'` y solo cuando la
        fila no tiene ya una atribución `'human'` (commit de revisión), que
        nunca se pisa. Un re-run del explode reafirma el 'auto' y respeta el
        'human'.
        """
        now = datetime.now(timezone.utc)
        params = []
        for r in rows:
            exp_canon = r.get("experienciador_canonico")
            fte_canon = r.get("fuente_canonico")
            params.append((
                r["codigo"], r["frase_idx"], r["emocion_idx"],
                r["experienciador"], r["experienciador_marca"],
                r["tipo_emocion"], r["fuente_marca"],
                r["fuente_inferencia"], r["modo_existencia"],
                r.get("tipo_configuracion"),
                exp_canon, exp_canon,   # valor + guard del CASE de origin
                fte_canon, fte_canon,
                now,
            ))
        with self._db.transaction() as cur:
            cur.executemany(
                """
                INSERT INTO emociones (
                    codigo, frase_idx, emocion_idx,
                    experienciador, experienciador_marca, tipo_emocion, fuente_marca,
                    fuente_inferencia, modo_existencia,
                    tipo_configuracion,
                    experienciador_canonico, experienciador_canonico_origin,
                    fuente_canonico, fuente_canonico_origin
                )
                VALUES (
                    ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                    ?, CASE WHEN ? IS NOT NULL THEN 'auto' END,
                    ?, CASE WHEN ? IS NOT NULL THEN 'auto' END
                )
                ON CONFLICT(codigo, frase_idx, emocion_idx) DO UPDATE SET
                    experienciador          = excluded.experienciador,
                    experienciador_marca    = excluded.experienciador_marca,
                    tipo_emocion            = excluded.tipo_emocion,
                    fuente_marca            = excluded.fuente_marca,
                    fuente_inferencia       = excluded.fuente_inferencia,
                    modo_existencia         = excluded.modo_existencia,
                    tipo_configuracion      = excluded.tipo_configuracion,
                    -- El desdoblamiento automático no pisa una atribución
                    -- humana; sí refresca (o limpia) la automática.
                    experienciador_canonico = CASE
                        WHEN experienciador_canonico_origin = 'human'
                        THEN experienciador_canonico
                        ELSE excluded.experienciador_canonico END,
                    experienciador_canonico_origin = CASE
                        WHEN experienciador_canonico_origin = 'human'
                        THEN 'human'
                        ELSE excluded.experienciador_canonico_origin END,
                    fuente_canonico = CASE
                        WHEN fuente_canonico_origin = 'human'
                        THEN fuente_canonico
                        ELSE excluded.fuente_canonico END,
                    fuente_canonico_origin = CASE
                        WHEN fuente_canonico_origin = 'human'
                        THEN 'human'
                        ELSE excluded.fuente_canonico_origin END,
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

    def set_modo_existencia_at(
        self,
        codigo: str,
        frase_idx: int,
        emocion_idx: int,
        modo: str,
    ) -> bool:
        """Fija el modo de existencia de UNA emoción. Devuelve True si cambió.

        El modo no lo consume ningún stage LLM (es una categoría del simulacro),
        así que no dispara recálculo downstream."""
        modo = str(modo or "").strip()
        if not modo:
            return False
        with self._db.transaction() as cur:
            cur.execute(
                "UPDATE emociones SET modo_existencia = ?, updated_at = ? "
                "WHERE codigo = ? AND frase_idx = ? AND emocion_idx = ? "
                "  AND modo_existencia != ?",
                (modo, datetime.now(timezone.utc),
                 codigo, frase_idx, emocion_idx, modo),
            )
            return cur.rowcount > 0

    def _set_canonico_at(
        self,
        column: str,
        codigo: str,
        frase_idx: int,
        emocion_idx: int,
        canonical: str | None,
    ) -> bool:
        """Setea una columna canónica por emoción; True si cambió.

        Marca la procedencia como 'human': es la revisión del analista, que
        el desdoblamiento automático nunca debe pisar. Limpiar el valor
        (canonical vacío) también limpia la procedencia, devolviendo la
        emoción a la resolución por marca.
        """
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
        origin = "human" if new is not None else None
        with self._db.transaction() as cur:
            cur.execute(
                f"UPDATE emociones SET {column} = ?, {column}_origin = ?, "
                "updated_at = ? "
                "WHERE codigo = ? AND frase_idx = ? AND emocion_idx = ?",
                (new, origin, datetime.now(timezone.utc),
                 codigo, frase_idx, emocion_idx),
            )
        return True

    # ── Desdoblamiento por experienciador / fuente (revisión) ────────────────

    #: Columnas downstream que las emociones nuevas dejan en NULL (re-pending).
    _DOWNSTREAM_COLS = (
        "caracterizacion_payload", "caracterizacion_version",
        "caracterizacion_error",
        "actantes_payload", "actantes_version", "actantes_error",
    )

    def split_por_experienciadores(
        self,
        codigo: str,
        frase_idx: int,
        emocion_idx: int,
        canonicals: list[str],
        modos: list[str] | None = None,
    ) -> dict[str, Any]:
        """Desdobla una emoción en una por experienciador canónico.

        El primer canónico queda en la emoción original; por cada canónico
        adicional se crea una emoción nueva (copia con el siguiente
        `emocion_idx` de la frase) con su propio `experienciador_canonico` y,
        si se pasa `modos`, su propio modo de existencia. Idempotente: no
        duplica una emoción que ya exista en la frase con el mismo tipo y el
        mismo canónico. Devuelve {'changed': bool, 'nuevos': [emocion_idx]};
        `changed` indica si la emoción original cambió (el caller debe
        invalidar su downstream)."""
        return self._split_at(
            codigo, frase_idx, emocion_idx, canonicals, modos,
        )

    def _split_at(
        self,
        codigo: str,
        frase_idx: int,
        emocion_idx: int,
        canonicals: list[str],
        modos: list[str] | None,
    ) -> dict[str, Any]:
        """Implementación del desdoblamiento por experienciador canónico.

        Solo el experienciador desdobla: la fuente de una emoción puede
        combinar entidades y se atribuye entera con `set_fuente_canonico_at`."""
        column = "experienciador_canonico"
        cids = [str(c).strip() for c in canonicals if str(c).strip()]
        src = self.get_emocion(codigo, frase_idx, emocion_idx)
        if not cids or src is None:
            return {"changed": False, "nuevos": []}
        modos = [str(m).strip() for m in (modos or [])]

        changed = self._set_canonico_at(
            column, codigo, frase_idx, emocion_idx, cids[0]
        )
        if modos and modos[0] and modos[0] != (src.get("modo_existencia") or ""):
            with self._db.transaction() as cur:
                cur.execute(
                    "UPDATE emociones SET modo_existencia = ?, updated_at = ? "
                    "WHERE codigo = ? AND frase_idx = ? AND emocion_idx = ?",
                    (modos[0], datetime.now(timezone.utc),
                     codigo, frase_idx, emocion_idx),
                )
            changed = True

        rows = self._db.execute(
            f"SELECT emocion_idx, tipo_emocion, {column} AS canon "
            "FROM emociones WHERE codigo = ? AND frase_idx = ?",
            (codigo, frase_idx),
        ).fetchall()
        existentes = {
            (str(r["tipo_emocion"] or ""), str(r["canon"] or ""))
            for r in rows
        }
        next_idx = max(int(r["emocion_idx"]) for r in rows) + 1

        nuevos: list[int] = []
        for i, cid in enumerate(cids[1:], start=1):
            if (str(src.get("tipo_emocion") or ""), cid) in existentes:
                continue
            rec = dict(src)
            rec.pop("id", None)
            rec["emocion_idx"] = next_idx
            rec[column] = cid
            # Es una edición del analista: fija la procedencia para que el
            # desdoblamiento automático del explode no la pise en un re-run.
            rec[f"{column}_origin"] = "human"
            if i < len(modos) and modos[i]:
                rec["modo_existencia"] = modos[i]
            for c in self._DOWNSTREAM_COLS:
                if c in rec:
                    rec[c] = None
            rec["updated_at"] = datetime.now(timezone.utc)
            cols = list(rec.keys())
            placeholders = ", ".join("?" * len(cols))
            with self._db.transaction() as cur:
                cur.execute(
                    f"INSERT INTO emociones ({', '.join(cols)}) "
                    f"VALUES ({placeholders})",
                    tuple(rec[c] for c in cols),
                )
            existentes.add((str(src.get("tipo_emocion") or ""), cid))
            nuevos.append(next_idx)
            next_idx += 1
        return {"changed": changed, "nuevos": nuevos}

    def delete_emocion(
        self, codigo: str, frase_idx: int, emocion_idx: int
    ) -> bool:
        """Elimina una emoción y lo que cuelga de ella. True si existía.

        Arrastra el juicio y los hallazgos de validación de esa emoción. No
        renumera el resto: `emocion_idx` identifica al simulacro dentro de la
        frase y renumerar orfanaría las referencias del overlay de revisión.
        """
        with self._db.transaction() as cur:
            for tabla in ("judgments", "validation_issues"):
                if self._db.table_exists(tabla):
                    cur.execute(
                        f"DELETE FROM {tabla} WHERE codigo = ? "
                        "AND frase_idx = ? AND emocion_idx = ?",
                        (codigo, frase_idx, emocion_idx),
                    )
            cur.execute(
                "DELETE FROM emociones "
                "WHERE codigo = ? AND frase_idx = ? AND emocion_idx = ?",
                (codigo, frase_idx, emocion_idx),
            )
            return cur.rowcount > 0

    def colapsar_duplicados(self, codigo: str, frase_idx: int) -> list[int]:
        """Funde los simulacros indistinguibles de una frase. Devuelve los idx caídos.

        Dos emociones de la misma frase con el mismo experienciador, la misma
        emoción y el mismo modo de existencia son un solo simulacro: no hay
        nada que las distinga. Sobrevive la de menor `emocion_idx`, que se
        queda con la unión de las fuentes; las demás se eliminan.

        Se invoca después de las operaciones que pueden producir la colisión
        (desdoblar por deixis, limpiar una atribución rechazada), no como
        barrido sobre lo que infirió el modelo.
        """
        rows = self._db.execute(
            "SELECT * FROM emociones WHERE codigo = ? AND frase_idx = ? "
            "ORDER BY emocion_idx",
            (codigo, frase_idx),
        ).fetchall()
        if len(rows) < 2:
            return []
        index_exp = marca_canonicos_index(self._db, "experienciador", codigo)
        index_fte = marca_canonicos_index(self._db, "fuente", codigo)
        marcas_exp = index_exp.get((codigo, frase_idx))
        marcas_fte = index_fte.get((codigo, frase_idx))

        grupos: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
        for row in rows:
            e = dict(row)
            clave = (
                resolver_canonico(
                    marcas_exp, e.get("experienciador_marca"),
                    override=e.get("experienciador_canonico"),
                    inferencia=e.get("experienciador"),
                ),
                str(e.get("tipo_emocion_canonico") or e.get("tipo_emocion") or ""),
                str(e.get("modo_existencia") or ""),
            )
            grupos.setdefault(clave, []).append(e)

        caidos: list[int] = []
        for miembros in grupos.values():
            if len(miembros) < 2:
                continue
            superviviente, *resto = miembros
            fuentes: list[str] = []
            for e in miembros:
                for cid in resolver_canonicos(
                    marcas_fte, e.get("fuente_marca"),
                    override=e.get("fuente_canonico"),
                    inferencia=e.get("fuente_inferencia"),
                ):
                    if cid not in fuentes:
                        fuentes.append(cid)
            if fuentes:
                self.set_fuente_canonico_at(
                    codigo, frase_idx, int(superviviente["emocion_idx"]),
                    "; ".join(fuentes),
                )
            for e in resto:
                idx = int(e["emocion_idx"])
                if self.delete_emocion(codigo, frase_idx, idx):
                    caidos.append(idx)
        return caidos

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
    ) -> dict[tuple[int, int], str]:
        """(frase_idx, emocion_idx) → el canónico del rol, uno por emoción.

        Para el experienciador, que nunca es más de uno. Resuelve con
        `storage.referencia`, el mismo resolutor que usan el dashboard y el
        export: por eso refleja las ediciones de la tab Referentes y las
        stages downstream ven el referente que muestra la revisión.
        """
        out: dict[tuple[int, int], str] = {}
        for key, (marca_map, marca) in self._marcas_por_emocion(
            codigo, funcion, marca_field
        ).items():
            canonical = resolver_canonico(marca_map, marca)
            if canonical:
                out[key] = canonical
        return out

    def resolve_canonicos_map(
        self,
        codigo: str,
        funcion: str,
        marca_field: str,
    ) -> dict[tuple[int, int], list[str]]:
        """(frase_idx, emocion_idx) → los canónicos del rol.

        Para la fuente, que puede combinar entidades en una sola emoción."""
        out: dict[tuple[int, int], list[str]] = {}
        for key, (marca_map, marca) in self._marcas_por_emocion(
            codigo, funcion, marca_field
        ).items():
            canonicos = resolver_canonicos(marca_map, marca)
            if canonicos:
                out[key] = canonicos
        return out

    def _marcas_por_emocion(
        self,
        codigo: str,
        funcion: str,
        marca_field: str,
    ) -> dict[tuple[int, int], tuple[Any, str]]:
        """(frase_idx, emocion_idx) → (marcas de la unidad, marca del rol).

        Devuelve {} si el run todavía no tiene base de menciones."""
        if marca_field not in self._MARCA_FIELDS:
            raise ValueError(f"marca_field inválido: {marca_field}")
        index = marca_canonicos_index(self._db, funcion, codigo)
        if not index:
            return {}
        return {
            (int(r["frase_idx"]), int(r["emocion_idx"])): (
                index.get((codigo, int(r["frase_idx"]))), r["marca"]
            )
            for r in self._db.execute(
                f"SELECT frase_idx, emocion_idx, {marca_field} AS marca "
                "FROM emociones WHERE codigo = ?",
                (codigo,),
            ).fetchall()
        }
