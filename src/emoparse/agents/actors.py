# ══════════════════════════════════════════════════════════════════════════════
#  emoparse.agents.actors
#
#  Batch agent para identificación de actores en unidades textuales
#  (frases o párrafos) de un discurso.
#
#  Cada fila de entrada representa una unidad textual individual y debe
#  contener al menos el texto y su referencia de discurso. El agente no
#  opera sobre discursos completos sino sobre estas unidades segmentadas.
#
#  El contexto global del discurso (título, tipo y enunciador) se inyecta
#  en el system prompt al instanciar el agente. Por diseño, este contexto
#  debe corresponder a un único discurso por instancia.
#
#  Output:
#  agrega la columna `actores`, con una lista JSON serializada de:
#  {actor, tipo, modo, justificacion}
# ══════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

import json
from typing import Any

import pandas as pd

from emoparse.agents.base import BaseBatchAgent
from emoparse.core.backend.base import LLMBackend
from emoparse.core.prompts import actors as prompts
from emoparse.core.schemas import (
    ActoresBatchItemSchema,
    ListaActoresBatchSchema,
)
from emoparse.genres.base import Genre


class ActorsAgent(BaseBatchAgent[ListaActoresBatchSchema]):
    """Detecta actores en frases o párrafos.

    Agrega la columna `actores` como JSON serializado con una lista de
    actores detectados por unidad textual.

    Sin actores: lista vacía.
    Errores de procesamiento: None.
    """

    NAME = "actors"
    SCHEMA = ListaActoresBatchSchema
    OUTPUT_COLUMNS = ("actores",)
    BATCH_SIZE = 5

    def __init__(
        self,
        backend: LLMBackend,
        titulo: str = "",
        tipo_discurso: str = "",
        enunciador: str = "",
        retry_config: Any | None = None,
        genre: Genre | None = None,
    ) -> None:
        """Inicializa el agente.

        Args:
            backend: Backend LLM utilizado para inferencia.
            titulo: Contexto global del discurso.
            tipo_discurso: Tipo o género del discurso.
            enunciador: Orador principal del discurso.
            retry_config: Configuración de reintentos.
            genre: Permite sobrescribir `BATCH_SIZE` si define
                `batch_size["actors"]`.
        """
        self._titulo = titulo
        self._tipo_discurso = tipo_discurso
        self._enunciador = enunciador
        self._genre = genre

        # Permite override de batch size desde el género.
        if genre is not None and "actors" in genre.batch_size:
            self.BATCH_SIZE = genre.batch_size["actors"]  # type: ignore[misc]

        super().__init__(backend, retry_config=retry_config)

    # ── Hooks de BaseBatchAgent ──────────────────────────────────────────────

    def _build_system(self) -> str:
        return prompts.render_system(
            titulo=self._titulo,
            tipo_discurso=self._tipo_discurso,
            enunciador=self._enunciador,
        )

    def _build_user(self, batch: pd.DataFrame) -> str:
        # `unit_idx` permite correlacionar cada respuesta del modelo
        # con su fila original dentro del batch.
        bloques: list[str] = []
        for i, (_, row) in enumerate(batch.iterrows()):
            codigo = str(row.get("codigo", ""))
            frase = str(row.get("frase", row.get("contenido", "")))
            bloques.append(f"UNIDAD [{i}] (codigo={codigo}):\n{frase}")
        unidades_block = "\n\n".join(bloques)
        return prompts.render_user(unidades_block=unidades_block)

    def _map_item_to_columns(
        self,
        item: ActoresBatchItemSchema,
        row: pd.Series,
    ) -> dict[str, Any]:
        actores_json = json.dumps(
            [a.model_dump() for a in item.actores],
            ensure_ascii=False,
        )
        return {"actores": actores_json}
