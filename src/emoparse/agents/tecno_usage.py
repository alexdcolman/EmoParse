# ══════════════════════════════════════════════════════════════════════════════
#  emoparse.agents.tecno_usage
#
#  Uso pragmático de menciones, tecnografismos y URLs, en contexto.
#
#  Opera a nivel unidad (post): cada fila del batch trae el texto de un post
#  y la lista de sus menciones (@cuenta, con posición), tecnografismos (con
#  subtipo) y URLs (con dominio), y el agente caracteriza el uso de cada
#  entidad en ese post (interpelar, confrontar, exponer, énfasis, ironía;
#  para URLs: fuente/prueba, autopromoción, convocatoria a la acción, enlace
#  temático). El output agrega la columna `usos` (JSON: lista de {valor, uso,
#  justificacion}).
# ══════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

import pandas as pd

from emoparse.agents.base import BaseBatchAgent
from emoparse.core.backend.base import LLMBackend
from emoparse.core.prompts import tecno_usage as prompts
from emoparse.core.schemas import (
    ListaTecnoUsosBatchSchema,
    TecnoUsoUnidadSchema,
)

if TYPE_CHECKING:
    from emoparse.genres.base import Genre


class TecnoUsageAgent(BaseBatchAgent[ListaTecnoUsosBatchSchema]):
    """Caracteriza el uso en contexto de menciones, tecnografismos y URLs."""

    NAME = "tecno_usage"
    SCHEMA = ListaTecnoUsosBatchSchema
    OUTPUT_COLUMNS = ("usos",)
    BATCH_SIZE = 3

    def __init__(
        self,
        backend: LLMBackend,
        heuristicas: str | None = None,
        retry_config: Any | None = None,
        genre: "Genre | None" = None,
    ) -> None:
        """
        Args:
            backend: Backend LLM utilizado para generación estructurada.
            heuristicas: Reglas heurísticas de caracterización. Si None, no
                se inyectan en el system prompt.
            retry_config: Política de reintentos ante errores transitorios.
            genre: Configuración opcional de género discursivo. Puede
                ajustar BATCH_SIZE vía `batch_size['tecno_usage']`.
        """
        self._heuristicas = heuristicas
        self._genre = genre

        if genre is not None and "tecno_usage" in genre.batch_size:
            self.BATCH_SIZE = genre.batch_size["tecno_usage"]  # type: ignore[misc]

        super().__init__(backend, retry_config=retry_config)

    # ── Hooks de BaseBatchAgent ──────────────────────────────────────────────

    def _build_system(self) -> str:
        return prompts.render_system(heuristicas=self._heuristicas)

    def _build_user(self, batch: pd.DataFrame) -> str:
        bloques: list[str] = []
        for i, (_, row) in enumerate(batch.iterrows()):
            bloques.append(
                f"UNIDAD [{i}]:\n"
                f"POST: {row.get('uso_texto', '')}\n"
                f"ENTIDADES:\n{row.get('entidades_txt', '')}"
            )
        return prompts.render_user(unidades_block="\n\n".join(bloques))

    def _map_item_to_columns(
        self,
        item: TecnoUsoUnidadSchema,
        row: pd.Series,
    ) -> dict[str, Any]:
        return {
            "usos": json.dumps(
                [u.model_dump() for u in item.usos], ensure_ascii=False
            )
        }
