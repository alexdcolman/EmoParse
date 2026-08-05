"""Contratos de preparación de las bases ad hoc del golden v2."""

from __future__ import annotations

import argparse
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

import emoparse.cli.__main__ as cli_main
from emoparse.cli.commands import run_cmd
from emoparse.evaluation.corpus_validation import (
    CorpusValidationError,
    summarize_prepared_corpus,
    validate_golden_v2_corpus,
)
from emoparse.genres.articulo_periodistico import get_genre as get_articulo_genre
from emoparse.genres.discurso_presidencial import get_genre as get_discurso_genre
from emoparse.genres.presentation import attach_genre_presentation
from emoparse.genres.tuit import get_genre as get_tuit_genre
from emoparse.storage.db import Database
from emoparse.storage.models import RunContext
from emoparse.storage.runs import RunsRepository


def test_run_parser_exposes_prepare_only() -> None:
    parser = cli_main.build_parser()
    subparsers = next(
        action for action in parser._actions if isinstance(action, argparse._SubParsersAction)
    )
    args = subparsers.choices["run"].parse_args(
        [
            "--config",
            "config.yaml",
            "--input",
            "input.csv",
            "--run-id",
            "golden",
            "--prepare-only",
        ]
    )

    assert args.prepare_only is True


def test_prepare_only_ingests_and_chunks_without_stages(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    knowledge = tmp_path / "knowledge"
    knowledge.mkdir()
    config = SimpleNamespace(
        paths=SimpleNamespace(runs_dir=str(tmp_path), knowledge_dir=str(knowledge))
    )
    genre = get_discurso_genre()
    captured: dict[str, object] = {}

    class FakeRunner:
        def __init__(self, **kwargs: object) -> None:
            captured.update(kwargs)

        def __enter__(self) -> FakeRunner:
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def ingest(self, df: pd.DataFrame) -> None:
            captured["ingested"] = len(df)

        def ingest_posts(self, bundle: object) -> None:
            raise AssertionError("no debía ingerir posts")

        def chunk_into_frases(self) -> int:
            captured["chunked"] = True
            return 3

        def run(self) -> dict[str, int]:
            captured["ran"] = True
            return {}

    monkeypatch.setattr(run_cmd, "load_config", lambda _: config)
    monkeypatch.setattr(run_cmd, "get_genre", lambda _: genre)
    monkeypatch.setattr(
        run_cmd,
        "_load_input",
        lambda *_args, **_kwargs: (
            pd.DataFrame([{"codigo": "d1", "contenido": "Uno. Dos. Tres."}]),
            None,
        ),
    )
    monkeypatch.setattr(run_cmd, "KnowledgeLoader", lambda _: object())
    monkeypatch.setattr(run_cmd, "PipelineRunner", FakeRunner)
    monkeypatch.setattr(run_cmd, "_registrar_alcance", lambda *_: None)

    args = argparse.Namespace(
        config="config.yaml",
        genre="discurso_presidencial",
        input="input.csv",
        select=None,
        db=str(tmp_path / "golden.sqlite"),
        run_id="golden",
        stages=None,
        prepare_only=True,
        overwrite_db=False,
        resume=False,
        scope_enunciador=False,
        scope_enunciatarios=False,
        scope_actores=False,
        embed=False,
    )

    assert run_cmd.handle(args) == 0
    assert captured["enabled_stages"] == ()
    assert captured["ingested"] == 1
    assert captured["chunked"] is True
    assert captured["ran"] is True


def test_tuit_prepared_corpus_contract(tmp_path: Path) -> None:
    db_path = tmp_path / "tuit.sqlite"
    db = Database(db_path)
    genre = get_tuit_genre()
    config = attach_genre_presentation({}, genre)
    RunsRepository(db).bootstrap(RunContext(run_id="golden_v2_tuit", config=config))

    with db.transaction() as cursor:
        cursor.executemany(
            "INSERT INTO discursos (codigo, input) VALUES (?, ?)",
            [(f"p{i}", '{"contenido": "texto"}') for i in range(200)],
        )
        cursor.executemany(
            "INSERT INTO frases (codigo, unit_idx, frase) VALUES (?, 0, ?)",
            [(f"p{i}", "texto") for i in range(200)],
        )
        cursor.executemany(
            "INSERT INTO posts (post_id, plataforma, autor_handle, texto, "
            "conversacion_id, es_repost_puro) VALUES (?, 'bluesky', ?, ?, ?, 0)",
            [(f"p{i}", f"autor{i % 15}", "texto", f"conv{i}") for i in range(200)],
        )

    summary = summarize_prepared_corpus(db_path)
    validate_golden_v2_corpus(summary, expected_genre="tuit")

    assert summary.texts == 200
    assert summary.units == 200
    assert summary.authors == 15
    assert summary.analytical_outputs == 0


def test_prepared_corpus_rejects_analytical_outputs(tmp_path: Path) -> None:
    db_path = tmp_path / "articulo.sqlite"
    db = Database(db_path)
    genre = get_articulo_genre()
    config = attach_genre_presentation({}, genre)
    RunsRepository(db).bootstrap(RunContext(run_id="golden_v2_articulo", config=config))

    with db.transaction() as cursor:
        cursor.execute(
            "INSERT INTO discursos (codigo, input, summarizer_payload) VALUES (?, ?, ?)",
            ("a1", '{"contenido": "texto"}', "{}"),
        )
        cursor.executemany(
            "INSERT INTO frases (codigo, unit_idx, frase) VALUES ('a1', ?, 'texto')",
            [(i,) for i in range(80)],
        )

    summary = summarize_prepared_corpus(db_path)
    with pytest.raises(CorpusValidationError, match="salidas analíticas"):
        validate_golden_v2_corpus(summary, expected_genre="articulo_periodistico")


def test_article_prepared_corpus_accepts_genre_specific_minimum(tmp_path: Path) -> None:
    db_path = tmp_path / "articulo_minimo.sqlite"
    db = Database(db_path)
    config = attach_genre_presentation({}, get_articulo_genre())
    RunsRepository(db).bootstrap(RunContext(run_id="golden_v2_articulo", config=config))

    with db.transaction() as cursor:
        cursor.executemany(
            "INSERT INTO discursos (codigo, input) VALUES (?, ?)",
            [(f"a{i}", '{"contenido": "texto"}') for i in range(30)],
        )
        cursor.executemany(
            "INSERT INTO frases (codigo, unit_idx, frase) VALUES (?, ?, ?)",
            [
                (f"a{document}", unit, "texto")
                for document in range(30)
                for unit in range(3)
                if document * 3 + unit < 80
            ],
        )

    summary = summarize_prepared_corpus(db_path)
    validate_golden_v2_corpus(summary, expected_genre="articulo_periodistico")

    assert summary.texts == 30
    assert summary.units == 80


def test_article_prepared_corpus_rejects_below_genre_specific_minimum(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "articulo_insuficiente.sqlite"
    db = Database(db_path)
    config = attach_genre_presentation({}, get_articulo_genre())
    RunsRepository(db).bootstrap(RunContext(run_id="golden_v2_articulo", config=config))

    with db.transaction() as cursor:
        cursor.executemany(
            "INSERT INTO discursos (codigo, input) VALUES (?, ?)",
            [(f"a{i}", '{"contenido": "texto"}') for i in range(30)],
        )
        cursor.executemany(
            "INSERT INTO frases (codigo, unit_idx, frase) VALUES (?, ?, ?)",
            [(f"a{i % 30}", i // 30, "texto") for i in range(79)],
        )

    summary = summarize_prepared_corpus(db_path)
    with pytest.raises(CorpusValidationError, match="al menos 80"):
        validate_golden_v2_corpus(summary, expected_genre="articulo_periodistico")


def test_longform_prepared_corpus_contract(tmp_path: Path) -> None:
    db_path = tmp_path / "discurso.sqlite"
    db = Database(db_path)
    config = attach_genre_presentation({}, get_discurso_genre())
    RunsRepository(db).bootstrap(RunContext(run_id="golden_v2_discurso", config=config))

    with db.transaction() as cursor:
        cursor.executemany(
            "INSERT INTO discursos (codigo, input) VALUES (?, ?)",
            [(f"d{i}", '{"contenido": "texto"}') for i in range(24)],
        )
        cursor.executemany(
            "INSERT INTO frases (codigo, unit_idx, frase) VALUES (?, ?, ?)",
            [(f"d{document}", unit, "texto") for document in range(24) for unit in range(9)],
        )

    summary = summarize_prepared_corpus(db_path)
    validate_golden_v2_corpus(summary, expected_genre="discurso_presidencial")

    assert summary.texts == 24
    assert summary.units == 216
    assert summary.analytical_outputs == 0


def test_merge_csv_corpus_is_deduplicated_and_capped(tmp_path: Path) -> None:
    from scripts.merge_golden_v2_csv import merge_csv_corpus

    corpus = tmp_path / "corpus.csv"
    candidate = tmp_path / "candidate.csv"
    corpus.write_text(
        "codigo,url,titulo,fecha,contenido,fuente\n"
        "a1,https://example/a,Uno,2026-01-01,Texto,fuente\n",
        encoding="utf-8",
    )
    candidate.write_text(
        "codigo,url,titulo,fecha,contenido,fuente\n"
        "a1,https://example/a,Uno,2026-01-01,Texto,fuente\n"
        "a2,https://example/b,Dos,2026-01-02,Texto,fuente\n"
        "a3,https://example/c,Tres,2026-01-03,Texto,fuente\n",
        encoding="utf-8",
    )

    total = merge_csv_corpus(corpus, candidate, target=2)
    rows = pd.read_csv(corpus)

    assert total == 2
    assert rows["url"].tolist() == ["https://example/a", "https://example/b"]


def test_prepare_script_uses_genre_specific_document_targets() -> None:
    script = Path("scripts/prepare_golden_v2_corpora.sh").read_text(encoding="utf-8")

    assert 'TARGET_ARTICLE_DOCUMENTS="${TARGET_ARTICLE_DOCUMENTS:-30}"' in script
    assert 'TARGET_SPEECH_DOCUMENTS="${TARGET_SPEECH_DOCUMENTS:-24}"' in script
    assert (
        'PAGINA12_CANDIDATES="${PAGINA12_CANDIDATES:-$((TARGET_ARTICLE_DOCUMENTS * 2))}"' in script
    )
    assert (
        'pagina12 "$ARTICULO_INPUT" http "$TARGET_ARTICLE_DOCUMENTS" '
        '"$PAGINA12_CANDIDATES"' in script
    )
    assert (
        'casarosada "$DISCURSO_INPUT" auto "$TARGET_SPEECH_DOCUMENTS" '
        '"$TARGET_SPEECH_DOCUMENTS"' in script
    )


def test_article_refresh_keeps_existing_rows_when_coverage_is_sufficient() -> None:
    from scripts.refresh_golden_v2_articles import coverage, refresh_rows

    paragraph = "Párrafo con extensión suficiente para ser una unidad del corpus."
    rows = [
        {
            "codigo": f"a{i}",
            "url": f"https://example/{i}",
            "contenido": "\n\n".join(paragraph for _ in range(9)),
        }
        for i in range(24)
    ]

    class FakeRecord:
        def __init__(self, row: dict[str, str]) -> None:
            self.row = row

        def to_dict(self) -> dict[str, object]:
            return self.row

    class FakeAdapter:
        def fetch_discurso(self, url: str) -> FakeRecord:
            row = next(row for row in rows if row["url"] == url)
            return FakeRecord(row)

        def list_discursos(self, *, max_items: int | None = None):
            raise AssertionError("no debía descubrir notas adicionales")

    refreshed = refresh_rows(
        rows,
        adapter=FakeAdapter(),
        min_units=80,
        max_documents=30,
        discovery_limit=60,
    )

    assert coverage(refreshed) == (24, 216)


def test_article_refresh_adds_documents_until_reaching_coverage() -> None:
    from scripts.refresh_golden_v2_articles import coverage, refresh_rows

    paragraph = "Párrafo con extensión suficiente para ser una unidad del corpus."
    rows = [
        {
            "codigo": f"a{i}",
            "url": f"https://example/{i}",
            "contenido": "\n\n".join(paragraph for _ in range(3)),
        }
        for i in range(24)
    ]
    extras = [
        {
            "codigo": f"x{i}",
            "url": f"https://example/extra/{i}",
            "contenido": "\n\n".join(paragraph for _ in range(8)),
        }
        for i in range(4)
    ]
    by_url = {row["url"]: row for row in [*rows, *extras]}

    class FakeRecord:
        def __init__(self, row: dict[str, str]) -> None:
            self.row = row

        def to_dict(self) -> dict[str, object]:
            return self.row

    class FakeAdapter:
        def fetch_discurso(self, url: str) -> FakeRecord:
            return FakeRecord(by_url[url])

        def list_discursos(self, *, max_items: int | None = None):
            return iter(row["url"] for row in extras[: max_items or len(extras)])

    refreshed = refresh_rows(
        rows,
        adapter=FakeAdapter(),
        min_units=80,
        max_documents=30,
        discovery_limit=60,
    )

    assert coverage(refreshed) == (25, 80)


def test_article_refresh_replaces_with_backup(tmp_path: Path) -> None:
    from scripts.refresh_golden_v2_articles import replace_with_backup

    corpus = tmp_path / "articulo.csv"
    db = tmp_path / "articulo.sqlite"
    new_corpus = tmp_path / "nuevo.csv"
    new_db = tmp_path / "nuevo.sqlite"
    corpus.write_text("viejo corpus", encoding="utf-8")
    db.write_bytes(b"vieja db")
    new_corpus.write_text("nuevo corpus", encoding="utf-8")
    new_db.write_bytes(b"nueva db")

    backup = replace_with_backup(
        project=tmp_path,
        corpus=corpus,
        db=db,
        new_corpus=new_corpus,
        new_db=new_db,
    )

    assert corpus.read_text(encoding="utf-8") == "nuevo corpus"
    assert db.read_bytes() == b"nueva db"
    assert (backup / corpus.name).read_text(encoding="utf-8") == "viejo corpus"
    assert (backup / db.name).read_bytes() == b"vieja db"
