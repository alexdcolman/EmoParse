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
    for name, current in footprint.items():
        assert name in budget["limits"], name
        assert current <= int(budget["limits"][name]), (name, current, budget["limits"][name])

    for name, current in footprint.items():
        fix08 = budget["reference"]["fix_val01_08"].get(name)
        pre06 = budget["reference"]["pre_fix_val01_06"].get(name)
        if fix08 is not None:
            assert current < int(fix08)
        if pre06 is not None:
            assert current < int(pre06)


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


def test_actants_interpretive_rules_have_single_source_of_truth() -> None:
    from emoparse.agents.actants import ACTANTS_COMPONENTS
    from emoparse.core.prompts import actants
    from emoparse.knowledge.loader import KnowledgeLoader

    template = (ROOT / "src/emoparse/core/prompts/templates/actants_system.jinja2").read_text(
        encoding="utf-8"
    )
    heuristics = (ROOT / "knowledge/heuristicas/actants.md").read_text(encoding="utf-8")

    semantic_markers = (
        "fuente → mediador → experienciador",
        "discurso_propio",
        "norma_sociocultural",
        "corroboracion_de_autenticidad",
        "persuasion_afectiva",
        "negada_factual",
    )
    for marker in semantic_markers:
        assert marker in heuristics, marker
        assert marker not in template, marker

    assert "afinen según el corpus" not in heuristics
    assert "No se afinan contra ejemplos aislados" in heuristics

    knowledge = KnowledgeLoader(ROOT / "knowledge")
    rendered = actants.render_system(
        titulo="",
        tipo_discurso="discurso_presidencial",
        enabled_components=ACTANTS_COMPONENTS,
        disabled_components=(),
        heuristicas=knowledge.load_heuristics("heuristicas/actants.md"),
    )
    for marker in semantic_markers:
        assert rendered.count(marker) == 1, marker


def test_actants_prompt_is_smaller_than_pre_dedupe_reference() -> None:
    budget = yaml.safe_load(
        (ROOT / "evals/prompt_regression/prompt_budget.yaml").read_text(encoding="utf-8")
    )
    footprint = build_footprint(ROOT)
    old = int(budget["reference"]["actants_v64_pre_dedupe"]["actants_system_chars"])
    assert footprint["actants_system_chars"] < old


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


def test_emotion_configuration_rules_keep_lexical_and_viewpoint_boundaries() -> None:
    from emoparse.knowledge.loader import KnowledgeLoader

    data = yaml.safe_load(
        (ROOT / "knowledge/configuraciones_emocion.json").read_text(encoding="utf-8")
    )
    configs = data["configuraciones"]

    for key in (
        "sostenido_en_sustantivos",
        "sostenido_en_adjetivos",
    ):
        assert "familia léxica de una emoción" in configs[key]["definicion"]

    assert (
        "procesos o estados afectivos"
        in configs["ordenado_alrededor_de_verbos_psicologicos"]["definicion"]
    )

    assert (
        "ninguna marca léxica ni conductual"
        in configs["transposicion_situacion_reconocimiento_potencial"]["definicion"]
    )
    assert (
        "punto de vista del experienciador"
        in configs["cualificacion_por_indicadores_axiologicos"]["definicion"]
    )
    assert (
        "enunciador principal" in configs["cualificacion_por_indicadores_axiologicos"]["definicion"]
    )
    assert (
        "sin marca léxica o conductual clara"
        in configs["cualificacion_por_componentes_descriptivo_narrativos"]["definicion"]
    )

    schema = (ROOT / "src/emoparse/core/schemas.py").read_text(encoding="utf-8")
    assert "una palabra no emocional" in schema
    assert "usar la 8 (transposición situacional)" in schema

    rendered = KnowledgeLoader(ROOT / "knowledge").load_emotion_configurations(
        "configuraciones_emocion.json"
    )
    assert rendered.count("punto de vista del experienciador") == 1
    assert rendered.count("enunciador principal") == 1
