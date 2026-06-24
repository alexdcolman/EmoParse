# ══════════════════════════════════════════════════════════════════════════════
#  emoparse.domain.validators.base
#
#  Tipos base para el sistema de validación post-LLM.
#
#  Diseño:
#   - ValidationIssue: valor inmutable que describe una incoherencia detectada.
#     Severidad siempre "warning": validators informativos, no bloquean el pipeline.
#   - RowValidator: valida una fila de la tabla emociones (una emoción caracterizada).
#     Recibe datos de la emoción + contexto del discurso. Devuelve lista de issues.
#   - DiscursoValidator: valida el conjunto completo de emociones de un discurso.
#     Recibe lista de dicts homogéneos. Útil para reglas con visión global.
#
#  Dos ABCs separados:
#   - RowValidators se aplican en loop sobre cada emoción.
#   - DiscursoValidators reciben el conjunto completo.
#
#  Severidad:
#   - Solo "warning" actualmente.
# ══════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Literal


@dataclass(frozen=True, slots=True)
class ValidationIssue:
    """Una incoherencia detectada post-LLM.

    Campos:
        validator_id: Identificador único del validator.
        mensaje: Descripción legible del problema.
        codigo: Código del discurso afectado.
        frase_idx: Índice de la frase (None para issues a nivel discurso).
        emocion_idx: Índice de la emoción en la frase (None idem).
        contexto: Dict con los valores que activaron la regla.
        severidad: Siempre "warning" (informativo, no bloquea pipeline).
    """
    validator_id: str
    mensaje: str
    codigo: str
    frase_idx: int | None
    emocion_idx: int | None
    contexto: dict[str, Any]
    severidad: Literal["warning"] = "warning"

    def as_dict(self) -> dict[str, Any]:
        """Serializable a JSON / SQLite. Contexto se guarda como-dict."""
        return {
            "validator_id": self.validator_id,
            "mensaje": self.mensaje,
            "codigo": self.codigo,
            "frase_idx": self.frase_idx,
            "emocion_idx": self.emocion_idx,
            "contexto": self.contexto,
            "severidad": self.severidad,
        }


class RowValidator(ABC):
    """Validator que opera sobre UNA emoción caracterizada.

    La fila incluye tanto los campos de detección (de `emociones`)
    como los de caracterización (de `caracterizacion_payload`).
    """

    #: Identificador único. Aparece en `ValidationIssue.validator_id`.
    VALIDATOR_ID: str

    @abstractmethod
    def validate(
        self,
        *,
        codigo: str,
        frase_idx: int,
        emocion_idx: int,
        # Campos de detección (tabla emociones):
        experienciador: str,
        experienciador_marca: str,
        tipo_emocion: str,
        modo_existencia: str,
        fuente_marca: str,
        fuente_inferencia: str,
        # Campos de caracterización (de caracterizacion_payload):
        foria: str,
        dominancia: str,
        intensidad: str,
        # Contexto del discurso (de discursos):
        enunciador: str,
        enunciatarios: list[dict[str, Any]],
    ) -> list[ValidationIssue]:
        """Evalúa la emoción. Devuelve lista de issues (vacía = ok)."""


class DiscursoValidator(ABC):
    """Validator que opera sobre TODAS las emociones de un discurso."""

    VALIDATOR_ID: str

    @abstractmethod
    def validate(
        self,
        *,
        codigo: str,
        emociones: list[dict[str, Any]],
        enunciador: str,
        enunciatarios: list[dict[str, Any]],
    ) -> list[ValidationIssue]:
        """Evalúa el discurso completo. Devuelve lista de issues."""
