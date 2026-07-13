# ══════════════════════════════════════════════════════════════════════════════
#  emoparse.agents.hashtag_semiotics
#
#  Caracterización semiótica de hashtags a nivel corpus.
#
#  Opera sobre el hashtag como unidad (no sobre el post): cada fila trae un
#  hashtag frecuente y una muestra de sus usos en el corpus, y el agente
#  caracteriza su función dominante (tópico, afiliación-consigna, evaluativo,
#  irónico, campaña), el acoplamiento actitud-tema que realiza y la foria
#  dominante de su entorno. El output agrega la columna `analisis` (JSON).
# ══════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

import pandas as pd

from emoparse.agents.base import BaseBatchAgent
from emoparse.core.backend.base import LLMBackend
from emoparse.core.prompts import hashtag_semiotics as prompts
from emoparse.core.schemas import (
    HashtagBatchItemSchema,
    ListaHashtagsBatchSchema,
)

if TYPE_CHECKING:
    from emoparse.genres.base import Genre


class HashtagSemioticsAgent(BaseBatchAgent[ListaHashtagsBatchSchema]):
    """Caracteriza hashtags frecuentes a partir de muestras de uso."""

    NAME = "hashtag_semiotics"
    SCHEMA = ListaHashtagsBatchSchema
    OUTPUT_COLUMNS = ("analisis",)
    BATCH_SIZE = 4

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
                ajustar BATCH_SIZE vía `batch_size['hashtag_semiotics']`.
        """
        self._heuristicas = heuristicas
        self._genre = genre

        if genre is not None and "hashtag_semiotics" in genre.batch_size:
            self.BATCH_SIZE = genre.batch_size["hashtag_semiotics"]  # type: ignore[misc]

        super().__init__(backend, retry_config=retry_config)

    # ── Hooks de BaseBatchAgent ──────────────────────────────────────────────

    def _build_system(self) -> str:
        return prompts.render_system(heuristicas=self._heuristicas)

    def _build_user(self, batch: pd.DataFrame) -> str:
        bloques: list[str] = []
        for i, (_, row) in enumerate(batch.iterrows()):
            bloques.append(
                f"UNIDAD [{i}]:\n"
                f"HASHTAG: #{row.get('hashtag', '')} "
                f"({row.get('n_usos', '?')} usos en el corpus)\n"
                f"MUESTRA DE USOS:\n{row.get('muestras', '')}"
            )
        return prompts.render_user(unidades_block="\n\n".join(bloques))

    def _map_item_to_columns(
        self,
        item: HashtagBatchItemSchema,
        row: pd.Series,
    ) -> dict[str, Any]:
        return {
            "analisis": json.dumps(
                item.analisis.model_dump(), ensure_ascii=False
            )
        }
