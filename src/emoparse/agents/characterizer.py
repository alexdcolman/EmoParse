# ══════════════════════════════════════════════════════════════════════════════
#  emoparse.agents.characterizer
#
#  Agente batch para caracterización de emociones detectadas.
# ══════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

from typing import Any

import pandas as pd

from emoparse.agents.base import BaseBatchAgent
from emoparse.core.backend.base import LLMBackend
from emoparse.core.prompts import characterizer as prompts
from emoparse.core.schemas import (
    CaracterizacionBatchItemSchema,
    ListaCaracterizacionBatchSchema,
)
from emoparse.genres.base import Genre


class CharacterizerAgent(BaseBatchAgent[ListaCaracterizacionBatchSchema]):
    """Agente batch que caracteriza emociones individuales."""

    NAME = "characterizer"
    SCHEMA = ListaCaracterizacionBatchSchema
    OUTPUT_COLUMNS = (
        "foria",
        "foria_justificacion",
        "dominancia",
        "dominancia_justificacion",
        "intensidad",
        "intensidad_justificacion",
        "duracion",
        "duracion_justificacion",
        "tipo_atribucion",
        "tipo_atribucion_justificacion",
    )
    BATCH_SIZE = 5

    def __init__(
        self,
        backend: LLMBackend,
        titulo: str = "",
        tipo_discurso: str = "",
        heuristicas: str | None = None,
        retry_config: Any | None = None,
        genre: Genre | None = None,
    ) -> None:
        """
        Args:
            backend: Backend LLM utilizado para la generación estructurada.
            titulo: Título del discurso, usado como contexto para el prompt.
            tipo_discurso: Clasificación o tipo del discurso, usado como
                contexto.
            heuristicas: Reglas heurísticas para caracterización de emociones.
                Si None, no se inyectan heurísticas en el system prompt.
            retry_config: Política de reintentos ante errores transitorios
                del backend.
            genre: Configuración opcional de género discursivo. Puede
                sobrescribir parámetros como `BATCH_SIZE`.
        """

        self._titulo = titulo
        self._tipo_discurso = tipo_discurso
        self._heuristicas = heuristicas
        self._genre = genre

        if genre is not None and "characterizer" in genre.batch_size:
            self.BATCH_SIZE = genre.batch_size["characterizer"]  # type: ignore[misc]

        super().__init__(backend, retry_config=retry_config)

    # ── Hooks ────────────────────────────────────────────────────────────────

    def _build_system(self) -> str:
        return prompts.render_system(
            titulo=self._titulo,
            tipo_discurso=self._tipo_discurso,
            heuristicas=self._heuristicas,
        )

    def _build_user(self, batch: pd.DataFrame) -> str:
        bloques: list[str] = []
        for i, (_, row) in enumerate(batch.iterrows()):
            codigo = str(row.get("codigo", ""))
            frase = str(row.get("frase", ""))
            experienciador = str(row.get("experienciador", ""))
            tipo_emocion = str(row.get("tipo_emocion", ""))
            modo = str(row.get("modo_existencia", ""))
            fuente_marca = str(row.get("fuente_marca", ""))
            fuente_inferencia = str(row.get("fuente_inferencia", ""))

            bloques.append(
                f"EMOCIÓN [{i}] (codigo={codigo}):\n"
                f"  Experienciador:  {experienciador}\n"
                f"  Tipo emoción:    {tipo_emocion}\n"
                f"  Modo existencia: {modo}\n"
                f"  Fuente marca:    {fuente_marca}\n"
                f"  Fuente inferencia: {fuente_inferencia}\n"
                f"  Frase de origen: {frase}"
            )
        unidades_block = "\n\n".join(bloques)
        return prompts.render_user(unidades_block=unidades_block)

    def _map_item_to_columns(
        self,
        item: CaracterizacionBatchItemSchema,
        row: pd.Series,
    ) -> dict[str, Any]:
        c = item.caracterizacion
        return {
            "foria": c.foria,
            "foria_justificacion": c.foria_justificacion,
            "dominancia": c.dominancia,
            "dominancia_justificacion": c.dominancia_justificacion,
            "intensidad": c.intensidad,
            "intensidad_justificacion": c.intensidad_justificacion,
            "duracion": c.duracion,
            "duracion_justificacion": c.duracion_justificacion,
            "tipo_atribucion": c.tipo_atribucion,
            "tipo_atribucion_justificacion": c.tipo_atribucion_justificacion,
        }
