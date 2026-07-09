# ══════════════════════════════════════════════════════════════════════════════
#  emoparse.agents.judge
#
#  Agente de validación de caracterización emocional.
#
#  Evalúa la coherencia de atributos previamente asignados a una emoción
#  individual (foria, dominancia, intensidad y fuente).
# ══════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

from typing import Any

import pandas as pd

from emoparse.agents.base import BaseBatchAgent
from emoparse.core.backend.base import LLMBackend
from emoparse.core.prompts import judge as prompts
from emoparse.core.schemas import (
    JuicioBatchItemSchema,
    ListaJuiciosBatchSchema,
)
from emoparse.genres.base import Genre


class JudgeAgent(BaseBatchAgent[ListaJuiciosBatchSchema]):
    """Agente batch para validación de caracterizaciones emocionales.

    Cada fila representa una emoción ya caracterizada. El agente evalúa si
    la caracterización asignada resulta coherente con el contexto textual y
    con la emoción detectada originalmente.
    """

    NAME = "judge"
    SCHEMA = ListaJuiciosBatchSchema
    OUTPUT_COLUMNS = ("coherente", "issues", "confianza", "sugerencias")
    BATCH_SIZE = 5

    def __init__(
        self,
        backend: LLMBackend,
        titulo: str = "",
        tipo_discurso: str = "",
        heuristicas: str | None = None,
        ontologia: str | None = None,
        resumen: str | None = None,
        enunciacion: str | None = None,
        retry_config: Any | None = None,
        genre: Genre | None = None,
    ) -> None:
        """
        Args:
            backend: Backend LLM utilizado para generación estructurada.
            titulo: Título del discurso, usado como contexto del prompt.
            tipo_discurso: Clasificación o tipo del discurso.
            heuristicas: Reglas heurísticas para evaluación de coherencia.
                Si None, no se inyectan heurísticas en el system prompt.
            ontologia: Ontología de emociones serializada. Si None, el juez no
                recibe las definiciones de emociones (comportamiento previo).
            resumen: Resumen global del discurso, como contexto.
            enunciacion: Bloque preformateado con enunciador, enunciatarios,
                auditorio y colectivos de identificación.
            retry_config: Política de reintentos ante errores transitorios.
            genre: Configuración opcional de género discursivo. Puede
                ajustar parámetros como `BATCH_SIZE`.
        """
        self._titulo = titulo
        self._tipo_discurso = tipo_discurso
        self._heuristicas = heuristicas
        self._ontologia = ontologia
        self._resumen = resumen
        self._enunciacion = enunciacion
        self._genre = genre

        if genre is not None and "judge" in genre.batch_size:
            self.BATCH_SIZE = genre.batch_size["judge"]  # type: ignore[misc]

        super().__init__(backend, retry_config=retry_config)

    # ── Hooks ────────────────────────────────────────────────────────────────

    def _build_system(self) -> str:
        return prompts.render_system(
            titulo=self._titulo,
            tipo_discurso=self._tipo_discurso,
            heuristicas=self._heuristicas,
            ontologia=self._ontologia,
            resumen=self._resumen,
            enunciacion=self._enunciacion,
        )

    def _build_user(self, batch: pd.DataFrame) -> str:
        bloques: list[str] = []
        for i, (_, row) in enumerate(batch.iterrows()):
            codigo = str(row.get("codigo", ""))
            frase = str(row.get("frase", ""))
            prev = str(row.get("ventana_previa", "") or "")
            post = str(row.get("ventana_posterior", "") or "")
            actantes = str(row.get("actantes_texto", "") or "")

            bloque = [
                f"UNIDAD [{i}] (codigo={codigo}):",
            ]
            if prev:
                bloque.append(f"  Contexto previo:\n{prev}")
            bloque.append(f"  FRASE OBJETIVO: {frase}")
            if post:
                bloque.append(f"  Contexto posterior:\n{post}")
            bloque.append(
                "  SIMULACRO A REVISAR:\n"
                f"    Experienciador: {row.get('experienciador', '')}\n"
                f"    Emoción:        {row.get('tipo_emocion', '')}\n"
                f"    Modo:           {row.get('modo_existencia', '')}\n"
                f"    Fuente:         {row.get('fuente_inferencia', '')}\n"
                f"    Temporalidad:   {row.get('temporalidad', '')}"
            )
            if actantes:
                bloque.append(f"  ACTANTES:\n{actantes}")
            bloques.append("\n".join(bloque))
        unidades_block = "\n\n".join(bloques)
        return prompts.render_user(unidades_block=unidades_block)

    def _map_item_to_columns(
        self,
        item: JuicioBatchItemSchema,
        row: pd.Series,
    ) -> dict[str, Any]:
        j = item.juicio
        return {
            "coherente": j.coherente,
            "issues": j.issues,
            "confianza": j.confianza,
            "sugerencias": [s.model_dump() for s in j.sugerencias],
        }
