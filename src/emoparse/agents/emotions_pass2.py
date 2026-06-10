# ══════════════════════════════════════════════════════════════════════════════
#  emoparse.agents.emotions_pass2
#
#  Segundo pase de detección de emociones con contexto previo.
#
#  El output mantiene el mismo schema estructural que el pase 1
#  (ListaEmocionesBatchSchema), permitiendo que ambos resultados sean
#  consumidos de forma intercambiable según el flujo downstream.
# ══════════════════════════════════════════════════════════════════════════════
 
from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any, Literal

import pandas as pd

from emoparse.agents.base import BaseBatchAgent
from emoparse.agents.emotions import alcance_text
from emoparse.core.backend.base import LLMBackend
from emoparse.core.prompts import emotions_pass2 as prompts
from emoparse.core.schemas import (
    EmocionesBatchItemSchema,
    ListaEmocionesBatchSchema,
)
from emoparse.core.backend.retry import RetryConfig

if TYPE_CHECKING:
    from emoparse.genres.base import Genre


class EmotionsAgentPass2(BaseBatchAgent[ListaEmocionesBatchSchema]):
    """Segundo pase de análisis de emociones con contexto previo.

    Espera un DataFrame similar al del primer pase, pero con la columna
    adicional `emotion_rolling`, que resume en texto las frases anteriores
    del mismo discurso (referencia auxiliar para desambiguar, no evidencia).

    `emotion_scope` restringe qué experienciadores se analizan, con la misma
    semántica que en el pase 1. Pasar el mismo alcance a ambos pases mantiene
    el filtro coherente de punta a punta: el explode prioriza el pase 2, así
    que si el pase 1 se acota pero el pase 2 no, el alcance se perdería.

    Args:
        context_mode: `"rolling"` usa una ventana deslizante de frases
            recientes; `"full"` usa todo el historial previo del discurso.
    """

    NAME = "emotions_pass2"
    SCHEMA = ListaEmocionesBatchSchema
    OUTPUT_COLUMNS = ("emociones",)
    BATCH_SIZE = 3

    def __init__(
        self,
        backend: LLMBackend,
        ontologia: str,
        heuristicas: str,
        configuraciones: str = "",
        titulo: str = "",
        tipo_discurso: str = "",
        enunciador: str = "",
        enunciatarios: str = "",
        emotion_scope: tuple[str, ...] | None = None,
        context_mode: Literal["rolling", "full"] = "rolling",
        retry_config: RetryConfig | None = None,
        genre: "Genre | None" = None,
    ) -> None:
        """
        Args:
            backend: Backend LLM utilizado para generación estructurada.
            ontologia: Ontología emocional utilizada por el prompt.
            heuristicas: Reglas heurísticas de interpretación emocional.
            configuraciones: Texto formateado con las 8 configuraciones del
                simulacro emocional (TIPO_CONF). Si es string vacío, el
                template lo renderiza como bloque sin contenido.
            titulo: Título del discurso.
            tipo_discurso: Tipo o clasificación del discurso.
            enunciador: Sujeto principal de enunciación del discurso.
            enunciatarios: Destinatarios o audiencias del discurso.
            emotion_scope: Restricción de experienciadores a analizar. Si se
                pasa, el prompt enfatiza que solo se consideren emociones
                relacionadas con esos actores específicos. Si no se pasa, se
                analizan emociones de cualquier experienciador presente.
            context_mode: Estrategia de construcción del contexto previo
                (`"rolling"` o `"full"`).
            retry_config: Política de reintentos ante errores transitorios.
            genre: Configuración opcional de género discursivo. Puede
                ajustar parámetros como `BATCH_SIZE`.
        """
        self._ontologia = ontologia
        self._heuristicas = heuristicas
        self._configuraciones = configuraciones
        self._titulo = titulo
        self._tipo_discurso = tipo_discurso
        self._enunciador = enunciador
        self._enunciatarios = enunciatarios
        self._emotion_scope = tuple(emotion_scope) if emotion_scope else ()
        self._context_mode = context_mode
        self._genre = genre

        if genre is not None:
            if "emotions_pass2" in genre.batch_size:
                self.BATCH_SIZE = genre.batch_size["emotions_pass2"]  # type: ignore[misc]
            elif "emotions" in genre.batch_size:
                self.BATCH_SIZE = genre.batch_size["emotions"]  # type: ignore[misc]

        super().__init__(
            backend,
            retry_config=retry_config,
        )

    # ── Hooks de BaseBatchAgent ──────────────────────────────────────────────

    def _build_system(self) -> str:
        return prompts.render_system(
            ontologia=self._ontologia,
            heuristicas=self._heuristicas,
            configuraciones=self._configuraciones,
            titulo=self._titulo,
            tipo_discurso=self._tipo_discurso,
            enunciador=self._enunciador,
            enunciatarios=self._enunciatarios,
            alcance=alcance_text(
                self._emotion_scope, self._enunciador, self._enunciatarios
            ),
        )

    def _build_user(self, batch: pd.DataFrame) -> str:
        bloques: list[str] = []
        for i, (_, row) in enumerate(batch.iterrows()):
            codigo = str(row.get("codigo", ""))
            frase = str(row.get("frase", row.get("contenido", "")))
            actores_str = self._format_actores(row.get("actores"))
            rolling = str(row.get("emotion_rolling", "")).strip()
            if not rolling:
                rolling = "(sin emociones previas)"

            bloques.append(
                f"UNIDAD [{i}] (codigo={codigo}):\n"
                f"FRASE: {frase}\n"
                f"ACTORES IDENTIFICADOS: {actores_str}\n"
                f"EMOCIONES EN FRASES PREVIAS "
                f"(referencia auxiliar, NO evidencia de esta frase):\n{rolling}"
            )
        unidades_block = "\n\n".join(bloques)
        return prompts.render_user(unidades_block=unidades_block)

    def _map_item_to_columns(
        self,
        item: EmocionesBatchItemSchema,
        row: pd.Series,
    ) -> dict[str, Any]:
        emociones_json = json.dumps(
            [e.model_dump() for e in item.emociones],
            ensure_ascii=False,
        )
        return {"emociones": emociones_json}

    # ── Helpers ──────────────────────────────────────────────────────────────

    @staticmethod
    def _format_actores(actores_raw: Any) -> str:
        """Convierte la representación de actores a texto legible.

        Acepta JSON serializado, listas ya parseadas o valores nulos, y
        devuelve una representación compacta adecuada para el prompt.

        Nota de mantenimiento:
            La lógica está duplicada respecto de `EmotionsAgent` (pase 1).
            Si otro agente requiere el mismo helper, puede evaluarse su
            extracción a un módulo compartido para evitar divergencias.
        """
        if actores_raw is None or (isinstance(actores_raw, float) and pd.isna(actores_raw)):
            return "(no procesados)"
        if isinstance(actores_raw, str):
            try:
                parsed = json.loads(actores_raw)
            except json.JSONDecodeError:
                return f"(error de parseo: {actores_raw[:60]})"
        else:
            parsed = actores_raw

        if not isinstance(parsed, list) or not parsed:
            return "(ninguno identificado)"

        formatted = []
        for a in parsed:
            if isinstance(a, dict):
                nombre = a.get("actor", "?")
                tipo = a.get("tipo", "?")
                formatted.append(f"{nombre} ({tipo})")
        return "; ".join(formatted) if formatted else "(ninguno)"
