# ══════════════════════════════════════════════════════════════════════════════
# emoparse.agents.normalize_experiencers
#
# Agente que propone equivalencias de experienciador, un discurso por unidad.
# ══════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

import pandas as pd

from emoparse.agents.base import BaseBatchAgent
from emoparse.core.backend.base import LLMBackend
from emoparse.core.backend.retry import RetryConfig
from emoparse.core.prompts import normalize_experiencers as prompts
from emoparse.core.schemas import (
    ExperiencerEquivalenceBatchItemSchema,
    ListaExperiencerEquivalenceBatchSchema,
)

if TYPE_CHECKING:
    from emoparse.genres.base import Genre


class NormalizeExperiencersAgent(
    BaseBatchAgent[ListaExperiencerEquivalenceBatchSchema]
):
    """Propone equivalencias de experienciador, un discurso por unidad.

    Cada fila de entrada es un discurso con: `codigo`, `enunciador`,
    `enunciatarios`, `actores` (contexto) y `experienciadores` (lista JSON de
    los crudos a resolver, con su frecuencia). Devuelve la columna
    `equivalencias` (lista JSON de propuestas).
    """

    NAME = "normalize_experiencers"
    SCHEMA = ListaExperiencerEquivalenceBatchSchema
    OUTPUT_COLUMNS = ("equivalencias",)
    BATCH_SIZE = 1

    def __init__(
        self,
        backend: LLMBackend,
        retry_config: RetryConfig | None = None,
        genre: "Genre | None" = None,
    ) -> None:
        self._genre = genre
        if genre is not None and "normalize_experiencers" in genre.batch_size:
            self.BATCH_SIZE = genre.batch_size["normalize_experiencers"]  # type: ignore[misc]
        super().__init__(backend, retry_config=retry_config)

    # ── Hooks ──────────────────────────────────────────────────────────────────

    def _build_system(self) -> str:
        return prompts.render_system()

    def _build_user(self, batch: pd.DataFrame) -> str:
        bloques: list[str] = []
        for i, (_, row) in enumerate(batch.iterrows()):
            codigo = str(row.get("codigo", ""))
            enunciador = str(row.get("enunciador", "") or "(no identificado)")
            enunciatarios = str(row.get("enunciatarios", "") or "(no identificados)")
            actores = str(row.get("actores", "") or "(ninguno)")
            exps = self._format_experiencers(row.get("experienciadores"))
            bloques.append(
                f"DISCURSO [{i}] (codigo={codigo}):\n"
                f"ENUNCIADOR: {enunciador}\n"
                f"ENUNCIATARIOS: {enunciatarios}\n"
                f"ACTORES MENCIONADOS: {actores}\n"
                f"EXPERIENCIADORES A NORMALIZAR:\n{exps}"
            )
        unidades_block = "\n\n".join(bloques)
        return prompts.render_user(unidades_block=unidades_block)

    def _map_item_to_columns(
        self,
        item: ExperiencerEquivalenceBatchItemSchema,
        row: pd.Series,
    ) -> dict[str, Any]:
        equivalencias_json = json.dumps(
            [e.model_dump() for e in item.equivalencias],
            ensure_ascii=False,
        )
        return {"equivalencias": equivalencias_json}

    # ── Helpers ──────────────────────────────────────────────────────────────

    @staticmethod
    def _format_experiencers(raw: Any) -> str:
        """Lista numerada de experienciadores crudos con su frecuencia."""
        if isinstance(raw, str):
            try:
                parsed = json.loads(raw)
            except (json.JSONDecodeError, TypeError):
                return "  (ninguno)"
        else:
            parsed = raw
        if not isinstance(parsed, list) or not parsed:
            return "  (ninguno)"
        lines: list[str] = []
        for idx, e in enumerate(parsed):
            if isinstance(e, dict):
                nombre = str(e.get("raw", "")).strip()
                n = e.get("ocurrencias")
                suf = f" (x{n})" if n else ""
                if nombre:
                    lines.append(f"  [{idx}] {nombre}{suf}")
        return "\n".join(lines) if lines else "  (ninguno)"
