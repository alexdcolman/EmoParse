# ══════════════════════════════════════════════════════════════════════════════
#  emoparse.agents.semas
#
#  Batch agent para asignación de semas a referentes canónicos.
# ══════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

import pandas as pd

from emoparse.agents.base import BaseBatchAgent
from emoparse.core.backend.base import LLMBackend
from emoparse.core.prompts import semas as prompts
from emoparse.core.schemas import (
    ListaSemasBatchSchema,
    SemasBatchItemSchema,
)

if TYPE_CHECKING:
    from emoparse.genres.base import Genre


class SemasAgent(BaseBatchAgent[ListaSemasBatchSchema]):
    """Asigna semas (del vocabulario curado) a cada referente canónico.

    Cada unidad del batch es un referente, con su denominación y una muestra de
    sus marcas discursivas. Agrega la columna `semas` (JSON con la lista de
    semas propuestos).
    """

    NAME = "semas"
    SCHEMA = ListaSemasBatchSchema
    OUTPUT_COLUMNS = ("semas",)
    BATCH_SIZE = 10

    def __init__(
        self,
        backend: LLMBackend,
        vocabulario: str,
        titulo: str = "",
        tipo_discurso: str = "",
        retry_config: Any | None = None,
        genre: "Genre | None" = None,
    ) -> None:
        """
        Args:
            backend: Backend LLM utilizado para generación estructurada.
            vocabulario: Vocabulario de semas formateado para el prompt.
            titulo: Título del run/corpus (contexto).
            tipo_discurso: Tipo de discurso (contexto).
            retry_config: Política de reintentos ante errores transitorios.
            genre: Permite sobrescribir `BATCH_SIZE` si define
                `batch_size["semas"]`.
        """
        self._vocabulario = vocabulario
        self._titulo = titulo
        self._tipo_discurso = tipo_discurso
        self._genre = genre

        if genre is not None and "semas" in genre.batch_size:
            self.BATCH_SIZE = genre.batch_size["semas"]  # type: ignore[misc]

        super().__init__(backend, retry_config=retry_config)

    # ── Hooks ────────────────────────────────────────────────────────────────

    def _build_system(self) -> str:
        return prompts.render_system(
            vocabulario=self._vocabulario,
            titulo=self._titulo,
            tipo_discurso=self._tipo_discurso,
        )

    def _build_user(self, batch: pd.DataFrame) -> str:
        bloques: list[str] = []
        for i, (_, row) in enumerate(batch.iterrows()):
            disp = str(row.get("display") or row.get("canonical_id") or "")
            marcas = row.get("marcas")
            if isinstance(marcas, (list, tuple)):
                marcas_str = "; ".join(str(x) for x in marcas)
            else:
                marcas_str = str(marcas or "")
            bloques.append(
                f"REFERENTE [{i}] ({disp}):\n  Marcas: {marcas_str}"
            )
        return prompts.render_user("\n\n".join(bloques))

    def _map_item_to_columns(
        self,
        item: SemasBatchItemSchema,
        row: pd.Series,
    ) -> dict[str, Any]:
        return {"semas": json.dumps(list(item.semas), ensure_ascii=False)}
