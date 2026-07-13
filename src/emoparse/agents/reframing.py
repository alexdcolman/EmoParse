# ══════════════════════════════════════════════════════════════════════════════
#  emoparse.agents.reframing
#
#  Clasificación de la operación de redocumentación en citas y reposts.
#
#  Un post que cita a otro (quote) o lo repostea con comentario no es un
#  enunciado aislado: recontextualiza discurso ajeno. Este agente clasifica
#  esa operación (adhesión, ironía/distancia, denuncia, difusión neutra,
#  ambigua) y el estatuto de las emociones del texto citado respecto del
#  citador (asumidas / semiotizadas / ninguna), insumo para no atribuir al
#  citador emociones que solo exhibe.
#
#  Cada fila de entrada debe incluir: `texto` (post citador), `autor`,
#  `texto_citado`, `autor_citado` y `operatoria` ('cita'|'repost_comentado').
#  El output agrega la columna `reframing` (JSON).
# ══════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

import pandas as pd

from emoparse.agents.base import BaseBatchAgent
from emoparse.core.backend.base import LLMBackend
from emoparse.core.prompts import reframing as prompts
from emoparse.core.schemas import (
    ListaReframingsBatchSchema,
    ReframingBatchItemSchema,
)

if TYPE_CHECKING:
    from emoparse.genres.base import Genre


class ReframingAgent(BaseBatchAgent[ListaReframingsBatchSchema]):
    """Clasifica la operación de recontextualización de posts que citan."""

    NAME = "reframing"
    SCHEMA = ListaReframingsBatchSchema
    OUTPUT_COLUMNS = ("reframing",)
    BATCH_SIZE = 8

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
            heuristicas: Reglas heurísticas de clasificación. Si None, no
                se inyectan en el system prompt.
            retry_config: Política de reintentos ante errores transitorios.
            genre: Configuración opcional de género discursivo. Puede
                ajustar BATCH_SIZE vía `batch_size['reframing']`.
        """
        self._heuristicas = heuristicas
        self._genre = genre

        if genre is not None and "reframing" in genre.batch_size:
            self.BATCH_SIZE = genre.batch_size["reframing"]  # type: ignore[misc]

        super().__init__(backend, retry_config=retry_config)

    # ── Hooks de BaseBatchAgent ──────────────────────────────────────────────

    def _build_system(self) -> str:
        return prompts.render_system(heuristicas=self._heuristicas)

    def _build_user(self, batch: pd.DataFrame) -> str:
        bloques: list[str] = []
        for i, (_, row) in enumerate(batch.iterrows()):
            operatoria = str(row.get("operatoria", "cita"))
            bloques.append(
                f"UNIDAD [{i}] ({operatoria}):\n"
                f"POST CITADOR (@{row.get('autor', '?')}): {row.get('texto', '')}\n"
                f"POST CITADO (@{row.get('autor_citado', '?')}): "
                f"{row.get('texto_citado', '(no capturado)')}"
            )
        return prompts.render_user(unidades_block="\n\n".join(bloques))

    def _map_item_to_columns(
        self,
        item: ReframingBatchItemSchema,
        row: pd.Series,
    ) -> dict[str, Any]:
        return {
            "reframing": json.dumps(
                item.reframing.model_dump(), ensure_ascii=False
            )
        }
