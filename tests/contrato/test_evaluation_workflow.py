"""Contratos del flujo de anotación y golden set multigénero."""

from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path

import pandas as pd
import pytest

from emoparse.cli.__main__ import build_parser
from emoparse.cli.commands import eval_cmd
from emoparse.evaluation.annotations import (
    ANNOTATION_COLUMNS,
    AnnotationError,
    freeze_annotations,
    make_reannotation_sample,
)
from emoparse.evaluation.golden import load_golden_dataset
from emoparse.evaluation.matching import match_units
from emoparse.evaluation.sampling import make_annotation_sample


def _create_run_db(path: Path, genre: str, prefix: str, *, documents: int = 4) -> None:
    conn = sqlite3.connect(path)
    try:
        conn.executescript(
            """
            CREATE TABLE runs (config TEXT);
            CREATE TABLE frases (codigo TEXT, unit_idx INTEGER, frase TEXT);
            CREATE TABLE emociones (
                codigo TEXT,
                frase_idx INTEGER,
                emocion_idx INTEGER,
                experienciador TEXT,
                experienciador_canonico TEXT,
                tipo_emocion TEXT,
                tipo_emocion_canonico TEXT,
                fuente_inferencia TEXT,
                fuente_canonico TEXT,
                modo_existencia TEXT,
                caracterizacion_payload TEXT
            );
            """
        )
        config = {
            "_emoparse": {
                "genre": {
                    "genre_id": genre,
                    "display_name": genre,
                    "input_metadata": [],
                }
            }
        }
        conn.execute("INSERT INTO runs(config) VALUES (?)", (json.dumps(config),))
        for document in range(documents):
            code = f"{prefix}-{document}"
            for unit_idx in range(2):
                conn.execute(
                    "INSERT INTO frases VALUES (?, ?, ?)",
                    (code, unit_idx, f"Texto {code} unidad {unit_idx}"),
                )
                if (document + unit_idx) % 2 == 0:
                    conn.execute(
                        "INSERT INTO emociones VALUES (?, ?, 0, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (
                            code,
                            unit_idx,
                            "autor",
                            "autor",
                            "ira",
                            "ira",
                            "medida",
                            "medida",
                            "realizada",
                            json.dumps({"foria": "disforico"}),
                        ),
                    )
        conn.commit()
    finally:
        conn.close()


def _completed_sample_row() -> dict[str, str | int]:
    row: dict[str, str | int] = {
        "id_muestra": "u0001",
        "genero": "tuit",
        "codigo": "post-1",
        "unit_idx": 0,
        "contexto": "",
        "texto": "Me indigna esta medida.",
        **{column: "" for column in ANNOTATION_COLUMNS},
    }
    row.update(
        {
            "anotador": "autor",
            "pasada": "1",
            "fecha_anotacion": "2026-08-03",
            "hay_emocion": "si",
            "emocion_1_experienciador": "autor",
            "emocion_1_tipo": "indignación",
            "emocion_1_fuente": "esta medida",
            "emocion_1_modo_existencia": "realizada",
            "emocion_1_foria": "disforico",
        }
    )
    return row


def test_make_sample_is_blind_diverse_and_complete(tmp_path: Path) -> None:
    db = tmp_path / "run.sqlite"
    _create_run_db(db, "discurso_presidencial", "d", documents=4)

    frame = make_annotation_sample(
        db,
        n=6,
        seed=7,
        min_texts=3,
        max_per_text=2,
    )

    assert len(frame) == 6
    assert frame["genero"].unique().tolist() == ["discurso_presidencial"]
    assert frame["codigo"].nunique() >= 3
    assert set(ANNOTATION_COLUMNS).issubset(frame.columns)
    assert all((frame[column] == "").all() for column in ANNOTATION_COLUMNS)
    assert "tipo_emocion" not in frame.columns
    assert "fuente_inferencia" not in frame.columns


def test_freeze_annotations_writes_full_simulacrum_metadata(tmp_path: Path) -> None:
    csv_path = tmp_path / "sample.csv"
    pd.DataFrame([_completed_sample_row()]).to_csv(csv_path, index=False)

    records = freeze_annotations(
        csv_path,
        annotator="autor",
        pass_number=1,
        annotation_date="2026-08-03",
    )

    assert records[0]["genero"] == "tuit"
    assert records[0]["anotadores"] == ["autor"]
    assert records[0]["pasadas"] == [1]
    assert records[0]["emociones"] == [
        {
            "experienciador": "autor",
            "tipo_emocion": "indignación",
            "fuente": "esta medida",
            "modo_existencia": "realizada",
            "foria": "disforico",
        }
    ]


def test_freeze_annotations_rejects_partial_emotion(tmp_path: Path) -> None:
    row = _completed_sample_row()
    row["emocion_1_fuente"] = ""
    csv_path = tmp_path / "sample.csv"
    pd.DataFrame([row]).to_csv(csv_path, index=False)

    with pytest.raises(AnnotationError, match="faltan fuente"):
        freeze_annotations(
            csv_path,
            annotator="autor",
            pass_number=1,
            annotation_date="2026-08-03",
        )


def test_reannotation_preserves_units_and_clears_answers(tmp_path: Path) -> None:
    rows = []
    for index in range(4):
        row = _completed_sample_row()
        row["id_muestra"] = f"u{index + 1:04d}"
        row["codigo"] = f"post-{index + 1}"
        rows.append(row)
    csv_path = tmp_path / "sample.csv"
    pd.DataFrame(rows).to_csv(csv_path, index=False)

    retest = make_reannotation_sample(csv_path, n=3, seed=9)

    assert len(retest) == 3
    assert set(retest["id_muestra"]).issubset({row["id_muestra"] for row in rows})
    assert (retest["pasada"] == "2").all()
    for column in ANNOTATION_COLUMNS:
        if column != "pasada":
            assert (retest[column] == "").all()


def test_golden_dataset_preserves_genre_and_source_is_scored(tmp_path: Path) -> None:
    golden_path = tmp_path / "golden.jsonl"
    golden_path.write_text(
        json.dumps(
            {
                "codigo": "x",
                "unit_idx": 0,
                "genero": "tuit",
                "emociones": [
                    {
                        "tipo_emocion": "ira",
                        "experienciador": "autor",
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

    dataset = load_golden_dataset(golden_path)
    report = match_units(
        dataset.units,
        {
            ("x", 0): [
                {
                    "tipo_emocion_canonico": "ira",
                    "experienciador_canonico": "autor",
                    "fuente_canonico": "la medida",
                    "modo_existencia": "realizada",
                    "foria": "disforico",
                }
            ]
        },
    )

    assert dataset.genres_present() == ("tuit",)
    assert report.dim_accuracy("fuente") == 1.0


def test_eval_golden_accepts_one_db_per_genre(tmp_path: Path) -> None:
    tuit_db = tmp_path / "tuit.sqlite"
    article_db = tmp_path / "article.sqlite"
    _create_run_db(tuit_db, "tuit", "t", documents=1)
    _create_run_db(article_db, "articulo_periodistico", "a", documents=1)
    golden_dir = tmp_path / "golden"
    golden_dir.mkdir()
    (golden_dir / "tuit.jsonl").write_text(
        json.dumps(
            {
                "codigo": "t-0",
                "unit_idx": 0,
                "genero": "tuit",
                "emociones": [
                    {
                        "tipo_emocion": "ira",
                        "experienciador": "autor",
                        "fuente": "medida",
                        "modo_existencia": "realizada",
                        "foria": "disforico",
                    }
                ],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    (golden_dir / "article.jsonl").write_text(
        json.dumps(
            {
                "codigo": "a-0",
                "unit_idx": 0,
                "genero": "articulo_periodistico",
                "emociones": [
                    {
                        "tipo_emocion": "ira",
                        "experienciador": "autor",
                        "fuente": "medida",
                        "modo_existencia": "realizada",
                        "foria": "disforico",
                    }
                ],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    output = tmp_path / "report.md"
    parser = build_parser()
    args = parser.parse_args(
        [
            "eval",
            "--golden",
            str(golden_dir),
            "--por-genero",
            "--db",
            str(tuit_db),
            "--db",
            str(article_db),
            "--out",
            str(output),
        ]
    )

    assert args.handler(args) == 0
    report = output.read_text(encoding="utf-8")
    assert "Género: `tuit`" in report
    assert "Género: `articulo_periodistico`" in report
    assert "| fuente |" in report


def test_agreement_treats_passes_as_distinct_coders(tmp_path: Path) -> None:
    rows = []
    for pass_number in (1, 2):
        for index, emotion in enumerate(("si", "no"), start=1):
            row = _completed_sample_row()
            row["id_muestra"] = f"u{index:04d}"
            row["pasada"] = str(pass_number)
            row["hay_emocion"] = emotion
            if emotion == "no":
                for column in ANNOTATION_COLUMNS:
                    if column.startswith("emocion_"):
                        row[column] = ""
            rows.append(row)
    csv_path = tmp_path / "agreement.csv"
    pd.DataFrame(rows).to_csv(csv_path, index=False)
    output = tmp_path / "agreement.md"
    args = argparse.Namespace(agreement=csv_path, out=output)

    assert eval_cmd._agreement(args) == 0
    report = output.read_text(encoding="utf-8")
    assert "autor/pasada-1" in report
    assert "autor/pasada-2" in report
    assert "| fuente | nominal |" in report


def test_freeze_uses_per_row_metadata_without_cli_overrides(tmp_path: Path) -> None:
    row = _completed_sample_row()
    row["anotador"] = "alex"
    row["pasada"] = "2"
    row["fecha_anotacion"] = "2026-08-17"
    row["emocion_1_foria"] = "aforico"
    csv_path = tmp_path / "sample.csv"
    pd.DataFrame([row]).to_csv(csv_path, index=False)

    records = freeze_annotations(csv_path)

    assert records[0]["anotadores"] == ["alex"]
    assert records[0]["pasadas"] == [2]
    assert records[0]["fecha"] == "2026-08-17"
    assert records[0]["emociones"][0]["foria"] == "aforico"


def test_reannotation_rejects_unfinished_first_pass(tmp_path: Path) -> None:
    complete = _completed_sample_row()
    pending = _completed_sample_row()
    pending["id_muestra"] = "u0002"
    pending["codigo"] = "post-2"
    pending["hay_emocion"] = ""
    csv_path = tmp_path / "sample.csv"
    pd.DataFrame([complete, pending]).to_csv(csv_path, index=False)

    with pytest.raises(AnnotationError, match="todavía tiene 1 unidades"):
        make_reannotation_sample(csv_path, n=1, seed=9)


def test_source_match_alone_does_not_create_true_positive() -> None:
    report = match_units(
        {
            ("x", 0): [
                {
                    "tipo_emocion": "miedo",
                    "experienciador": "auditorio",
                    "fuente": "la medida",
                }
            ]
        },
        {
            ("x", 0): [
                {
                    "tipo_emocion_canonico": "alegría",
                    "experienciador_canonico": "autor",
                    "fuente_canonico": "la medida",
                }
            ]
        },
    )

    assert report.tp == 0
    assert report.fp == 1
    assert report.fn == 1


def test_agreement_rejects_missing_decision_column(tmp_path: Path) -> None:
    rows = []
    for pass_number in (1, 2):
        row = _completed_sample_row()
        row["pasada"] = str(pass_number)
        rows.append(row)
    frame = pd.DataFrame(rows).drop(columns=["emocion_1_fuente"])
    csv_path = tmp_path / "agreement.csv"
    frame.to_csv(csv_path, index=False)
    output = tmp_path / "agreement.md"
    args = argparse.Namespace(agreement=csv_path, out=output)

    assert eval_cmd._agreement(args) == 1
    assert not output.exists()
