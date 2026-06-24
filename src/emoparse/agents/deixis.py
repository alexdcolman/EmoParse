# ══════════════════════════════════════════════════════════════════════════════
#  emoparse.agents.deixis
#
#  Agente de resolución de deixis: asigna marcas deícticas (1ª/2ª persona) a los
#  referentes concretos del discurso (enunciador, auditorio, colectivo de
#  identificación). La asignación puede ser múltiple.
# ══════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

import json
from typing import Any

import pandas as pd

from emoparse.agents.base import BaseAgent
from emoparse.core.backend.base import LLMBackend
from emoparse.core.prompts import deixis as prompts
from emoparse.core.schemas import DeixisSchema
from emoparse.genres.base import Genre


class DeixisAgent(BaseAgent[DeixisSchema]):
    """Resuelve las marcas deícticas de un discurso a referentes concretos.

    Procesa un discurso por llamada: recibe sus marcas candidatas y los
    referentes disponibles (enunciador, auditorio, colectivos), y agrega la
    columna `deixis` (JSON con la lista de resoluciones).
    """

    NAME = "deixis"
    SCHEMA = DeixisSchema
    OUTPUT_COLUMNS = ("deixis",)

    def __init__(
        self,
        backend: LLMBackend,
        enunciador: str = "",
        auditorio: tuple[str, ...] = (),
        colectivos: tuple[str, ...] = (),
        resumen: str = "",
        retry_config: Any | None = None,
        genre: Genre | None = None,
    ) -> None:
        """
        Args:
            backend: Backend LLM utilizado para generación estructurada.
            enunciador: Nombre concreto del enunciador del discurso.
            auditorio: Nombres concretos del auditorio directo.
            colectivos: Nombres concretos de los colectivos de identificación.
            resumen: Resumen del discurso, inyectado como contexto.
            retry_config: Política de reintentos ante errores transitorios.
            genre: Configuración opcional de género discursivo.
        """
        self._enunciador = enunciador
        self._auditorio = tuple(auditorio)
        self._colectivos = tuple(colectivos)
        self._resumen = resumen
        self._genre = genre
        super().__init__(backend, retry_config=retry_config)

    # ── Hooks de BaseAgent ───────────────────────────────────────────────────

    def _build_system(self) -> str:
        return prompts.render_system()

    def _build_user(self, row: pd.Series) -> str:
        return prompts.render_user(
            codigo=str(row["codigo"]),
            referentes=self._format_referentes(),
            marcas=str(row.get("marcas", "")),
            resumen=self._resumen,
        )

    def _map_to_columns(
        self,
        parsed: DeixisSchema,
        row: pd.Series,
    ) -> dict[str, Any]:
        resoluciones = [r.model_dump() for r in parsed.resoluciones]
        return {"deixis": json.dumps(resoluciones, ensure_ascii=False)}

    # ── Helpers ──────────────────────────────────────────────────────────────

    def _format_referentes(self) -> str:
        """Lista los referentes disponibles, agrupados por tipo."""
        lines: list[str] = []
        if self._enunciador:
            lines.append(f"- enunciador: {self._enunciador}")
        for a in self._auditorio:
            lines.append(f"- auditorio: {a}")
        for c in self._colectivos:
            lines.append(f"- colectivo_identificacion: {c}")
        return "\n".join(lines) if lines else "- (sin referentes identificados)"
