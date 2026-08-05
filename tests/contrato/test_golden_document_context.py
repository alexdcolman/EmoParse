from __future__ import annotations

import csv
import json
import sqlite3
from pathlib import Path

from emoparse.evaluation.document_context import build_document_context_snapshot


def _database(path: Path, *, genre: str, article: bool) -> None:
    connection = sqlite3.connect(path)
    connection.executescript(
        """
        CREATE TABLE runs (config TEXT);
        CREATE TABLE discursos (codigo TEXT PRIMARY KEY, input TEXT NOT NULL);
        CREATE TABLE frases (
            codigo TEXT NOT NULL,
            unit_idx INTEGER NOT NULL,
            frase TEXT NOT NULL,
            PRIMARY KEY (codigo, unit_idx)
        );
        """
    )
    config = {"_emoparse": {"genre": {"genre_id": genre}}}
    connection.execute("INSERT INTO runs VALUES (?)", (json.dumps(config),))
    payload = {
        "titulo": "Título de prueba",
        "fecha": "2026-08-04",
        "fuente": "fuente",
        "url": "https://example.test/doc",
    }
    if article:
        payload.update(
            {
                "medio": "Medio",
                "seccion": "Política",
                "autoria": '["Autora"]',
            }
        )
    connection.execute("INSERT INTO discursos VALUES (?, ?)", ("doc-1", json.dumps(payload)))
    connection.executemany(
        "INSERT INTO frases VALUES (?, ?, ?)",
        [("doc-1", index, f"Unidad {index}") for index in range(1, 6)],
    )
    connection.commit()
    connection.close()


def _sample(path: Path, *, genre: str, indexes: tuple[int, ...]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["genero", "codigo", "unit_idx", "texto"])
        writer.writeheader()
        for index in indexes:
            writer.writerow(
                {
                    "genero": genre,
                    "codigo": "doc-1",
                    "unit_idx": index,
                    "texto": f"Unidad {index}",
                }
            )


def test_article_context_preserves_metadata_and_neighbours(tmp_path: Path) -> None:
    database = tmp_path / "article.sqlite"
    sample = tmp_path / "article.csv"
    snapshot = tmp_path / "article.jsonl"
    manifest = tmp_path / "article.manifest.json"
    _database(database, genre="articulo_periodistico", article=True)
    _sample(sample, genre="articulo_periodistico", indexes=(1, 3))

    result = build_document_context_snapshot(
        db_path=database,
        sample_csv=sample,
        snapshot_jsonl=snapshot,
        manifest_json=manifest,
        genre="articulo_periodistico",
        previous_units=1,
        next_units=1,
    )

    rows = [json.loads(line) for line in snapshot.read_text(encoding="utf-8").splitlines()]
    assert result.units == 2
    assert rows[0]["unit_idx"] == 1
    assert [item["relation"] for item in rows[0]["contexts"]] == [
        "document_metadata",
        "next_unit",
    ]
    assert "Medio: Medio" in rows[0]["contexts"][0]["target"]["texto"]
    assert [item["relation"] for item in rows[1]["contexts"]] == [
        "document_metadata",
        "previous_unit",
        "next_unit",
    ]


def test_discourse_context_uses_two_previous_sentences(tmp_path: Path) -> None:
    database = tmp_path / "discourse.sqlite"
    sample = tmp_path / "discourse.csv"
    snapshot = tmp_path / "discourse.jsonl"
    manifest = tmp_path / "discourse.manifest.json"
    _database(database, genre="discurso_presidencial", article=False)
    _sample(sample, genre="discurso_presidencial", indexes=(4,))

    result = build_document_context_snapshot(
        db_path=database,
        sample_csv=sample,
        snapshot_jsonl=snapshot,
        manifest_json=manifest,
        genre="discurso_presidencial",
        previous_units=2,
        next_units=1,
    )

    row = json.loads(snapshot.read_text(encoding="utf-8"))
    assert result.previous_items == 2
    assert [item["depth"] for item in row["contexts"] if item["relation"] == "previous_unit"] == [
        2,
        1,
    ]
    assert row["contexts"][-1]["relation"] == "next_unit"
    assert row["contexts"][-1]["target"]["texto"] == "Unidad 5"
