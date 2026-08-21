# ══════════════════════════════════════════════════════════════════════════════
#  emoparse.agents.modalidad
# ══════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

import json
import math
from typing import Any

import pandas as pd

from emoparse.agents.base import BaseAgent
from emoparse.core.backend.base import LLMBackend
from emoparse.core.backend.exceptions import BackendError
from emoparse.core.backend.retry import RetryConfig, retry_with_backoff
from emoparse.core.prompts import modalidad as prompts
from emoparse.core.schemas import ModalidadRecoverySchema, ModalidadSchema
from emoparse.genres.base import Genre


def _estimate_tokens(text: str) -> int:
    """Misma cota conservadora del pipeline, mantenida local para evitar acoplamiento."""
    return math.ceil(len(text) / 3) if text else 0


class ModalidadAgent(BaseAgent[ModalidadSchema]):
    """Clasifica un lote pequeño de aristas marca→referente."""

    NAME = "modalidad"
    SCHEMA = ModalidadSchema
    OUTPUT_COLUMNS = ("modalidad",)
    MAX_TOKENS = 1024
    CONTROL_TOKEN_MARGIN = 64

    def __init__(
        self,
        backend: LLMBackend,
        resumen: str = "",
        heuristicas: str = "",
        retry_config: RetryConfig | None = None,
        genre: Genre | None = None,
    ) -> None:
        self._resumen = resumen
        self._heuristicas = heuristicas
        self._genre = genre
        super().__init__(backend, retry_config=retry_config)

    def _build_system(self) -> str:
        return prompts.render_system(heuristicas=self._heuristicas)

    def _build_user(self, row: pd.Series) -> str:
        return prompts.render_user(
            codigo=str(row["codigo"]),
            vinculos=str(row.get("vinculos", "")),
            resumen=self._resumen,
        )

    def estimate_prompt_tokens(self, row: pd.Series) -> int:
        """Cota conservadora del prompt antes de invocar el backend."""
        return (
            _estimate_tokens(self._system)
            + _estimate_tokens(self._build_user(row))
            + self.CONTROL_TOKEN_MARGIN
        )

    def process_unit(self, row: pd.Series) -> ModalidadSchema:
        """Genera con presupuesto de salida local a modalidad."""

        def _call() -> ModalidadSchema:
            response = self._backend.generate(
                system=self._system,
                user=self._build_user(row),
                schema=self.SCHEMA,
                max_tokens=self.MAX_TOKENS,
            )
            if not isinstance(response.parsed, self.SCHEMA):
                raise BackendError(
                    f"Backend devolvió response sin parsed (alias={response.model_alias}, "
                    f"parsed={response.parsed!r})"
                )
            return response.parsed

        if self._retry_config is not None:
            return retry_with_backoff(_call, self._retry_config)
        return _call()

    def process_recovery_unit(self, row: pd.Series) -> ModalidadRecoverySchema:
        """Recupera una arista con un contrato singleton semánticamente estricto."""

        def _call() -> ModalidadRecoverySchema:
            response = self._backend.generate(
                system=self._system,
                user=self._build_user(row),
                schema=ModalidadRecoverySchema,
                max_tokens=self.MAX_TOKENS,
            )
            if not isinstance(response.parsed, ModalidadRecoverySchema):
                raise BackendError(
                    f"Backend devolvió recovery sin parsed (alias={response.model_alias}, "
                    f"parsed={response.parsed!r})"
                )
            return response.parsed

        if self._retry_config is not None:
            return retry_with_backoff(_call, self._retry_config)
        return _call()

    def _map_to_columns(
        self,
        parsed: ModalidadSchema,
        row: pd.Series,
    ) -> dict[str, Any]:
        clasif = [c.model_dump() for c in parsed.clasificaciones]
        return {"modalidad": json.dumps(clasif, ensure_ascii=False)}
