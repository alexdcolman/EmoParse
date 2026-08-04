"""Contratos de separación entre detección y normalización emocional."""

from __future__ import annotations

import ast
from pathlib import Path

from emoparse.core.prompts import emotions as prompts
from emoparse.knowledge.loader import KnowledgeLoader
from emoparse.knowledge.normalization import build_emotion_normalization_lookup

ROOT = Path(__file__).parents[2]


def _runner_init_defaults() -> dict[str, object]:
    tree = ast.parse((ROOT / "src/emoparse/pipeline/runner.py").read_text(encoding="utf-8"))
    pipeline = next(
        node
        for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == "PipelineRunner"
    )
    init = next(
        node
        for node in pipeline.body
        if isinstance(node, ast.FunctionDef) and node.name == "__init__"
    )
    defaults: dict[str, object] = {}
    for arg, value in zip(init.args.kwonlyargs, init.args.kw_defaults, strict=True):
        if arg.arg in {"normalization_filename", "emotion_modes_filename"}:
            defaults[arg.arg] = ast.literal_eval(value)
    return defaults


def test_runner_defaults_separate_normalization_catalog_and_modes() -> None:
    defaults = _runner_init_defaults()

    assert defaults["normalization_filename"] == "catalogo_normalizacion_emociones.json"
    assert defaults["emotion_modes_filename"] == "emociones.json"


def test_emotions_modes_resource_is_distinct_from_normalization_catalog(
    project_root: Path,
) -> None:
    loader = KnowledgeLoader(project_root / "knowledge")

    modes_text = loader.load_ontology("emociones.json", genre_id="tuit")
    catalog = loader.load_emotion_normalization_catalog()
    constraints = loader.load_emotion_characterization_constraints()

    assert "Realizada" in modes_text
    assert "Potencial" in modes_text
    assert "gratitud" not in modes_text
    assert "agradecimiento" not in modes_text
    assert "gratitud" in catalog["emociones"]
    assert set(catalog["emociones"]["gratitud"]) <= {"aliases", "generos"}
    assert "foria" in constraints["emociones"]["gratitud"]
    assert "aliases" not in constraints["emociones"]["gratitud"]


def test_normalization_catalog_builds_ex_post_lookup(project_root: Path) -> None:
    loader = KnowledgeLoader(project_root / "knowledge")
    catalog = loader.load_emotion_normalization_catalog()
    lookup = build_emotion_normalization_lookup(catalog, normalize_accents=True)

    assert lookup["agradecimiento"] == "gratitud"
    assert lookup["esperanza"] == "esperanza"
    assert "carencia" not in lookup


def test_emotions_prompt_has_modes_but_no_normalization_catalog() -> None:
    for template in (
        "emotions_system",
        "emotions_system_tuit",
        "emotions_pass2_system",
        "emotions_pass2_system_tuit",
    ):
        rendered = prompts.render_system(
            modos_existencia="- Realizada: emoción efectiva",
            configuraciones="- configuración",
            titulo="",
            tipo_discurso="personal_cotidiano",
            enunciador="@cuenta",
            template=template,
        )

        assert "MODOS DE EXISTENCIA" in rendered
        assert "- Realizada: emoción efectiva" in rendered
        assert "ONTOLOGÍA DE EMOCIONES" not in rendered
        assert "agradecimiento" not in rendered
        assert "vocabulario cerrado" not in rendered


def test_catalog_is_consumed_only_by_normalize_emotions_in_product_code() -> None:
    allowed = {
        ROOT / "src/emoparse/knowledge/loader.py",
        ROOT / "src/emoparse/knowledge/normalization.py",
        ROOT / "src/emoparse/pipeline/runner.py",
        ROOT / "src/emoparse/pipeline/stages.py",
    }
    needles = {
        "catalogo_normalizacion_emociones.json",
        "load_emotion_normalization_catalog",
        "build_emotion_normalization_lookup",
    }

    hits: set[Path] = set()
    for path in (ROOT / "src/emoparse").rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        if any(needle in text for needle in needles):
            hits.add(path)

    assert hits <= allowed, sorted(str(path.relative_to(ROOT)) for path in hits - allowed)

    runner = (ROOT / "src/emoparse/pipeline/runner.py").read_text(encoding="utf-8")
    normalize_block = runner.split('if name == "normalize_emotions":', 1)[1].split(
        'if name == "normalize_actors":', 1
    )[0]
    assert "load_emotion_normalization_catalog" in normalize_block

    for stage in ("emotions", "emotions_pass2", "judge"):
        block = runner.split(f'if name == "{stage}":', 1)[1].split("\n        if name ==", 1)[0]
        assert "load_emotion_normalization_catalog" not in block


def test_evaluation_consumes_persisted_canonical_type_without_catalog() -> None:
    from emoparse.evaluation.matching import match_units

    key = ("post-1", 0)
    golden = {key: [{"tipo_emocion": "esperanza", "experienciador": "@autor"}]}
    predicted = {
        key: [
            {
                "tipo_emocion": "expectativa",
                "tipo_emocion_canonico": "esperanza",
                "experienciador": "@autor",
            }
        ]
    }

    report = match_units(golden, predicted)

    assert report.tp == 1
    assert report.fp == 0
    assert report.fn == 0


def test_evaluation_does_not_recanonicalize_raw_detection_labels() -> None:
    from emoparse.evaluation.matching import match_units

    key = ("post-1", 0)
    golden = {key: [{"tipo_emocion": "esperanza", "experienciador": "@autor"}]}
    predicted = {
        key: [
            {
                "tipo_emocion": "expectativa",
                "tipo_emocion_canonico": None,
                "experienciador": "otro actor",
            }
        ]
    }

    report = match_units(golden, predicted)

    assert report.tp == 0
    assert report.fp == 1
    assert report.fn == 1


def test_v11_uses_separate_canonical_constraints_without_aliases(project_root: Path) -> None:
    from emoparse.domain.validators.rules import V11_DesviacionOntologica

    loader = KnowledgeLoader(project_root / "knowledge")
    constraints = loader.load_emotion_characterization_constraints()
    validator = V11_DesviacionOntologica(constraints)

    assert "gratitud" in validator._lookup
    assert "agradecimiento" not in validator._lookup
