"""Validators de coherencia semiótica post-LLM para EmoParse."""

from emoparse.domain.validators.base import (
    DiscursoValidator,
    RowValidator,
    ValidationIssue,
)
from emoparse.domain.validators.rules import (
    DISCURSO_VALIDATORS,
    ROW_VALIDATORS,
    V01_ModoPotencialVirtualExperienciador,
    V02_FuenteNoIdentificadaConIntensidadAlta,
    V04_AforicoConIntensidadAlta,
    V05_AmbiforicaConIntensidadBaja,
    V06_VirtualConForiaAforica,
    V07_TipoFuenteActorSinFuenteNombrada,
    V08_ActorCoincideConEnunciador,
    V09_EmocionDuplicadaMismoActorMismaFrase,
    V10_ModoPotencialConExperienciadorNoEnunciatario,
)
from emoparse.domain.validators.runner import ValidationRunner

__all__ = [
    "ValidationIssue",
    "RowValidator",
    "DiscursoValidator",
    "ROW_VALIDATORS",
    "DISCURSO_VALIDATORS",
    "V01_ModoPotencialVirtualExperienciador",
    "V02_FuenteNoIdentificadaConIntensidadAlta",
    "V04_AforicoConIntensidadAlta",
    "V05_AmbiforicaConIntensidadBaja",
    "V06_VirtualConForiaAforica",
    "V07_TipoFuenteActorSinFuenteNombrada",
    "V08_ActorCoincideConEnunciador",
    "V09_EmocionDuplicadaMismoActorMismaFrase",
    "V10_ModoPotencialConExperienciadorNoEnunciatario",
    "ValidationRunner",
]
