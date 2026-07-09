# ══════════════════════════════════════════════════════════════════════════════
#  emoparse.agents.modalidad
#
#  Agente de clasificación de modalidad referencial: para cada vínculo
#  marca→referente (ambiguo para el pre-pass NLP), decide la modalidad
#  (designación / referencia gramatical / identificación inferencial) y la
#  naturaleza del referente. Procesa un discurso por llamada (lote de vínculos).
# ══════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

import json
from typing import Any

import pandas as pd

from emoparse.agents.base import BaseAgent
from emoparse.core.backend.base import LLMBackend
from emoparse.core.prompts import modalidad as prompts
from emoparse.core.schemas import ModalidadSchema
from emoparse.genres.base import Genre


class ModalidadAgent(BaseAgent[ModalidadSchema]):
    """Clasifica la modalidad referencial de un lote de vínculos de un discurso."""

    NAME = "modalidad"
    SCHEMA = ModalidadSchema
    OUTPUT_COLUMNS = ("modalidad",)

    def __init__(
        self,
        backend: LLMBackend,
        resumen: str = "",
        retry_config: Any | None = None,
        genre: Genre | None = None,
    ) -> None:
        """
        Args:
            backend: Backend LLM para generación estructurada.
            resumen: Resumen del discurso, inyectado como contexto.
            retry_config: Política de reintentos ante errores transitorios.
            genre: Configuración opcional de género discursivo.
        """
        self._resumen = resumen
        self._genre = genre
        super().__init__(backend, retry_config=retry_config)

    # ── Hooks de BaseAgent ───────────────────────────────────────────────────

    def _build_system(self) -> str:
        return prompts.render_system()

    def _build_user(self, row: pd.Series) -> str:
        return prompts.render_user(
            codigo=str(row["codigo"]),
            vinculos=str(row.get("vinculos", "")),
            resumen=self._resumen,
        )

    def _map_to_columns(
        self,
        parsed: ModalidadSchema,
        row: pd.Series,
    ) -> dict[str, Any]:
        clasif = [c.model_dump() for c in parsed.clasificaciones]
        return {"modalidad": json.dumps(clasif, ensure_ascii=False)}
