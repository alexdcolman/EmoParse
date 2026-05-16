# ══════════════════════════════════════════════════════════════════════════════
#  emoparse.agents.normalize_actors
#
#  Batch agent para entity linking de actores contra una KB conocida.
# ══════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

import pandas as pd

from emoparse.agents.base import BaseBatchAgent
from emoparse.core.backend.base import LLMBackend
from emoparse.core.prompts import normalize_actors as prompts
from emoparse.core.schemas import (
    ActorLinkingBatchItemSchema,
    ListaActorLinkingBatchSchema,
)

if TYPE_CHECKING:
    from emoparse.genres.base import Genre


class NormalizeActorsAgent(BaseBatchAgent[ListaActorLinkingBatchSchema]):
    """Linkea menciones de actores contra una KB de actores conocidos.

    Para cada unidad, recibe la lista de actores ya detectados por
    `ActorsAgent` y devuelve, para cada uno, su `canonical_id` de la KB
    (o `null` con `es_nuevo=true` si no matchea).
    """

    NAME = "normalize_actors"
    SCHEMA = ListaActorLinkingBatchSchema
    OUTPUT_COLUMNS = ("actores_canonicos",)
    BATCH_SIZE = 10

    def __init__(
        self,
        backend: LLMBackend,
        actors_kb_serialized: str,
        retry_config: Any | None = None,
        genre: "Genre | None" = None,
    ) -> None:
        """
        Args:
            backend: Backend LLM utilizado para inferencia.
            actors_kb_serialized: KB serializada como string (formato
                compacto `canonical_id: aliases`).
            retry_config: Política de reintentos ante errores transitorios.
            genre: Permite sobrescribir `BATCH_SIZE` si define
                `batch_size["normalize_actors"]`.
        """
        self._kb_serialized = actors_kb_serialized
        self._genre = genre

        if genre is not None and "normalize_actors" in genre.batch_size:
            self.BATCH_SIZE = genre.batch_size["normalize_actors"]  # type: ignore[misc]

        super().__init__(backend, retry_config=retry_config)

    # ── Hooks ────────────────────────────────────────────────────────────────

    def _build_system(self) -> str:
        return prompts.render_system(actors_kb=self._kb_serialized)

    def _build_user(self, batch: pd.DataFrame) -> str:
        bloques: list[str] = []
        for i, (_, row) in enumerate(batch.iterrows()):
            codigo = str(row.get("codigo", ""))
            frase = str(row.get("frase", ""))
            actores_listado = self._format_actores(row.get("actores_a_linkear"))

            bloques.append(
                f"UNIDAD [{i}] (codigo={codigo}):\n"
                f"FRASE: {frase}\n"
                f"ACTORES A LINKEAR:\n{actores_listado}"
            )
        unidades_block = "\n\n".join(bloques)
        return prompts.render_user(unidades_block=unidades_block)

    def _map_item_to_columns(
        self,
        item: ActorLinkingBatchItemSchema,
        row: pd.Series,
    ) -> dict[str, Any]:
        actores_canonicos_json = json.dumps(
            [link.model_dump() for link in item.linkings],
            ensure_ascii=False,
        )
        return {"actores_canonicos": actores_canonicos_json}

    # ── Helpers ──────────────────────────────────────────────────────────────

    @staticmethod
    def _format_actores(raw: Any) -> str:
        """Convierte la lista de actores a un listado numerado legible."""
        if raw is None or (isinstance(raw, float) and pd.isna(raw)):
            return "  (sin actores)"
        if isinstance(raw, str):
            try:
                parsed = json.loads(raw)
            except json.JSONDecodeError:
                return f"  (error de parseo: {raw[:60]})"
        else:
            parsed = raw

        if not isinstance(parsed, list) or not parsed:
            return "  (sin actores)"

        lines: list[str] = []
        for idx, a in enumerate(parsed):
            if isinstance(a, dict):
                nombre = a.get("actor", "?")
                tipo = a.get("tipo", "?")
                lines.append(f"  [{idx}] {nombre} (tipo={tipo})")
        return "\n".join(lines) if lines else "  (sin actores)"
