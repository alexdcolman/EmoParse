"""Contratos del arnés reproducible para el smoke test multigénero VAL-01."""

from __future__ import annotations

import argparse
import csv
import importlib.util
import json
import sqlite3
import sys
from pathlib import Path
from types import ModuleType

import yaml

SCRIPT_PATH = Path(__file__).parents[2] / "scripts" / "val01_smoke.py"


def _load_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("val01_smoke", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def _sources(tmp_path: Path) -> tuple[Path, Path, Path, Path]:
    config = tmp_path / "config.yaml"
    config.write_text(
        yaml.safe_dump(
            {
                "models": {"modelo-prueba": {"backend": "llama_cpp", "path": "modelo.gguf"}},
                "pipeline": {"stages": {"metadata": "otro"}},
                "paths": {"knowledge_dir": "knowledge"},
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    article = tmp_path / "pagina12.csv"
    _write_csv(
        article,
        [
            {
                "codigo": "p12_1",
                "url": "https://www.pagina12.com.ar/1-nota",
                "titulo": "Una nota",
                "contenido": (
                    "Primer párrafo con información política suficiente para validar la segmentación y el contexto editorial del artículo.\n\n"
                    "Segundo párrafo con antecedentes, actores involucrados y una explicación más extensa del acontecimiento público.\n\n"
                    "Tercer párrafo con declaraciones atribuidas, expectativas y preocupaciones relevantes para el análisis emocional.\n\n"
                    "Cuarto párrafo con consecuencias, reacciones y un cierre periodístico suficientemente desarrollado."
                ),
                "fuente": "pagina12",
                "medio": "Página/12",
                "idioma": "es",
                "seccion": "El País",
                "volanta": "Política",
                "subtitulo": "Una bajada",
                "autoria": '["Autora"]',
                "agencia": "",
                "epigrafe": "Una imagen",
            }
        ],
    )
    discourse = tmp_path / "discurso.csv"
    _write_csv(
        discourse,
        [
            {
                "codigo": "discurso_1",
                "contenido": " ".join(
                    [
                        "Primera oración suficientemente extensa para la prueba.",
                        "Segunda oración con una expectativa política concreta.",
                        "Tercera oración donde aparece una preocupación pública.",
                        "Cuarta oración que expresa determinación institucional.",
                        "Quinta oración con agradecimiento a la ciudadanía.",
                        "Sexta oración que cierra el fragmento seleccionado.",
                        "Séptima oración que no debería incorporarse.",
                    ]
                ),
                "fuente": "casarosada",
            }
        ],
    )
    posts = tmp_path / "posts.jsonl"
    with posts.open("w", encoding="utf-8") as stream:
        for index in range(6):
            stream.write(
                json.dumps(
                    {
                        "id": f"post-{index}",
                        "plataforma": "bluesky",
                        "autor_handle": f"autor{index}.bsky.social",
                        "texto": f"Post emocional número {index}",
                        "tipo": "original",
                        "media": [],
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )
    return config, article, discourse, posts


def test_find_article_csv_identifies_pagina12(tmp_path: Path) -> None:
    module = _load_module()
    _, article, _, _ = _sources(tmp_path)

    found = module.find_article_csv(tmp_path)

    assert found == article


def test_prepare_creates_isolated_config_and_three_inputs(tmp_path: Path) -> None:
    module = _load_module()
    config, article, discourse, posts = _sources(tmp_path)
    workspace = tmp_path / "workspace"
    args = argparse.Namespace(
        config=config,
        model_alias="modelo-prueba",
        article_source=article,
        discourse_source=discourse,
        posts_source=posts,
        workspace=workspace,
        article_paragraphs=3,
        discourse_sentences=6,
        posts=5,
    )

    assert module.prepare(args) == 0

    generated = yaml.safe_load((workspace / "config.val01.yaml").read_text(encoding="utf-8"))
    assert generated["pipeline"]["parallel"] == 1
    assert generated["pipeline"]["cache_enabled"] is True
    assert all(
        generated["pipeline"]["stages"][stage] == "modelo-prueba" for stage in module.MODEL_STAGES
    )
    article_rows = module._read_csv_rows(workspace / "inputs" / "articulo.csv")[1]
    discourse_rows = module._read_csv_rows(workspace / "inputs" / "discurso.csv")[1]
    assert len(article_rows) == 1
    assert len(discourse_rows) == 1
    assert article_rows[0]["codigo"].endswith("_val01")
    assert discourse_rows[0]["codigo"].endswith("_val01")
    assert len((workspace / "inputs" / "posts.jsonl").read_text(encoding="utf-8").splitlines()) == 5
    manifest = json.loads((workspace / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["model_alias"] == "modelo-prueba"
    assert len(manifest["prepared"]["posts"]["ids"]) == 5


def test_prepare_rejects_unknown_model_alias(tmp_path: Path) -> None:
    module = _load_module()
    config, article, discourse, posts = _sources(tmp_path)
    args = argparse.Namespace(
        config=config,
        model_alias="inexistente",
        article_source=article,
        discourse_source=discourse,
        posts_source=posts,
        workspace=tmp_path / "workspace",
        article_paragraphs=3,
        discourse_sentences=6,
        posts=5,
    )

    try:
        module.prepare(args)
    except module.Val01Error as exc:
        assert "inexistente" in str(exc)
    else:
        raise AssertionError("prepare debía rechazar el alias desconocido")


def _create_good_run(workspace: Path, module: ModuleType, spec: object) -> None:
    db_path = workspace / "runs" / f"{spec.key}.sqlite"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(db_path)
    connection.executescript(
        """
        CREATE TABLE runs (
            run_id TEXT,
            status TEXT,
            config TEXT
        );
        CREATE TABLE discursos (
            codigo TEXT,
            summarizer_error TEXT,
            metadata_error TEXT,
            enunciation_error TEXT
        );
        CREATE TABLE frases (
            codigo TEXT,
            unit_idx INTEGER,
            actores_error TEXT,
            emociones_error TEXT,
            emociones_pass2_error TEXT
        );
        CREATE TABLE emociones (
            codigo TEXT,
            frase_idx INTEGER,
            emocion_idx INTEGER,
            caracterizacion_error TEXT,
            actantes_error TEXT
        );
        CREATE TABLE run_metrics (
            stage_name TEXT,
            n_items_ok INTEGER,
            n_items_failed INTEGER,
            recorded_at TEXT
        );
        CREATE TABLE llm_cache (model_alias TEXT);
        """
    )
    config = {
        "_emoparse": {
            "genre": {
                "genre_id": spec.genre_id,
                "display_name": spec.genre_id,
                "input_metadata": [],
            }
        }
    }
    connection.execute(
        "INSERT INTO runs VALUES (?, 'completed', ?)",
        (f"val01_{spec.key}", json.dumps(config)),
    )
    for index in range(spec.expected_discursos):
        code = f"{spec.key}-{index}"
        connection.execute("INSERT INTO discursos VALUES (?, NULL, NULL, NULL)", (code,))
        connection.execute("INSERT INTO frases VALUES (?, 0, NULL, NULL, NULL)", (code,))
        connection.execute("INSERT INTO emociones VALUES (?, 0, 0, NULL, NULL)", (code,))
    for stage in spec.expected_stages:
        ok = 1 if stage in {"summarizer", "metadata", "enunciation", "emotions"} else 0
        connection.execute(
            "INSERT INTO run_metrics VALUES (?, ?, 0, '2026-08-02T00:00:00')",
            (stage, ok),
        )
    connection.execute("INSERT INTO llm_cache VALUES ('modelo-prueba')")
    connection.commit()
    connection.close()

    export_dir = workspace / "exports" / spec.key
    export_dir.mkdir(parents=True, exist_ok=True)
    counts = {
        "discursos.csv": spec.expected_discursos,
        "metadata_genero.csv": 8 if spec.genre_id == "articulo_periodistico" else 0,
        "frases.csv": spec.expected_discursos,
        "emociones.csv": spec.expected_discursos,
    }
    for filename, count in counts.items():
        with (export_dir / filename).open("w", encoding="utf-8", newline="") as stream:
            writer = csv.writer(stream)
            writer.writerow(["valor"])
            for index in range(count):
                writer.writerow([index])


def test_inspect_workspace_accepts_coherent_runs(tmp_path: Path) -> None:
    module = _load_module()
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "manifest.json").write_text(
        json.dumps({"model_alias": "modelo-prueba"}), encoding="utf-8"
    )
    for spec in module.RUN_SPECS:
        _create_good_run(workspace, module, spec)

    ok, report = module.inspect_workspace(workspace)

    assert ok is True
    assert "**APROBADO**" in report
    assert "Ninguno" in report


def test_inspect_workspace_detects_missing_stage_metric(tmp_path: Path) -> None:
    module = _load_module()
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "manifest.json").write_text(
        json.dumps({"model_alias": "modelo-prueba"}), encoding="utf-8"
    )
    for spec in module.RUN_SPECS:
        _create_good_run(workspace, module, spec)
    connection = sqlite3.connect(workspace / "runs" / "articulo.sqlite")
    connection.execute("DELETE FROM run_metrics WHERE stage_name = 'metadata'")
    connection.commit()
    connection.close()

    ok, report = module.inspect_workspace(workspace)

    assert ok is False
    assert "falta métrica de la stage metadata" in report
