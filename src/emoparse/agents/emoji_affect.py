# ══════════════════════════════════════════════════════════════════════════════
#  emoparse.agents.emoji_affect
#
#  Desambiguación en contexto de la contribución afectiva de emojis.
#
#  Solo recibe los usos que el léxico (knowledge/emoji_afecto.json) marca
#  como ambiguos o no cubre: los inequívocos se resuelven sin LLM en la
#  stage. Cada fila: `emoji`, `frase` (texto completo de la unidad) y el
#  `prior` del léxico si existe. El output agrega la columna `afecto` (JSON).
# ══════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

import pandas as pd

from emoparse.agents.base import BaseBatchAgent
from emoparse.core.backend.base import LLMBackend
from emoparse.core.prompts import emoji_affect as prompts
from emoparse.core.schemas import (
    EmojiAfectoBatchItemSchema,
    ListaEmojiAfectoBatchSchema,
)

if TYPE_CHECKING:
    from emoparse.genres.base import Genre


class EmojiAffectAgent(BaseBatchAgent[ListaEmojiAfectoBatchSchema]):
    """Resuelve la contribución afectiva de emojis ambiguos en contexto."""

    NAME = "emoji_affect"
    SCHEMA = ListaEmojiAfectoBatchSchema
    OUTPUT_COLUMNS = ("afecto",)
    BATCH_SIZE = 12

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
            heuristicas: Reglas heurísticas de desambiguación. Si None, no
                se inyectan en el system prompt.
            retry_config: Política de reintentos ante errores transitorios.
            genre: Configuración opcional de género discursivo. Puede
                ajustar BATCH_SIZE vía `batch_size['emoji_affect']`.
        """
        self._heuristicas = heuristicas
        self._genre = genre

        if genre is not None and "emoji_affect" in genre.batch_size:
            self.BATCH_SIZE = genre.batch_size["emoji_affect"]  # type: ignore[misc]

        super().__init__(backend, retry_config=retry_config)

    # ── Hooks de BaseBatchAgent ──────────────────────────────────────────────

    def _build_system(self) -> str:
        return prompts.render_system(heuristicas=self._heuristicas)

    def _build_user(self, batch: pd.DataFrame) -> str:
        bloques: list[str] = []
        for i, (_, row) in enumerate(batch.iterrows()):
            prior = str(row.get("prior") or "").strip()
            linea_prior = f"\nPRIOR DEL LÉXICO: {prior}" if prior else ""
            bloques.append(
                f"UNIDAD [{i}]:\n"
                f"EMOJI: {row.get('emoji', '')}\n"
                f"POST: {row.get('frase', '')}{linea_prior}"
            )
        return prompts.render_user(unidades_block="\n\n".join(bloques))

    def _map_item_to_columns(
        self,
        item: EmojiAfectoBatchItemSchema,
        row: pd.Series,
    ) -> dict[str, Any]:
        return {
            "afecto": json.dumps(item.afecto.model_dump(), ensure_ascii=False)
        }
