# ══════════════════════════════════════════════════════════════════════════════
#  emoparse.pipeline.payload_selection
#
#  Resolución de selectores cuyo campo proviene de payloads ya persistidos.
# ══════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from emoparse.inputs.seleccion import Seleccion, SeleccionError, SelectorFiltro
from emoparse.pipeline.dag import EMOPARSE_DAG
from emoparse.pipeline.filter_sql import where_for_json_filters
from emoparse.storage.db import Database
from emoparse.storage.selector_scope import SelectorScopeRepository


@dataclass(frozen=True, slots=True)
class PayloadSource:
    """Ubicación SQL de un payload y su vínculo con el discurso."""

    from_sql: str
    codigo_expr: str
    payload_expr: str
    completion_where: str
    base_where: str = "1"


_PAYLOAD_SOURCES: dict[str, PayloadSource] = {
    "summarizer": PayloadSource(
        "discursos",
        "codigo",
        "summarizer_payload",
        "summarizer_payload IS NOT NULL AND summarizer_error IS NULL",
    ),
    "metadata": PayloadSource(
        "discursos",
        "codigo",
        "metadata_payload",
        "metadata_payload IS NOT NULL AND metadata_error IS NULL",
    ),
    "enunciation": PayloadSource(
        "discursos",
        "codigo",
        "enunciation_payload",
        "enunciation_payload IS NOT NULL AND enunciation_error IS NULL",
    ),
    "actors": PayloadSource(
        "frases",
        "codigo",
        "actores_payload",
        "actores_payload IS NOT NULL AND actores_error IS NULL",
    ),
    "emotions": PayloadSource(
        "frases",
        "codigo",
        "emociones_payload",
        "emociones_payload IS NOT NULL AND emociones_error IS NULL",
    ),
    "emotions_pass2": PayloadSource(
        "frases",
        "codigo",
        "emociones_pass2_payload",
        "emociones_pass2_payload IS NOT NULL AND emociones_pass2_error IS NULL",
    ),
    "characterizer": PayloadSource(
        "emociones",
        "codigo",
        "caracterizacion_payload",
        "caracterizacion_payload IS NOT NULL AND caracterizacion_error IS NULL",
    ),
    "actants": PayloadSource(
        "emociones",
        "codigo",
        "actantes_payload",
        "actantes_payload IS NOT NULL AND actantes_error IS NULL",
    ),
    "reframing": PayloadSource(
        "posts",
        "post_id",
        "reframing_payload",
        "reframing_payload IS NOT NULL AND reframing_error IS NULL",
        "es_repost_puro = 0 AND (cita_a IS NOT NULL OR "
        "(reposteo_a IS NOT NULL AND TRIM(texto) != ''))",
    ),
    "vision_describe": PayloadSource(
        "media",
        "post_id",
        "descripcion_payload",
        "descripcion_payload IS NOT NULL AND descripcion_error IS NULL",
        "tipo = 'imagen' AND (url IS NOT NULL OR path_local IS NOT NULL)",
    ),
    "hashtag_semiotics": PayloadSource(
        "tecno_entidades te JOIN hashtags h ON h.valor_norm = te.valor_norm",
        "te.codigo",
        "h.analisis_payload",
        "h.analisis_payload IS NOT NULL AND h.analisis_error IS NULL",
        "te.tipo = 'hashtag' AND h.n_usos >= 1",
    ),
}


class PayloadSelectionEngine:
    """Calcula y persiste el alcance dinámico antes de cada stage."""

    def __init__(
        self,
        db: Database,
        selection: Seleccion | None,
        enabled_stages: tuple[str, ...],
    ) -> None:
        self._db = db
        self._selection = selection
        self._enabled = tuple(enabled_stages)
        self._order = EMOPARSE_DAG.toposort()
        self._order_index = {name: index for index, name in enumerate(self._order)}
        self._repo = SelectorScopeRepository(db)
        self._filters = self._group_payload_filters(selection)

    @property
    def active(self) -> bool:
        """True cuando el selector contiene filtros sobre payloads."""
        return bool(self._filters)

    def prepare(self) -> None:
        """Valida productores, orden y disponibilidad previa."""
        self._repo.clear_all()
        if not self.active:
            return

        enabled = set(self._enabled)
        for producer in self._filters:
            if producer not in _PAYLOAD_SOURCES:
                supported = ", ".join(sorted(_PAYLOAD_SOURCES))
                raise SeleccionError(
                    f"El selector usa '{producer}', pero esa stage todavía no "
                    f"expone un payload seleccionable. Disponibles: {supported}."
                )
            later_enabled = [
                stage
                for stage in self._enabled
                if self._order_index[stage] > self._order_index[producer]
            ]
            if not later_enabled:
                raise SeleccionError(
                    f"El filtro sobre '{producer}' no puede afectar ninguna "
                    "stage habilitada posterior. Agregá stages posteriores o "
                    "sacá ese filtro del selector."
                )
            if producer not in enabled and not self._producer_complete(producer):
                field = self._filters[producer][0].field
                raise SeleccionError(
                    f"'{field}' requiere que '{producer}' esté completa; "
                    "corré primero esa etapa o sacala del selector."
                )

    def scope_for(self, stage: str) -> frozenset[str] | None:
        """Códigos en alcance de `stage`, o None si aún no aplica ningún filtro."""
        active = {
            producer: filters
            for producer, filters in self._filters.items()
            if self._order_index[producer] < self._order_index[stage]
        }
        all_codes = self._all_codes()
        if not active:
            self._repo.replace_stage(stage, all_codes, None, None)
            return None

        scope = set(all_codes)
        for producer, filters in active.items():
            if not self._producer_complete(producer):
                field = filters[0].field
                raise SeleccionError(
                    f"'{field}' requiere que '{producer}' esté completa; "
                    "corré primero esa etapa o sacala del selector."
                )
            scope &= self._matching_codes(producer, filters)

        if not scope:
            details = " y ".join(item.leer() for filters in active.values() for item in filters)
            raise SeleccionError(
                f"Ninguna unidad cumple los filtros de payload ya resolubles "
                f"para '{stage}' ({details})."
            )

        details = " y ".join(item.leer() for filters in active.values() for item in filters)
        self._repo.replace_stage(stage, all_codes, scope, details)
        return frozenset(scope)

    def _producer_complete(self, producer: str) -> bool:
        source = _PAYLOAD_SOURCES[producer]
        total = self._scalar(f"SELECT COUNT(*) FROM {source.from_sql} WHERE ({source.base_where})")
        if total == 0:
            return True
        completed = self._scalar(
            f"SELECT COUNT(*) FROM {source.from_sql} "
            f"WHERE ({source.base_where}) AND ({source.completion_where})"
        )
        return completed == total

    def _matching_codes(
        self,
        producer: str,
        filters: list[SelectorFiltro],
    ) -> set[str]:
        source = _PAYLOAD_SOURCES[producer]
        local_filters = [item.without_stage_prefix() for item in filters]
        clauses, params = where_for_json_filters(
            local_filters,
            source.payload_expr,
            case_sensitive_contains=False,
        )
        where = [f"({source.base_where})", f"{source.payload_expr} IS NOT NULL"]
        where.extend(clauses)
        rows = self._db.execute(
            f"SELECT DISTINCT {source.codigo_expr} AS codigo "
            f"FROM {source.from_sql} WHERE " + " AND ".join(where),
            tuple(params),
        ).fetchall()
        return {str(row["codigo"]) for row in rows}

    def _all_codes(self) -> list[str]:
        rows = self._db.execute("SELECT codigo FROM discursos ORDER BY codigo").fetchall()
        return [str(row["codigo"]) for row in rows]

    def _scalar(self, sql: str, params: tuple[Any, ...] = ()) -> int:
        row = self._db.execute(sql, params).fetchone()
        return int(row[0] or 0) if row is not None else 0

    @staticmethod
    def _group_payload_filters(
        selection: Seleccion | None,
    ) -> dict[str, list[SelectorFiltro]]:
        grouped: dict[str, list[SelectorFiltro]] = {}
        if selection is None:
            return grouped
        for item in selection.payload_filters():
            producer = item.source_stage
            assert producer is not None
            grouped.setdefault(producer, []).append(item)
        return grouped
