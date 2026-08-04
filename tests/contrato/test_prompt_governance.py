"""Contratos de ubicación y presupuesto de instrucciones de prompt."""

from __future__ import annotations

from pathlib import Path

import yaml
from scripts.prompt_footprint import build_footprint

ROOT = Path(__file__).parents[2]


def test_case_heuristics_are_not_duplicated_in_templates() -> None:
    templates = [
        "characterizer_system.jinja2",
        "emotions_system.jinja2",
        "emotions_system_tuit.jinja2",
        "emotions_pass2_system.jinja2",
        "emotions_pass2_system_tuit.jinja2",
    ]
    forbidden = [
        "Agradezco estos mensajes",
        "Siento que + proposición",
        "Cuando vea acciones",
        "El pueblo se hartó",
        "carezco de esperanza",
        "Ojalá licencia",
    ]
    for name in templates:
        text = (ROOT / "src/emoparse/core/prompts/templates" / name).read_text(encoding="utf-8")
        for snippet in forbidden:
            assert snippet not in text, (name, snippet)


def test_rendered_prompts_stay_within_declared_budget() -> None:
    budget = yaml.safe_load(
        (ROOT / "evals/prompt_regression/prompt_budget.yaml").read_text(encoding="utf-8")
    )
    footprint = build_footprint(ROOT)
    assert footprint["emotions_tuit_system_chars"] <= int(
        budget["limits"]["emotions_tuit_system_chars"]
    )
    assert footprint["characterizer_system_chars"] <= int(
        budget["limits"]["characterizer_system_chars"]
    )

    for name, current in footprint.items():
        assert current < int(budget["reference"]["fix_val01_08"][name])
        assert current < int(budget["reference"]["pre_fix_val01_06"][name])


def test_interpretive_rules_are_injected_once() -> None:
    from emoparse.core.prompts import emotions
    from emoparse.knowledge.loader import KnowledgeLoader

    knowledge = KnowledgeLoader(ROOT / "knowledge")
    prompt = emotions.render_system(
        configuraciones=knowledge.load_emotion_configurations("configuraciones_emocion.json"),
        titulo="",
        tipo_discurso="tuit",
        enunciador="@autor.bsky.social",
        heuristicas="\n\n".join(
            [
                knowledge.load_heuristics("heuristicas/emotions.md"),
                knowledge.load_heuristics("heuristicas/emotions_tuit.md"),
            ]
        ),
        modos_existencia=knowledge.load_ontology("emociones.json"),
        template="emotions_system_tuit",
    )

    assert prompt.count("siento que + proposición") == 1
    exact_rule = (
        "Una matriz epistémica en primera persona (`creo que`, `pienso que`, "
        "`siento que`, `me parece que`) no convierte al enunciador en "
        "experienciador de la emoción predicada en la subordinada."
    )
    assert prompt.count(exact_rule) == 1


def test_normalization_catalog_never_enters_prompt_path() -> None:
    prompt_files = [
        ROOT / "src/emoparse/agents/emotions.py",
        ROOT / "src/emoparse/agents/emotions_pass2.py",
        ROOT / "src/emoparse/agents/judge.py",
        ROOT / "src/emoparse/core/prompts/emotions.py",
        ROOT / "src/emoparse/core/prompts/emotions_pass2.py",
        ROOT / "src/emoparse/core/prompts/judge.py",
        ROOT / "scripts/prompt_footprint.py",
    ]
    forbidden = [
        "catalogo_normalizacion_emociones.json",
        "load_emotion_" + "normalization_catalog",
        "format_emotion_" + "ontology_for_prompt",
        "emotion_" + "alias_lookup",
        "ontologia=",
    ]
    for path in prompt_files:
        text = path.read_text(encoding="utf-8")
        for snippet in forbidden:
            assert snippet not in text, (path, snippet)

    runner = (ROOT / "src/emoparse/pipeline/runner.py").read_text(encoding="utf-8")
    emotions_block = runner.split('if name == "emotions":', 1)[1].split(
        'if name == "explode_emotions":', 1
    )[0]
    judge_block = runner.split('if name == "judge":', 1)[1].split('if name == "actants":', 1)[0]
    for block in (emotions_block, judge_block):
        for snippet in forbidden:
            assert snippet not in block, snippet

    stages = (ROOT / "src/emoparse/pipeline/stages.py").read_text(encoding="utf-8")
    detection = stages.split("class EmotionsStage", 1)[1].split("class NormalizeEmotionsStage", 1)[
        0
    ]
    judge = stages.split("class JudgeStage", 1)[1]
    for block in (detection, judge):
        for snippet in forbidden:
            assert snippet not in block, snippet


def test_legacy_catalog_name_is_gone() -> None:
    for base in [ROOT / "src", ROOT / "tests", ROOT / "scripts", ROOT / "knowledge"]:
        for path in base.rglob("*"):
            if path.is_file() and path.suffix not in {".pyc", ".sqlite"}:
                legacy = "emociones_" + "ont" + "ologia"
                assert legacy not in path.read_text(encoding="utf-8"), path
