# ══════════════════════════════════════════════════════════════════════════════
#  emoparse.agents.characterizer
#
#  Agente batch para caracterización de emociones detectadas.
#
#  Cada fila de entrada representa una emoción individual ya extraída
#  desde una frase del discurso, con su contexto y atributos previos
#  (por ejemplo: experienciador, tipo_emocion, modo_existencia).
#
#  El agente agrega atributos de caracterización:
#  - foria
#  - dominancia
#  - intensidad
#  - fuente
#
#  junto con sus justificaciones y metadatos asociados.
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
    """Agente batch que caracteriza emociones individuales.

    Cada fila de entrada representa una emoción previamente detectada en una
    frase del discurso. El agente enriquece esa fila con atributos de
    caracterización como foria, dominancia, intensidad y fuente, junto con
    sus justificaciones correspondientes.
    """

    NAME = "characterizer"
    SCHEMA = ListaCaracterizacionBatchSchema
    OUTPUT_COLUMNS = (
        "foria",
        "foria_justificacion",
        "dominancia",
        "dominancia_justificacion",
        "intensidad",
        "intensidad_justificacion",
        "fuente",
        "tipo_fuente",
        "fuente_justificacion",
    )
    BATCH_SIZE = 5

    def __init__(
        self,
        backend: LLMBackend,
        titulo: str = "",
        tipo_discurso: str = "",
        retry_config: Any | None = None,
        genre: Genre | None = None,
    ) -> None:
        """
        Args:
            backend: Backend LLM utilizado para la generación estructurada.
            titulo: Título del discurso, usado como contexto para el prompt.
            tipo_discurso: Clasificación o tipo del discurso, usado como
                contexto.
            retry_config: Política de reintentos ante errores transitorios
                del backend.
            genre: Configuración opcional de género discursivo. Puede
                sobrescribir parámetros como `BATCH_SIZE`.
        """

        self._titulo = titulo
        self._tipo_discurso = tipo_discurso
        self._genre = genre

        if genre is not None and "characterizer" in genre.batch_size:
            self.BATCH_SIZE = genre.batch_size["characterizer"]  # type: ignore[misc]

        super().__init__(backend, retry_config=retry_config)

    # ── Hooks ────────────────────────────────────────────────────────────────

    def _build_system(self) -> str:
        return prompts.render_system(
            titulo=self._titulo,
            tipo_discurso=self._tipo_discurso,
        )

    def _build_user(self, batch: pd.DataFrame) -> str:
        bloques: list[str] = []
        for i, (_, row) in enumerate(batch.iterrows()):
            codigo = str(row.get("codigo", ""))
            frase = str(row.get("frase", ""))
            experienciador = str(row.get("experienciador", ""))
            tipo_emocion = str(row.get("tipo_emocion", ""))
            modo = str(row.get("modo_existencia", ""))

            bloques.append(
                f"EMOCIÓN [{i}] (codigo={codigo}):\n"
                f"  Experienciador:  {experienciador}\n"
                f"  Tipo emoción:    {tipo_emocion}\n"
                f"  Modo existencia: {modo}\n"
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
            "fuente": c.fuente,
            "tipo_fuente": c.tipo_fuente,
            "fuente_justificacion": c.fuente_justificacion,
        }
