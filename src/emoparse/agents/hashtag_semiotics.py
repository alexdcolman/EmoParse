# ══════════════════════════════════════════════════════════════════════════════
#  emoparse.agents.hashtag_semiotics
#
#  Análisis semiótico de hashtags por uso.
#
#  Un hashtag no funciona siempre igual: su función varía post a post. El
#  agente opera sobre los usos de UN hashtag por corrida: cada fila del batch
#  es un post donde el hashtag aparece, y el agente caracteriza su función,
#  acoplamiento y foria en ese post concreto. Las funciones ya identificadas
#  para el hashtag entran como contexto creciente (vía la stage), con
#  posibilidad de proponer etiquetas nuevas. La caracterización a nivel
#  corpus (tabla `hashtags`) se deriva por agregación de los usos, sin un
#  segundo pase LLM. El output agrega la columna `analisis` (JSON).
# ══════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

import pandas as pd

from emoparse.agents.base import BaseBatchAgent
from emoparse.core.backend.base import LLMBackend
from emoparse.core.prompts import hashtag_semiotics as prompts
from emoparse.core.schemas import (
    HashtagUsoBatchItemSchema,
    ListaHashtagUsosBatchSchema,
)

if TYPE_CHECKING:
    from emoparse.genres.base import Genre


class HashtagSemioticsAgent(BaseBatchAgent[ListaHashtagUsosBatchSchema]):
    """Caracteriza el funcionamiento de un hashtag en cada uno de sus usos."""

    NAME = "hashtag_semiotics"
    SCHEMA = ListaHashtagUsosBatchSchema
    OUTPUT_COLUMNS = ("analisis",)
    BATCH_SIZE = 6

    def __init__(
        self,
        backend: LLMBackend,
        heuristicas: str | None = None,
        retry_config: Any | None = None,
        genre: Genre | None = None,
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
        # El batch trae usos de UN solo hashtag: cabecera y contexto de
        # funciones previas se toman de la primera fila.
        head = batch.iloc[0]
        bloques: list[str] = []
        for i, (_, row) in enumerate(batch.iterrows()):
            bloques.append(f"UNIDAD [{i}]:\nPOST: {row.get('uso_texto', '')}")
        funciones = str(head.get("funciones_previas", "") or "").strip()
        return prompts.render_user(
            hashtag=str(head.get("hashtag", "")),
            n_usos=int(head.get("n_usos", 0) or 0),
            unidades_block="\n\n".join(bloques),
            funciones_previas=funciones or None,
        )

    def _map_item_to_columns(
        self,
        item: HashtagUsoBatchItemSchema,
        row: pd.Series,
    ) -> dict[str, Any]:
        return {"analisis": json.dumps(item.analisis.model_dump(), ensure_ascii=False)}
