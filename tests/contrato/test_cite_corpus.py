from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path

from emoparse.acquisition.post_record import PostRecord
from emoparse.cli.commands import cite_corpus_cmd
from emoparse.storage.db import Database
from emoparse.storage.discursos import DiscursosRepository
from emoparse.storage.models import RunContext
from emoparse.storage.posts import PostsRepository
from emoparse.storage.runs import RunsRepository


class FakeAdapter:
    source_id = "bluesky"

    def __init__(self, records: dict[str, PostRecord]) -> None:
        self.records = records
        self.requests: list[list[str]] = []

    def __enter__(self) -> FakeAdapter:
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def fetch_posts(self, post_ids: list[str]):
        self.requests.append(list(post_ids))
        for post_id in post_ids:
            if post_id in self.records:
                yield self.records[post_id]


def _origin_db(path: Path, rows: list[dict[str, object]]) -> None:
    db = Database(path)
    RunsRepository(db).bootstrap(RunContext(run_id="origin-run"))
    PostsRepository(db).upsert_posts(rows)
    DiscursosRepository(db).upsert_inputs(
        [
            (
                str(row["post_id"]),
                {"contenido": str(row.get("texto") or ""), "fuente": "bluesky"},
            )
            for row in rows
            if str(row.get("texto") or "").strip()
        ]
    )
    with db.transaction() as cur:
        cur.execute(
            "INSERT INTO run_metrics (run_id, stage_name, n_items_ok) VALUES (?, ?, ?)",
            ("origin-run", "seed", 1),
        )
    db.close_thread_connection()


def _row(post_id: str, **overrides: object) -> dict[str, object]:
    row: dict[str, object] = {
        "post_id": post_id,
        "plataforma": "bluesky",
        "autor_handle": "origin.bsky.social",
        "texto": f"texto {post_id}",
        "tipo": "original",
        "conversacion_id": post_id,
    }
    row.update(overrides)
    return row


def _record(post_id: str, **overrides: object) -> PostRecord:
    values: dict[str, object] = {
        "id": post_id,
        "plataforma": "bluesky",
        "autor_handle": "sat.bsky.social",
        "texto": f"texto {post_id}",
        "tipo": "original",
        "conversacion_id": post_id,
    }
    values.update(overrides)
    return PostRecord(**values)  # type: ignore[arg-type]


def _args(db: Path, out: Path, **overrides: object) -> argparse.Namespace:
    values: dict[str, object] = {
        "db": db,
        "source": "bluesky",
        "out": out,
        "profundidad": 1,
        "max_items": None,
        "timeout": 20.0,
    }
    values.update(overrides)
    return argparse.Namespace(**values)


def _snapshot_origin(path: Path) -> dict[str, list[tuple[object, ...]]]:
    conn = sqlite3.connect(path)
    try:
        return {
            table: conn.execute(f"SELECT * FROM {table} ORDER BY 1").fetchall()
            for table in ("posts", "discursos", "run_metrics")
        }
    finally:
        conn.close()


def test_cite_corpus_creates_separate_satellite_and_only_registers_origin(tmp_path, monkeypatch):
    origin = tmp_path / "origin.sqlite"
    satellite = tmp_path / "sat.sqlite"
    _origin_db(origin, [_row("o1", cita_a="s1", tipo="quote")])
    before = _snapshot_origin(origin)
    fake = FakeAdapter({"s1": _record("s1")})
    monkeypatch.setattr(cite_corpus_cmd, "get_post_source", lambda *_a, **_k: fake)

    assert cite_corpus_cmd.handle(_args(origin, satellite)) == 0
    assert satellite.is_file()
    assert _snapshot_origin(origin) == before

    conn = sqlite3.connect(origin)
    try:
        reg = conn.execute(
            "SELECT source_id, marco, profundidad, satellite_path FROM satelites"
        ).fetchone()
        assert reg == ("bluesky", "bola_de_nieve", 1, str(satellite.resolve()))
    finally:
        conn.close()

    conn = sqlite3.connect(satellite)
    try:
        assert conn.execute("SELECT post_id FROM posts").fetchall() == [("s1",)]
        assert conn.execute("SELECT codigo FROM discursos").fetchall() == [("s1",)]
        assert conn.execute("SELECT marco FROM runs").fetchone() == ("bola_de_nieve",)
        link = conn.execute(
            "SELECT origin_post_id, relation, status, target_location FROM corpus_vinculos"
        ).fetchone()
        assert link == ("o1", "quote", "resolved", "satellite")
    finally:
        conn.close()


def test_cite_corpus_records_unavailable_without_inventing_post(tmp_path, monkeypatch):
    origin = tmp_path / "origin.sqlite"
    satellite = tmp_path / "sat.sqlite"
    _origin_db(origin, [_row("o1", cita_a="missing", tipo="quote")])
    fake = FakeAdapter({})
    monkeypatch.setattr(cite_corpus_cmd, "get_post_source", lambda *_a, **_k: fake)

    assert cite_corpus_cmd.handle(_args(origin, satellite)) == 0
    conn = sqlite3.connect(satellite)
    try:
        assert conn.execute("SELECT COUNT(*) FROM posts").fetchone() == (0,)
        assert conn.execute(
            "SELECT status, target_location FROM corpus_vinculos"
        ).fetchone() == ("unavailable", "external")
    finally:
        conn.close()


def test_cite_corpus_max_marks_remaining_targets_without_fetch(tmp_path, monkeypatch):
    origin = tmp_path / "origin.sqlite"
    satellite = tmp_path / "sat.sqlite"
    _origin_db(
        origin,
        [_row("o1", en_respuesta_a="a", cita_a="b", tipo="quote", conversacion_id="o1")],
    )
    fake = FakeAdapter({"a": _record("a"), "b": _record("b")})
    monkeypatch.setattr(cite_corpus_cmd, "get_post_source", lambda *_a, **_k: fake)

    assert cite_corpus_cmd.handle(_args(origin, satellite, max_items=1)) == 0
    assert fake.requests == [["a"]]
    conn = sqlite3.connect(satellite)
    try:
        assert conn.execute("SELECT post_id FROM posts").fetchall() == [("a",)]
        statuses = dict(conn.execute("SELECT target_post_id, status FROM corpus_vinculos"))
        assert statuses == {"a": "resolved", "b": "limit_reached"}
    finally:
        conn.close()


def test_cite_corpus_depth_two_follows_context_of_acquired_post(tmp_path, monkeypatch):
    origin = tmp_path / "origin.sqlite"
    satellite = tmp_path / "sat.sqlite"
    _origin_db(origin, [_row("o1", cita_a="s1", tipo="quote")])
    fake = FakeAdapter(
        {
            "s1": _record("s1", en_respuesta_a="s2", tipo="reply", conversacion_id="thread-x"),
            "s2": _record("s2", conversacion_id="thread-x"),
            "thread-x": _record("thread-x"),
        }
    )
    monkeypatch.setattr(cite_corpus_cmd, "get_post_source", lambda *_a, **_k: fake)

    assert cite_corpus_cmd.handle(_args(origin, satellite, profundidad=2)) == 0
    conn = sqlite3.connect(satellite)
    try:
        ids = {row[0] for row in conn.execute("SELECT post_id FROM posts")}
        assert ids == {"s1", "s2", "thread-x"}
        gen2 = conn.execute(
            "SELECT relation, target_post_id FROM corpus_vinculos "
            "WHERE origin_post_id='o1' AND generation=2 ORDER BY relation, target_post_id"
        ).fetchall()
        assert ("reply_ancestor", "s2") in gen2
        assert ("reply_root", "thread-x") in gen2
    finally:
        conn.close()


def test_cite_corpus_rejects_invalid_depth_before_source_lookup(tmp_path, monkeypatch):
    origin = tmp_path / "origin.sqlite"
    _origin_db(origin, [_row("o1")])
    called = False

    def _unexpected(*_a, **_k):
        nonlocal called
        called = True
        raise AssertionError

    monkeypatch.setattr(cite_corpus_cmd, "get_post_source", _unexpected)
    assert cite_corpus_cmd.handle(_args(origin, tmp_path / "sat.sqlite", profundidad=0)) == 2
    assert called is False
