"""Contratos de 2.3: procedencia, reportes y comparación de runs."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from emoparse.cli.__main__ import build_parser
from emoparse.evaluation.run_comparison import (
    classify_reference,
    compare_runs,
    is_role_label,
    load_run_overview,
)
from emoparse.storage.db import Database
from emoparse.storage.eval_reports import EvalReportsRepository
from emoparse.storage.metrics import MetricsRepository, StageMetricsSnapshot
from emoparse.storage.models import RunContext, Versions
from emoparse.storage.runs import RunsRepository


def _create_run(
    path: Path,
    *,
    run_id: str,
    model: str,
    experiencer: str = "Javier Milei",
    experiencer_canonical: str = "javier_milei",
    source: str = "la medida",
    source_canonical: str = "medida",
) -> None:
    db = Database(path)
    config = {
        "pipeline": {"stages": {"emotions": model}},
        "_emoparse": {
            "genre": {
                "genre_id": "tuit",
                "display_name": "Tuit",
                "input_metadata": [],
            }
        },
    }
    RunsRepository(db).bootstrap(
        RunContext(
            run_id=run_id,
            versions=Versions(
                knowledge="v19",
                prompt="v54",
                ontology="v27",
                schema="v41",
            ),
            config=config,
            notes=f"run con {model}",
        )
    )
    with db.transaction() as cur:
        cur.execute(
            "INSERT INTO discursos (codigo, input) VALUES (?, ?)",
            ("post-1", json.dumps({"contenido": "Me indigna la medida."})),
        )
        cur.execute(
            "INSERT INTO frases (codigo, unit_idx, frase) VALUES (?, ?, ?)",
            ("post-1", 0, "Me indigna la medida."),
        )
        cur.execute(
            """
            INSERT INTO emociones (
                codigo, frase_idx, emocion_idx,
                experienciador, experienciador_marca,
                tipo_emocion, fuente_marca, fuente_inferencia,
                modo_existencia, tipo_configuracion,
                tipo_emocion_canonico, experienciador_canonico,
                fuente_canonico, caracterizacion_payload
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "post-1",
                0,
                0,
                experiencer,
                experiencer,
                "indignación",
                source,
                source,
                "realizada",
                "TIPO_1",
                "indignación",
                experiencer_canonical,
                source_canonical,
                json.dumps({"foria": "disforico"}),
            ),
        )
    MetricsRepository(db).insert(
        run_id,
        "emotions",
        StageMetricsSnapshot(n_items_ok=1),
        model_alias=model,
    )
    db.close_thread_connection()


def test_additive_migration_adds_model_alias_and_eval_reports(tmp_path: Path) -> None:
    path = tmp_path / "legacy.sqlite"
    connection = sqlite3.connect(path)
    try:
        connection.execute(
            """
            CREATE TABLE run_metrics (
                run_id TEXT NOT NULL,
                stage_name TEXT NOT NULL,
                n_items_ok INTEGER NOT NULL DEFAULT 0,
                n_items_failed INTEGER NOT NULL DEFAULT 0,
                total_latency_ms REAL NOT NULL DEFAULT 0.0,
                p50_latency_ms REAL,
                p99_latency_ms REAL,
                total_prompt_tokens INTEGER NOT NULL DEFAULT 0,
                total_completion_tokens INTEGER NOT NULL DEFAULT 0,
                cache_hits INTEGER NOT NULL DEFAULT 0,
                cache_misses INTEGER NOT NULL DEFAULT 0,
                recorded_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (run_id, stage_name, recorded_at)
            )
            """
        )
        connection.commit()
    finally:
        connection.close()

    db = Database(path)
    RunsRepository(db).ensure_migrations()

    columns = {row["name"] for row in db.execute("PRAGMA table_info(run_metrics)")}
    assert "model_alias" in columns
    assert db.table_exists("eval_reports")
    db.close_thread_connection()


def test_metrics_detects_mixed_stage(tmp_path: Path) -> None:
    path = tmp_path / "mixed.sqlite"
    _create_run(path, run_id="mixed", model="modelo-a")
    db = Database(path)
    db.execute(
        "UPDATE run_metrics SET recorded_at = ?",
        ("2026-01-01T00:00:00+00:00",),
    )
    repo = MetricsRepository(db)
    repo.insert(
        "mixed",
        "emotions",
        StageMetricsSnapshot(n_items_ok=1),
        model_alias="modelo-b",
    )

    assert repo.model_aliases_by_stage("mixed") == {"emotions": ("modelo-a", "modelo-b")}
    assert repo.mixed_stages("mixed") == {"emotions": ("modelo-a", "modelo-b")}
    db.close_thread_connection()


def test_eval_reports_round_trip_structured_payload(tmp_path: Path) -> None:
    run_path = tmp_path / "run.sqlite"
    _create_run(run_path, run_id="run", model="modelo-a")
    db = Database(run_path)
    report_id = EvalReportsRepository(db).insert(
        run_id="run",
        golden_version="v2",
        payload={
            "report_type": "golden",
            "golden_version": "v2",
            "golden_sha256": "abc123",
            "genre": "tuit",
            "metrics": {"unidades": 1, "precision": 1.0, "recall": 1.0, "f1": 1.0},
        },
    )
    reports = EvalReportsRepository(db).list_for_run("run")
    db.close_thread_connection()

    assert report_id > 0
    assert len(reports) == 1
    assert reports[0]["golden_version"] == "v2"
    assert reports[0]["payload"]["report_type"] == "golden"
    assert reports[0]["payload"]["metrics"]["f1"] == 1.0


def test_eval_cli_persists_golden_report(tmp_path: Path) -> None:
    run_path = tmp_path / "run.sqlite"
    _create_run(run_path, run_id="run", model="modelo-a")
    golden_dir = tmp_path / "golden" / "v2"
    golden_dir.mkdir(parents=True)
    golden_path = golden_dir / "tuit.jsonl"
    golden_path.write_text(
        json.dumps(
            {
                "codigo": "post-1",
                "unit_idx": 0,
                "genero": "tuit",
                "emociones": [
                    {
                        "tipo_emocion": "indignación",
                        "experienciador": "Javier Milei",
                        "fuente": "la medida",
                        "modo_existencia": "realizada",
                        "foria": "disforico",
                    }
                ],
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    output = tmp_path / "report.md"
    args = build_parser().parse_args(
        [
            "eval",
            "--db",
            str(run_path),
            "--golden",
            str(golden_path),
            "--persist-report",
            "--out",
            str(output),
        ]
    )

    assert args.handler(args) == 0
    db = Database(run_path)
    reports = EvalReportsRepository(db).list_for_run("run")
    db.close_thread_connection()

    assert output.exists()
    assert len(reports) == 1
    assert reports[0]["golden_version"] == "v2"
    assert reports[0]["payload"]["metrics"]["f1"] == 1.0


def test_eval_cli_persists_control_report(tmp_path: Path) -> None:
    run_path = tmp_path / "control.sqlite"
    _create_run(run_path, run_id="control", model="modelo-a")
    args = build_parser().parse_args(
        [
            "eval",
            "--db",
            str(run_path),
            "--control",
            "--persist-report",
        ]
    )

    assert args.handler(args) == 0
    db = Database(run_path)
    reports = EvalReportsRepository(db).list_for_run("control")
    db.close_thread_connection()

    assert len(reports) == 1
    assert reports[0]["golden_version"] == "control"
    assert reports[0]["payload"]["report_type"] == "control"
    assert reports[0]["payload"]["metrics"]["unidades"] == 1
    assert reports[0]["payload"]["metrics"]["emociones_detectadas"] == 1


def test_overview_reads_legacy_run_without_observed_models(tmp_path: Path) -> None:
    path = tmp_path / "legacy-overview.sqlite"
    _create_run(path, run_id="legacy", model="modelo-a")
    connection = sqlite3.connect(path)
    try:
        connection.execute("ALTER TABLE run_metrics RENAME TO run_metrics_new")
        connection.execute(
            """
            CREATE TABLE run_metrics (
                run_id TEXT NOT NULL,
                stage_name TEXT NOT NULL,
                n_items_ok INTEGER NOT NULL DEFAULT 0,
                n_items_failed INTEGER NOT NULL DEFAULT 0,
                total_latency_ms REAL NOT NULL DEFAULT 0.0,
                p50_latency_ms REAL,
                p99_latency_ms REAL,
                total_prompt_tokens INTEGER NOT NULL DEFAULT 0,
                total_completion_tokens INTEGER NOT NULL DEFAULT 0,
                cache_hits INTEGER NOT NULL DEFAULT 0,
                cache_misses INTEGER NOT NULL DEFAULT 0,
                recorded_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (run_id, stage_name, recorded_at)
            )
            """
        )
        connection.execute(
            """
            INSERT INTO run_metrics (
                run_id, stage_name, n_items_ok, n_items_failed, total_latency_ms,
                p50_latency_ms, p99_latency_ms, total_prompt_tokens,
                total_completion_tokens, cache_hits, cache_misses, recorded_at
            )
            SELECT
                run_id, stage_name, n_items_ok, n_items_failed, total_latency_ms,
                p50_latency_ms, p99_latency_ms, total_prompt_tokens,
                total_completion_tokens, cache_hits, cache_misses, recorded_at
            FROM run_metrics_new
            """
        )
        connection.execute("DROP TABLE run_metrics_new")
        connection.execute("DROP TABLE eval_reports")
        connection.commit()
    finally:
        connection.close()

    overview = load_run_overview(path)

    assert overview.run_id == "legacy"
    assert overview.genre == "tuit"
    assert overview.genre_source == "snapshot"
    assert overview.configured_models == {"emotions": "modelo-a"}
    assert overview.observed_models == {}
    assert overview.mixed_stages == {}
    assert overview.latest_reports == {}


def test_overview_infers_tuit_for_legacy_run_with_posts(tmp_path: Path) -> None:
    path = tmp_path / "legacy-tuit.sqlite"
    _create_run(path, run_id="legacy-tuit", model="modelo-a")
    connection = sqlite3.connect(path)
    try:
        connection.execute(
            "UPDATE runs SET config = ?",
            (json.dumps({"pipeline": {"stages": {"emotions": "modelo-a"}}}),),
        )
        connection.execute(
            """
            INSERT INTO posts (post_id, plataforma, autor_handle, texto)
            VALUES (?, ?, ?, ?)
            """,
            ("post-1", "bluesky", "alex.test", "Me indigna la medida."),
        )
        connection.commit()
    finally:
        connection.close()

    overview = load_run_overview(path)

    assert overview.genre == "tuit"
    assert overview.genre_source == "estructura_posts"


def test_overview_infers_tuit_for_legacy_run_with_input_metadata(tmp_path: Path) -> None:
    path = tmp_path / "legacy-tuit-input.sqlite"
    _create_run(path, run_id="legacy-tuit-input", model="modelo-a")
    connection = sqlite3.connect(path)
    try:
        connection.execute(
            "UPDATE runs SET config = ?",
            (json.dumps({"pipeline": {"stages": {"emotions": "modelo-a"}}}),),
        )
        connection.execute(
            "UPDATE discursos SET input = ? WHERE codigo = ?",
            (
                json.dumps(
                    {
                        "contenido": "Texto del post.",
                        "autor_handle": "alex.test",
                        "tipo_post": "original",
                    }
                ),
                "post-1",
            ),
        )
        connection.commit()
    finally:
        connection.close()

    overview = load_run_overview(path)

    assert overview.genre == "tuit"
    assert overview.genre_source == "metadata_input_tuit"


def test_overview_infers_article_for_legacy_run_with_article_metadata(tmp_path: Path) -> None:
    path = tmp_path / "legacy-article.sqlite"
    _create_run(path, run_id="legacy-article", model="modelo-a")
    connection = sqlite3.connect(path)
    try:
        connection.execute(
            "UPDATE runs SET config = ?",
            (json.dumps({"pipeline": {"stages": {"emotions": "modelo-a"}}}),),
        )
        connection.execute(
            "UPDATE discursos SET input = ? WHERE codigo = ?",
            (
                json.dumps(
                    {
                        "contenido": "Texto de la nota.",
                        "titulo": "Título",
                        "medio": "Diario de prueba",
                        "seccion": "Política",
                    }
                ),
                "post-1",
            ),
        )
        connection.commit()
    finally:
        connection.close()

    overview = load_run_overview(path)

    assert overview.genre == "articulo_periodistico"
    assert overview.genre_source == "metadata_input"


def test_overview_infers_historical_presidential_genre_for_legacy_run(tmp_path: Path) -> None:
    path = tmp_path / "legacy-presidential.sqlite"
    _create_run(path, run_id="legacy-presidential", model="modelo-a")
    connection = sqlite3.connect(path)
    try:
        connection.execute(
            "UPDATE runs SET config = ?",
            (json.dumps({"pipeline": {"stages": {"emotions": "modelo-a"}}}),),
        )
        connection.commit()
    finally:
        connection.close()

    overview = load_run_overview(path)

    assert overview.genre == "discurso_presidencial"
    assert overview.genre_source == "fallback_historico"


def test_overview_reads_incomplete_legacy_genre_config(tmp_path: Path) -> None:
    path = tmp_path / "legacy-config.sqlite"
    _create_run(path, run_id="legacy-config", model="modelo-a")
    connection = sqlite3.connect(path)
    try:
        connection.execute(
            "UPDATE runs SET config = ?",
            (
                json.dumps(
                    {
                        "pipeline": {"stages": {"emotions": "modelo-a"}},
                        "_emoparse": {"genre": {"genre_id": "articulo_periodistico"}},
                    }
                ),
            ),
        )
        connection.commit()
    finally:
        connection.close()

    overview = load_run_overview(path)

    assert overview.genre == "articulo_periodistico"
    assert overview.genre_source == "config_legacy"


def test_overview_preserves_latest_golden_and_control_reports(tmp_path: Path) -> None:
    path = tmp_path / "run.sqlite"
    _create_run(path, run_id="run", model="modelo-a")
    db = Database(path)
    reports = EvalReportsRepository(db)
    reports.insert(
        run_id="run",
        golden_version="v2",
        payload={"report_type": "golden", "metrics": {"f1": 0.8}},
    )
    reports.insert(
        run_id="run",
        golden_version="control",
        payload={"report_type": "control", "metrics": {"tasa": 0.5}},
    )
    db.close_thread_connection()

    overview = load_run_overview(path)

    assert set(overview.latest_reports) == {"golden", "control"}
    assert overview.latest_reports["golden"]["golden_version"] == "v2"
    assert overview.latest_reports["control"]["golden_version"] == "control"


def test_reference_classification_and_role_contract() -> None:
    assert classify_reference("Javier Milei", "javier milei") == "identico"
    assert (
        classify_reference(
            "el Presidente",
            "Javier Milei",
            left_canonical="javier_milei",
            right_canonical="javier_milei",
        )
        == "mismo_canonico"
    )
    assert classify_reference("Javier Milei", "Milei") == "solapamiento_parcial"
    assert classify_reference("Javier Milei", "la oposición") == "distinto"
    assert classify_reference(None, "Javier Milei") == "valor_ausente"
    assert is_role_label("el enunciador")
    assert not is_role_label("Javier Milei")


def test_compare_runs_uses_same_corpus_and_counts_contract_violations(tmp_path: Path) -> None:
    first = tmp_path / "modelo_a.sqlite"
    second = tmp_path / "modelo_b.sqlite"
    _create_run(first, run_id="a", model="modelo-a")
    _create_run(
        second,
        run_id="b",
        model="modelo-b",
        experiencer="el enunciador",
        experiencer_canonical="el_enunciador",
        source="medida económica",
        source_canonical="medida",
    )

    comparison = compare_runs([first, second])

    assert comparison.same_corpus is True
    assert comparison.common_units == 1
    assert {row["dimension"] for row in comparison.agreement} >= {
        "hay_emocion",
        "tipo",
        "experienciador",
        "fuente",
    }
    assert any(
        row["dimension"] == "fuente" and row["grado"] == "mismo_canonico"
        for row in comparison.reference_matches
    )
    assert any(
        row["run"] == "modelo_b"
        and row["dimension"] == "experienciador"
        and row["violaciones"] == 1
        for row in comparison.contract_violations
    )


def test_dashboard_registers_model_comparison_tab() -> None:
    main_path = Path(__file__).parents[2] / "src" / "emoparse" / "app" / "main.py"
    source = main_path.read_text(encoding="utf-8")

    assert '"🧪 Comparar modelos"' in source
    assert "tab_modelos.render(runs_dir, db_path)" in source
