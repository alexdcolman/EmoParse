# ══════════════════════════════════════════════════════════════════════════════
#  emoparse.storage.menciones
#
#  Repositorio de la base de marcas discursivas: `menciones`, `mencion_funcion`
#  y `mencion_canonico`.
#
#  Una `mencion` es una marca discursiva en su lugar (codigo, unit_idx),
#  independiente de su función actancial. Una misma marca puede cumplir varias
#  funciones (actor y experienciador a la vez): esas funciones viven en
#  `mencion_funcion`. Cada marca arranca con un canónico PROPUESTO derivado de
#  la inferencia del LLM; la normalización y la revisión humana lo refinan.
#
#  Las funciones `acumular_*` y `derivar_menciones` son puras: traducen los
#  payloads de los agentes (actores / emociones) a filas de mención sin tocar
#  la DB.
# ══════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

from typing import Any

from emoparse.pipeline.deixis import is_first_person_deictic
from emoparse.storage.db import Database
from emoparse.core.text import canonical_slug

#: Valores que cuentan como "sin referente" y no generan canónico propuesto.
_DESCONOCIDO = frozenset({
    "", "no identificado", "no_identificado", "no identificada",
    "no se identifica", "no_se_identifica", "ninguno", "ninguna", "?",
})


def _norm(s: Any) -> str:
    """Trim seguro a string."""
    return str(s or "").strip()


def _es_desconocido(s: str) -> bool:
    """True si la marca/inferencia no aporta referente."""
    return s.lower() in _DESCONOCIDO


def _acumular(
    acc: dict[tuple[int, str], dict[str, Any]],
    *,
    unit_idx: int,
    marca: str,
    funcion: str,
    inferencia: str,
) -> None:
    """Acumula una marca deduplicada por (unit_idx, marca).

    Una marca repetida (misma unidad) colapsa en una sola mención; sus
    funciones se acumulan. La inferencia (y el canónico propuesto) la fija la
    primera aparición con referente conocido.
    """
    marca = _norm(marca)
    if not marca:
        return
    key = (unit_idx, marca)
    entry = acc.get(key)
    if entry is None:
        inferencia = _norm(inferencia)
        canonical = "" if _es_desconocido(inferencia) else canonical_slug(inferencia)
        entry = {
            "unit_idx": unit_idx,
            "marca": marca,
            "llm_inferencia": inferencia or None,
            "canonical_proposed": canonical or None,
            "funciones": set(),
        }
        acc[key] = entry
    elif entry["llm_inferencia"] is None:
        inferencia = _norm(inferencia)
        if not _es_desconocido(inferencia):
            entry["llm_inferencia"] = inferencia
            entry["canonical_proposed"] = canonical_slug(inferencia)
    entry["funciones"].add(funcion)


def acumular_actores(
    acc: dict[tuple[int, str], dict[str, Any]],
    actores_by_unit: dict[int, list[dict[str, Any]]],
) -> None:
    """Suma marcas de actor (funcion='actor') desde payloads de ActorsAgent."""
    for unit_idx, actores in actores_by_unit.items():
        if not isinstance(actores, list):
            continue
        for a in actores:
            if not isinstance(a, dict):
                continue
            marca = _norm(a.get("marca")) or _norm(a.get("actor"))
            _acumular(
                acc,
                unit_idx=unit_idx,
                marca=marca,
                funcion="actor",
                inferencia=_norm(a.get("actor")),
            )


def acumular_emociones(
    acc: dict[tuple[int, str], dict[str, Any]],
    emociones_by_unit: dict[int, list[dict[str, Any]]],
) -> None:
    """Suma marcas de experienciador y fuente desde payloads de EmotionsAgent."""
    for unit_idx, emociones in emociones_by_unit.items():
        if not isinstance(emociones, list):
            continue
        for e in emociones:
            if not isinstance(e, dict):
                continue
            _acumular(
                acc,
                unit_idx=unit_idx,
                marca=_norm(e.get("experienciador_marca")),
                funcion="experienciador",
                inferencia=_norm(e.get("experienciador")),
            )
            fuente_marca = _norm(e.get("fuente_marca"))
            if not _es_desconocido(fuente_marca):
                _acumular(
                    acc,
                    unit_idx=unit_idx,
                    marca=fuente_marca,
                    funcion="fuente",
                    inferencia=_norm(e.get("fuente_inferencia")),
                )


def derivar_menciones(
    actores_by_unit: dict[int, list[dict[str, Any]]],
    emociones_by_unit: dict[int, list[dict[str, Any]]],
) -> list[dict[str, Any]]:
    """Deriva las menciones de un discurso desde los payloads de los agentes.

    Funde por (unit_idx, marca), de modo que una marca con varias funciones
    (p. ej. actor y experienciador) produce UNA mención con ambas funciones.
    """
    acc: dict[tuple[int, str], dict[str, Any]] = {}
    acumular_actores(acc, actores_by_unit)
    acumular_emociones(acc, emociones_by_unit)
    return list(acc.values())


class MencionesRepository:
    """Repositorio de `menciones`, `mencion_funcion` y `mencion_canonico`."""

    def __init__(self, db: Database) -> None:
        self._db = db

    # ── Población ──────────────────────────────────────────────────────────────

    def rebuild_for_codigo(
        self,
        codigo: str,
        actores_by_unit: dict[int, list[dict[str, Any]]],
        emociones_by_unit: dict[int, list[dict[str, Any]]],
    ) -> dict[str, int]:
        """Reconstruye las menciones de un discurso desde los payloads.

        Idempotente: borra las menciones del código (la FK cascada limpia
        `mencion_funcion` y `mencion_canonico`) y reinserta. Cada mención
        siembra sus funciones y un canónico propuesto desde la inferencia.
        """
        derivadas = derivar_menciones(actores_by_unit, emociones_by_unit)

        counts = {"menciones": 0, "funciones": 0, "canonicos": 0}
        with self._db.transaction() as cur:
            cur.execute("DELETE FROM menciones WHERE codigo = ?", (codigo,))
            for m in derivadas:
                cur.execute(
                    "INSERT INTO menciones "
                    "(codigo, unit_idx, marca, llm_inferencia, origin) "
                    "VALUES (?, ?, ?, ?, 'llm')",
                    (codigo, m["unit_idx"], m["marca"], m["llm_inferencia"]),
                )
                mencion_id = cur.lastrowid
                counts["menciones"] += 1
                for funcion in sorted(m["funciones"]):
                    cur.execute(
                        "INSERT OR IGNORE INTO mencion_funcion "
                        "(mencion_id, funcion, origin) VALUES (?, ?, 'llm')",
                        (mencion_id, funcion),
                    )
                    counts["funciones"] += 1
                canonical = m["canonical_proposed"]
                if canonical:
                    cur.execute(
                        "INSERT OR IGNORE INTO mencion_canonico "
                        "(mencion_id, canonical_id, status, origin) "
                        "VALUES (?, ?, 'proposed', 'llm')",
                        (mencion_id, canonical),
                    )
                    counts["canonicos"] += 1
        return counts

    def propose_coref_equivalences(self, codigo: str) -> int:
        """Agrupa automáticamente marcas correferentes bajo un canónico compartido.

        Construcción de correferencias AUTOMÁTICA: clustering léxico conservador
        (coref) sobre TODAS las marcas del discurso —actores, experienciadores y
        fuentes—. A cada cluster le asigna como canónico propuesto
        (`origin='coref'`) la inferencia DOMINANTE del LLM en el cluster (la más
        frecuente entre sus menciones), con fallback al slug de la mención
        representativa cuando no hay inferencia útil. Así un cluster de marcas
        "los secuestrados"/"los rehenes" cuya inferencia es "personas
        secuestradas" recibe el canónico `personas_secuestradas` en lugar del
        slug de la marca. No toca las marcas con un canónico ya aceptado.
        Devuelve cuántas propuestas agregó.
        """
        from collections import Counter

        from emoparse.pipeline.coref import (
            cluster_mentions_within_discurso,
            pick_representative,
        )
        rows = self._db.execute(
            "SELECT id, unit_idx, marca, llm_inferencia FROM menciones "
            "WHERE codigo = ? ORDER BY unit_idx, id",
            (codigo,),
        ).fetchall()
        if not rows:
            return 0

        by_unit: dict[int, list[dict[str, Any]]] = {}
        keymap: dict[tuple[int, int], int] = {}
        inf_by_key: dict[tuple[int, int], str] = {}
        for r in rows:
            lst = by_unit.setdefault(r["unit_idx"], [])
            key = (r["unit_idx"], len(lst))
            keymap[key] = r["id"]
            inf_by_key[key] = r["llm_inferencia"] or ""
            lst.append({"actor": r["marca"]})

        clusters = cluster_mentions_within_discurso(list(by_unit.items()))
        accepted = {
            row["mencion_id"]
            for row in self._db.execute(
                "SELECT mc.mencion_id FROM mencion_canonico mc "
                "JOIN menciones m ON m.id = mc.mencion_id "
                "WHERE m.codigo = ? AND mc.status = 'accepted'",
                (codigo,),
            ).fetchall()
        }

        def _dominant_canonical(cluster: set) -> str:
            """Slug de la inferencia LLM dominante del cluster; '' si no hay."""
            slugs = [
                canonical_slug(inf_by_key.get(k, ""))
                for k in cluster
                if (inf := inf_by_key.get(k, "")) and not _es_desconocido(inf)
            ]
            slugs = [s for s in slugs if s]
            if not slugs:
                return ""
            counts = Counter(slugs)
            top = max(counts.values())
            # Desempate determinista: más específico (más largo) y luego alfabético.
            return sorted(
                (s for s, n in counts.items() if n == top),
                key=lambda s: (-len(s), s),
            )[0]

        added = 0
        with self._db.transaction() as cur:
            for cluster in clusters:
                if len(cluster) < 2:
                    continue
                canonical = _dominant_canonical(cluster) or canonical_slug(
                    pick_representative(cluster, by_unit)
                )
                if not canonical:
                    continue
                for key in cluster:
                    mid = keymap.get(key)
                    if mid is None or mid in accepted:
                        continue
                    cur.execute(
                        "INSERT OR IGNORE INTO mencion_canonico "
                        "(mencion_id, canonical_id, status, origin) "
                        "VALUES (?, ?, 'proposed', 'coref')",
                        (mid, canonical),
                    )
                    added += cur.rowcount
        return added

    def add_deixis_suggestions(self, codigo: str, enunciador: str) -> int:
        """Propone el enunciador como canónico de las marcas deícticas de 1ª persona.

        La marca deíctica ("nosotros", "tomamos"…) NO se resuelve sola: se suma
        como propuesta destildable (`origin='deixis'`) que la revisión humana
        acepta o descarta. Devuelve cuántas propuestas se agregaron.
        """
        enunciador = _norm(enunciador)
        canonical = canonical_slug(enunciador) if enunciador else ""
        if not canonical:
            return 0
        rows = self._db.execute(
            "SELECT id, marca FROM menciones WHERE codigo = ?", (codigo,)
        ).fetchall()
        added = 0
        with self._db.transaction() as cur:
            for r in rows:
                if is_first_person_deictic(r["marca"]):
                    cur.execute(
                        "INSERT OR IGNORE INTO mencion_canonico "
                        "(mencion_id, canonical_id, status, origin) "
                        "VALUES (?, ?, 'proposed', 'deixis')",
                        (r["id"], canonical),
                    )
                    added += cur.rowcount
        return added

    def list_marcas_for_deixis(self, codigo: str) -> list[dict[str, Any]]:
        """Marcas del discurso candidatas para resolución deíctica (id + marca)."""
        rows = self._db.execute(
            "SELECT id, unit_idx, marca FROM menciones WHERE codigo = ? "
            "ORDER BY unit_idx, id",
            (codigo,),
        ).fetchall()
        return [dict(r) for r in rows]

    def has_deixis_llm(self, codigo: str) -> bool:
        """True si el discurso ya tiene vínculos resueltos por la stage deixis."""
        row = self._db.execute(
            "SELECT 1 FROM mencion_canonico mc "
            "JOIN menciones m ON m.id = mc.mencion_id "
            "WHERE m.codigo = ? AND mc.origin = 'deixis_llm' LIMIT 1",
            (codigo,),
        ).fetchone()
        return row is not None

    def link_deixis(
        self,
        mencion_id: int,
        canonical_id: str,
        deixis_tipo: str,
    ) -> int:
        """Vincula una marca deíctica a su referente concreto (propuesta).

        `canonical_id` es el referente ESPECÍFICO (p. ej. `javier_milei`),
        nunca el tipo. `deixis_tipo` registra la categoría esquemática
        (`enunciador` | `auditorio` | `colectivo_identificacion`). Si ya
        existía el par marca↔canónico (p. ej. propuesto por la deixis
        determinista), lo promueve a origin='deixis_llm' y le fija el tipo,
        sin pisar un vínculo ya aceptado/rechazado por revisión humana.
        """
        canonical_id = canonical_slug(canonical_id)
        if not canonical_id:
            return 0
        with self._db.transaction() as cur:
            cur.execute(
                "INSERT INTO mencion_canonico "
                "(mencion_id, canonical_id, status, origin, deixis_tipo) "
                "VALUES (?, ?, 'proposed', 'deixis_llm', ?) "
                "ON CONFLICT(mencion_id, canonical_id) DO UPDATE SET "
                "    deixis_tipo = excluded.deixis_tipo, "
                "    origin = CASE WHEN mencion_canonico.status = 'proposed' "
                "                  THEN 'deixis_llm' ELSE mencion_canonico.origin END",
                (mencion_id, canonical_id, deixis_tipo),
            )
            return cur.rowcount

    def accept_deixis_link(self, mencion_id: int, canonical_id: str) -> None:
        """Acepta un referente deíctico para una marca y sobreescribe el automático.

        Marca el vínculo (marca↔referente concreto) como aceptado y rechaza los
        vínculos automáticos competidores de esa misma marca (inferencia/coref/
        auto), para que la marca quede inscripta en el referente deíctico y deje
        de colgar del canónico que el LLM había inventado. Respeta los vínculos
        hechos a mano (`origin='human'`) y los demás referentes deícticos
        (que se revisan por separado).
        """
        from datetime import datetime, timezone

        now = datetime.now(timezone.utc)
        with self._db.transaction() as cur:
            cur.execute(
                "UPDATE mencion_canonico SET status = 'accepted', reviewed_at = ? "
                "WHERE mencion_id = ? AND canonical_id = ?",
                (now, mencion_id, canonical_id),
            )
            cur.execute(
                "UPDATE mencion_canonico SET status = 'rejected', reviewed_at = ? "
                "WHERE mencion_id = ? AND canonical_id != ? "
                "AND origin NOT IN ('deixis_llm', 'human')",
                (now, mencion_id, canonical_id),
            )

    def reject_deixis_link(self, mencion_id: int, canonical_id: str) -> None:
        """Rechaza un referente deíctico propuesto para una marca."""
        from datetime import datetime, timezone

        now = datetime.now(timezone.utc)
        with self._db.transaction() as cur:
            cur.execute(
                "UPDATE mencion_canonico SET status = 'rejected', reviewed_at = ? "
                "WHERE mencion_id = ? AND canonical_id = ?",
                (now, mencion_id, canonical_id),
            )

    def add_deixis_referente(
        self, mencion_id: int, canonical_id: str, deixis_tipo: str
    ) -> None:
        """Agrega a mano un referente deíctico a una marca (lo deja aceptado).

        Inscribe la marca en el referente concreto y sobreescribe el canónico
        automático, igual que `accept_deixis_link`. Útil cuando se rechaza la
        sugerencia del LLM y se quiere asignar otro referente del discurso.
        """
        from datetime import datetime, timezone

        canonical_id = canonical_slug(canonical_id)
        if not canonical_id:
            return
        now = datetime.now(timezone.utc)
        with self._db.transaction() as cur:
            cur.execute(
                "INSERT INTO mencion_canonico "
                "(mencion_id, canonical_id, status, origin, deixis_tipo, reviewed_at) "
                "VALUES (?, ?, 'accepted', 'human', ?, ?) "
                "ON CONFLICT(mencion_id, canonical_id) DO UPDATE SET "
                "    status = 'accepted', deixis_tipo = excluded.deixis_tipo, "
                "    reviewed_at = excluded.reviewed_at",
                (mencion_id, canonical_id, deixis_tipo, now),
            )
            cur.execute(
                "UPDATE mencion_canonico SET status = 'rejected', reviewed_at = ? "
                "WHERE mencion_id = ? AND canonical_id != ? "
                "AND origin NOT IN ('deixis_llm', 'human')",
                (now, mencion_id, canonical_id),
            )

    def propose_kb_equivalences(
        self,
        codigo: str,
        referentes_kb: dict[str, Any] | None,
    ) -> int:
        """Propone equivalencias de las marcas contra la KB de referentes.

        Para cada mención sin canónico aceptado, si el slug de su inferencia o
        de su marca coincide con un `canonical_id` conocido en la KB, agrega una
        propuesta destildable (`origin='auto'`). Con la KB vacía no hace nada;
        crece a medida que se aceptan referentes. Devuelve cuántas agregó.
        """
        referentes = (referentes_kb or {}).get("referentes") or {}
        if not referentes:
            return 0
        # Comparación insensible a artículos: tanto el candidato como las
        # claves de la KB se normalizan con canonical_slug. Se vincula a la
        # clave original para no orfanar referentes preexistentes.
        known_map = {canonical_slug(k): k for k in referentes.keys()}
        rows = self._db.execute(
            """
            SELECT m.id, m.marca, m.llm_inferencia
            FROM menciones m
            WHERE m.codigo = ?
              AND NOT EXISTS (
                  SELECT 1 FROM mencion_canonico mc
                  WHERE mc.mencion_id = m.id AND mc.status = 'accepted'
              )
            """,
            (codigo,),
        ).fetchall()
        added = 0
        with self._db.transaction() as cur:
            for r in rows:
                for cand in (canonical_slug(r["llm_inferencia"] or ""),
                             canonical_slug(r["marca"] or "")):
                    target = known_map.get(cand) if cand else None
                    if target:
                        cur.execute(
                            "INSERT OR IGNORE INTO mencion_canonico "
                            "(mencion_id, canonical_id, status, origin) "
                            "VALUES (?, ?, 'proposed', 'auto')",
                            (r["id"], target),
                        )
                        added += cur.rowcount
        return added

    # ── Revisión (escritura) ───────────────────────────────────────────────
    def set_link_status(
        self, mencion_id: int, canonical_id: str, status: str
    ) -> None:
        """Acepta o rechaza un vínculo marca↔canónico ('accepted'|'rejected'|'proposed')."""
        from datetime import datetime, timezone
        with self._db.transaction() as cur:
            cur.execute(
                "UPDATE mencion_canonico SET status = ?, reviewed_at = ? "
                "WHERE mencion_id = ? AND canonical_id = ?",
                (status, datetime.now(timezone.utc), mencion_id, canonical_id),
            )

    def add_human_link(self, mencion_id: int, canonical_id: str) -> None:
        """Agrega (o acepta) un vínculo creado por el analista."""
        from datetime import datetime, timezone
        canonical_id = canonical_slug(canonical_id)
        if not canonical_id:
            return
        with self._db.transaction() as cur:
            cur.execute(
                "INSERT INTO mencion_canonico "
                "(mencion_id, canonical_id, status, origin, reviewed_at) "
                "VALUES (?, ?, 'accepted', 'human', ?) "
                "ON CONFLICT(mencion_id, canonical_id) DO UPDATE SET "
                "status = 'accepted', reviewed_at = excluded.reviewed_at",
                (mencion_id, canonical_id, datetime.now(timezone.utc)),
            )

    def remove_link(self, mencion_id: int, canonical_id: str) -> None:
        """Elimina un vínculo marca↔canónico."""
        with self._db.transaction() as cur:
            cur.execute(
                "DELETE FROM mencion_canonico "
                "WHERE mencion_id = ? AND canonical_id = ?",
                (mencion_id, canonical_id),
            )

    # ── Semas del referente ─────────────────────────────────────────────────
    def propose_semas(
        self,
        canonical_id: str,
        semas: list[str],
        *,
        allowed: set[str] | None = None,
        origin: str = "llm",
    ) -> int:
        """Agrega semas propuestos a un referente, normalizados al vocabulario.

        Si `allowed` se pasa, descarta los semas fuera del vocabulario curado.
        No pisa un sema ya existente (respeta decisiones humanas). Devuelve
        cuántos agregó.
        """
        canonical_id = canonical_slug(canonical_id)
        added = 0
        with self._db.transaction() as cur:
            for sema in semas:
                sema = (sema or "").strip().lower()
                if not sema or (allowed is not None and sema not in allowed):
                    continue
                cur.execute(
                    "INSERT OR IGNORE INTO canonico_semas "
                    "(canonical_id, sema, status, origin) "
                    "VALUES (?, ?, 'proposed', ?)",
                    (canonical_id, sema, origin),
                )
                added += cur.rowcount
        return added

    def set_sema(
        self, canonical_id: str, sema: str, status: str = "accepted"
    ) -> None:
        """Acepta/rechaza o agrega (humano) un sema de un referente."""
        canonical_id = canonical_slug(canonical_id)
        sema = (sema or "").strip().lower()
        if not canonical_id or not sema:
            return
        with self._db.transaction() as cur:
            cur.execute(
                "INSERT INTO canonico_semas "
                "(canonical_id, sema, status, origin) "
                "VALUES (?, ?, ?, 'human') "
                "ON CONFLICT(canonical_id, sema) DO UPDATE SET status = excluded.status",
                (canonical_id, sema, status),
            )

    def remove_sema(self, canonical_id: str, sema: str) -> None:
        """Elimina un sema de un referente."""
        with self._db.transaction() as cur:
            cur.execute(
                "DELETE FROM canonico_semas WHERE canonical_id = ? AND sema = ?",
                (canonical_slug(canonical_id), (sema or "").strip().lower()),
            )

    def list_semas(self, canonical_id: str) -> list[dict[str, Any]]:
        """Semas de un referente con su estado y origen."""
        rows = self._db.execute(
            "SELECT sema, status, origin FROM canonico_semas "
            "WHERE canonical_id = ? ORDER BY sema",
            (canonical_slug(canonical_id),),
        ).fetchall()
        return [dict(r) for r in rows]

    def canonicos_by_sema(
        self, sema: str, status: str = "accepted"
    ) -> set[str]:
        """Canónicos que tienen un sema dado (por defecto, aceptado)."""
        rows = self._db.execute(
            "SELECT canonical_id FROM canonico_semas "
            "WHERE sema = ? AND status = ?",
            ((sema or "").strip().lower(), status),
        ).fetchall()
        return {r["canonical_id"] for r in rows}

    def list_canonicos(self, sample: int = 8) -> list[dict[str, Any]]:
        """Referentes canónicos con una muestra de sus marcas (excluye rechazados)."""
        rows = self._db.execute(
            "SELECT mc.canonical_id AS canonical_id, "
            "       group_concat(DISTINCT m.marca) AS marcas "
            "FROM mencion_canonico mc "
            "JOIN menciones m ON m.id = mc.mencion_id "
            "WHERE mc.status != 'rejected' "
            "GROUP BY mc.canonical_id "
            "ORDER BY mc.canonical_id",
            (),
        ).fetchall()
        out: list[dict[str, Any]] = []
        for r in rows:
            marcas = [s for s in (r["marcas"] or "").split(",") if s][:sample]
            out.append({"canonical_id": r["canonical_id"], "marcas": marcas})
        return out

    def canonicos_con_semas(self) -> set[str]:
        """Canónicos que ya tienen algún sema (para no re-proponer)."""
        rows = self._db.execute(
            "SELECT DISTINCT canonical_id FROM canonico_semas"
        ).fetchall()
        return {r["canonical_id"] for r in rows}

    def accepted_referentes(self) -> list[dict[str, Any]]:
        """Referentes con ≥1 vínculo ACEPTADO, con clase inferida y display.

        Para materializar en `referentes_kb`. `clase` se infiere de las
        funciones de sus marcas (actor/experienciador → actor; solo fuente →
        circunstante; en otro caso → referente). `display_name` es la marca más
        larga vista.
        """
        rows = self._db.execute(
            "SELECT mc.canonical_id AS canonical_id, "
            "       group_concat(DISTINCT mf.funcion) AS funciones, "
            "       group_concat(DISTINCT m.marca) AS marcas "
            "FROM mencion_canonico mc "
            "JOIN menciones m ON m.id = mc.mencion_id "
            "LEFT JOIN mencion_funcion mf ON mf.mencion_id = m.id "
            "WHERE mc.status = 'accepted' "
            "GROUP BY mc.canonical_id "
            "ORDER BY mc.canonical_id",
            (),
        ).fetchall()
        out: list[dict[str, Any]] = []
        for r in rows:
            funcs = {f for f in (r["funciones"] or "").split(",") if f}
            if {"actor", "experienciador"} & funcs:
                clase = "actor"
            elif funcs == {"fuente"}:
                clase = "circunstante"
            else:
                clase = "referente"
            marcas = [x for x in (r["marcas"] or "").split(",") if x]
            display = max(marcas, key=len) if marcas else r["canonical_id"]
            out.append({
                "canonical_id": r["canonical_id"],
                "clase": clase,
                "display_name": display,
            })
        return out

    # ── Lookup ─────────────────────────────────────────────────────────────────

    def list_for_codigo(self, codigo: str) -> list[dict[str, Any]]:
        """Menciones de un discurso con funciones y canónicos agregados.

        Una fila por mención; `funciones` y `canonicos` vienen como listas
        separadas por coma (estas últimas como 'canonical_id:status').
        """
        rows = self._db.execute(
            """
            SELECT
                m.id, m.codigo, m.unit_idx, m.marca, m.llm_inferencia, m.origin,
                (SELECT group_concat(funcion)
                   FROM mencion_funcion WHERE mencion_id = m.id) AS funciones,
                (SELECT group_concat(canonical_id || ':' || status)
                   FROM mencion_canonico WHERE mencion_id = m.id) AS canonicos
            FROM menciones m
            WHERE m.codigo = ?
            ORDER BY m.unit_idx, m.marca
            """,
            (codigo,),
        ).fetchall()
        return [dict(r) for r in rows]

    def counts_for_codigo(self, codigo: str) -> dict[str, int]:
        """Conteo de menciones por función para un discurso."""
        rows = self._db.execute(
            """
            SELECT mf.funcion AS funcion, COUNT(DISTINCT mf.mencion_id) AS n
            FROM mencion_funcion mf
            JOIN menciones m ON m.id = mf.mencion_id
            WHERE m.codigo = ?
            GROUP BY mf.funcion
            """,
            (codigo,),
        ).fetchall()
        return {r["funcion"]: int(r["n"]) for r in rows}
