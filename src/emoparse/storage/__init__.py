"""Capa de persistencia SQLite por run.

Expone repositorios y modelos principales.
"""

from emoparse.storage.db import Database
from emoparse.storage.discursos import DiscursoStage, DiscursosRepository
from emoparse.storage.emociones import EmocionesRepository
from emoparse.storage.frases import FraseStage, FrasesRepository
from emoparse.storage.judgments import JudgmentsRepository
from emoparse.storage.metrics import (
    MetricsRepository,
    StageMetricsAccumulator,
    StageMetricsSnapshot,
)
from emoparse.storage.models import RunContext, Versions
from emoparse.storage.runs import RunsRepository

#: API pública del storage.
__all__ = [
    "Database",
    "RunContext",
    "Versions",
    "RunsRepository",
    "DiscursosRepository",
    "DiscursoStage",
    "FrasesRepository",
    "FraseStage",
    "EmocionesRepository",
    "JudgmentsRepository",
    "MetricsRepository",
    "StageMetricsAccumulator",
    "StageMetricsSnapshot",
]
