"""Contratos de lint, tipado e integración continua."""

from __future__ import annotations

import tomllib
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW_PATH = ROOT / ".github" / "workflows" / "ci.yml"
PYPROJECT_PATH = ROOT / "pyproject.toml"
BLAME_IGNORE_PATH = ROOT / ".git-blame-ignore-revs"


def _workflow() -> dict[str, object]:
    """Carga el workflow sin la coerción YAML 1.1 de la clave ``on``."""
    loaded = yaml.load(WORKFLOW_PATH.read_text(encoding="utf-8"), Loader=yaml.BaseLoader)
    assert isinstance(loaded, dict)
    return loaded


def _pyproject() -> dict[str, object]:
    with PYPROJECT_PATH.open("rb") as file:
        return tomllib.load(file)


def test_ci_workflow_has_expected_jobs() -> None:
    jobs = _workflow()["jobs"]
    assert isinstance(jobs, dict)
    assert set(jobs) == {"lint", "types", "test", "docs"}


def test_ci_runs_on_push_and_pull_request() -> None:
    triggers = _workflow()["on"]
    assert isinstance(triggers, dict)
    assert set(triggers) == {"push", "pull_request"}


def test_ci_uses_supported_python_matrix() -> None:
    jobs = _workflow()["jobs"]
    assert isinstance(jobs, dict)
    test_job = jobs["test"]
    assert isinstance(test_job, dict)
    strategy = test_job["strategy"]
    assert isinstance(strategy, dict)
    matrix = strategy["matrix"]
    assert isinstance(matrix, dict)
    assert matrix["python-version"] == ["3.11", "3.12"]


def test_contract_tests_are_blocking() -> None:
    text = WORKFLOW_PATH.read_text(encoding="utf-8")
    assert "python -m pytest tests/contrato -q" in text


def test_scaffold_tests_are_informative() -> None:
    jobs = _workflow()["jobs"]
    assert isinstance(jobs, dict)
    test_job = jobs["test"]
    assert isinstance(test_job, dict)
    steps = test_job["steps"]
    assert isinstance(steps, list)

    scaffold = next(
        step
        for step in steps
        if isinstance(step, dict) and step.get("name") == "Andamio informativo"
    )
    assert scaffold["continue-on-error"] == "true"
    assert scaffold["run"] == "python -m pytest tests/andamio -q"


def test_ci_does_not_run_llm_tests() -> None:
    text = WORKFLOW_PATH.read_text(encoding="utf-8")
    assert "tests/integracion_llm" not in text
    assert "EMOPARSE_LLM_TEST" not in text


def test_ci_checks_lint_and_format() -> None:
    text = WORKFLOW_PATH.read_text(encoding="utf-8")
    assert "ruff check src tests scripts" in text
    assert "ruff format --check src tests scripts" in text


def test_ci_checks_types_and_generated_docs() -> None:
    text = WORKFLOW_PATH.read_text(encoding="utf-8")
    assert "run: mypy" in text
    assert "python scripts/gen_cli_reference.py --check" in text

    tool = _pyproject()["tool"]
    assert isinstance(tool, dict)
    mypy = tool["mypy"]
    assert isinstance(mypy, dict)
    assert mypy["files"] == [
        "src/emoparse/version.py",
        "src/emoparse/config",
        "src/emoparse/core/text.py",
        "src/emoparse/core/grammar.py",
        "src/emoparse/core/backend/exceptions.py",
        "src/emoparse/core/backend/retry.py",
        "src/emoparse/domain/validators/base.py",
        "src/emoparse/genres/base.py",
        "src/emoparse/genres/presentation.py",
    ]


def test_ci_builds_wheel() -> None:
    text = WORKFLOW_PATH.read_text(encoding="utf-8")
    assert "python -m build --wheel" in text


def test_ruff_configuration_is_explicit() -> None:
    tool = _pyproject()["tool"]
    assert isinstance(tool, dict)
    ruff = tool["ruff"]
    assert isinstance(ruff, dict)
    lint = ruff["lint"]
    assert isinstance(lint, dict)

    assert ruff["line-length"] == 100
    assert ruff["target-version"] == "py311"
    assert lint["select"] == ["E", "F", "I", "UP", "B"]
    assert set(lint["ignore"]) >= {"E402", "F841", "B027", "B905"}


def test_development_extra_contains_ci_tools() -> None:
    project = _pyproject()["project"]
    assert isinstance(project, dict)
    optional = project["optional-dependencies"]
    assert isinstance(optional, dict)
    dev = optional["dev"]
    assert isinstance(dev, list)

    assert any(item.startswith("ruff>=") for item in dev)
    assert any(item.startswith("mypy>=") for item in dev)
    assert any(item.startswith("build>=") for item in dev)
    assert any(item.startswith("types-PyYAML>=") for item in dev)


def test_blame_ignore_file_accepts_only_commit_hashes() -> None:
    text = BLAME_IGNORE_PATH.read_text(encoding="utf-8")
    assert "formateo mecánico" in text
    revisions = [
        line.strip() for line in text.splitlines() if line.strip() and not line.startswith("#")
    ]
    assert all(
        len(revision) == 40 and all(character in "0123456789abcdef" for character in revision)
        for revision in revisions
    )
