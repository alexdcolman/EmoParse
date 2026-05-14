"""Orquestador del pipeline EmoParse."""

from emoparse.pipeline.chunking import split_into_sentences
from emoparse.pipeline.dag import EMOPARSE_DAG, StageDAG, StageNode
from emoparse.pipeline.runner import DEFAULT_ENABLED_STAGES, STAGE_ORDER, PipelineRunner
from emoparse.pipeline.stages import (
    ActorsStage,
    CharacterizerStage,
    EmotionsPass2Stage,
    EmotionsStage,
    EnunciationStage,
    ExplodeEmocionesStage,
    JudgeStage,
    MetadataStage,
    Stage,
    SummarizerStage,
)

#: API pública del pipeline.
__all__ = [
    "PipelineRunner",
    "STAGE_ORDER",
    "DEFAULT_ENABLED_STAGES",
    "EMOPARSE_DAG",
    "StageDAG",
    "StageNode",
    "split_into_sentences",
    "Stage",
    "SummarizerStage",
    "MetadataStage",
    "EnunciationStage",
    "ActorsStage",
    "EmotionsStage",
    "EmotionsPass2Stage",
    "ExplodeEmocionesStage",
    "CharacterizerStage",
    "JudgeStage",
]
