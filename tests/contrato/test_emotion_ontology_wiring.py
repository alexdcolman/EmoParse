"""Contratos del cableado entre ontología emocional y modos de existencia."""

from __future__ import annotations

import inspect
from pathlib import Path

import pytest

from emoparse.agents.emotions import canonical_emotion
from emoparse.core.prompts import emotions as prompts
from emoparse.genres.tuit import get_genre
from emoparse.knowledge.loader import KnowledgeError, KnowledgeLoader
from emoparse.pipeline.runner import PipelineRunner


def _runner_for_resources(
    knowledge_dir: Path,
    *,
    ontology_filename: str = "emociones_ontologia.json",
) -> PipelineRunner:
    runner = object.__new__(PipelineRunner)
    runner._knowledge = KnowledgeLoader(knowledge_dir)
    runner._ontology_filename = ontology_filename
    runner._emotion_modes_filename = "emociones.json"
    runner._emotion_resources_cache = None
    runner._genre = get_genre()
    return runner


def test_runner_defaults_separate_ontology_and_modes() -> None:
    parameters = inspect.signature(PipelineRunner.__init__).parameters

    assert parameters["ontology_filename"].default == "emociones_ontologia.json"
    assert parameters["emotion_modes_filename"].default == "emociones.json"


def test_runner_loads_real_closed_vocabulary(project_root: Path) -> None:
    runner = _runner_for_resources(project_root / "knowledge")

    ontology_text, modes_text, lookup = runner._load_emotion_resources()

    assert "- gratitud" in ontology_text
    assert "agradecimiento" in ontology_text
    assert "- Realizada" in modes_text
    assert lookup["agradecimiento"] == "gratitud"
    assert lookup["esperanza"] == "esperanza"
    assert "carencia" not in lookup


def test_runner_rejects_modes_file_as_lexical_ontology(project_root: Path) -> None:
    runner = _runner_for_resources(
        project_root / "knowledge",
        ontology_filename="emociones.json",
    )

    with pytest.raises(KnowledgeError, match="modos de existencia"):
        runner._load_emotion_resources()


def test_empty_lookup_fails_closed() -> None:
    assert canonical_emotion("carencia", {}) is None
    assert canonical_emotion("esperanza", {}) is None


def test_none_lookup_preserves_explicit_legacy_open_mode() -> None:
    assert canonical_emotion("esperanza", None) == "esperanza"


def test_prompts_keep_vocabulary_and_modes_in_distinct_sections() -> None:
    for template in (
        "emotions_system",
        "emotions_system_tuit",
        "emotions_pass2_system",
        "emotions_pass2_system_tuit",
    ):
        rendered = prompts.render_system(
            ontologia="- gratitud (aliases: agradecimiento)",
            modos_existencia="- Realizada: emoción efectiva",
            configuraciones="- configuración",
            titulo="",
            tipo_discurso="personal_cotidiano",
            enunciador="@cuenta",
            template=template,
        )

        assert "ONTOLOGÍA DE EMOCIONES" in rendered
        assert "- gratitud (aliases: agradecimiento)" in rendered
        assert "MODOS DE EXISTENCIA" in rendered
        assert "- Realizada: emoción efectiva" in rendered
