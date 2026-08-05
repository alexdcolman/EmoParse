from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from emoparse.acquisition.context_satellite import build_context_satellite
from emoparse.acquisition.post_record import PostRecord
from emoparse.acquisition.sources.bluesky import BlueskyAdapter


def _write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
        encoding="utf-8",
    )


def test_context_satellite_keeps_origin_separate_and_types_relations(tmp_path: Path) -> None:
    source = tmp_path / "source.jsonl"
    _write_jsonl(
        source,
        [
            {
                "id": "at://origin/reply",
                "plataforma": "bluesky",
                "autor_handle": "ana.test",
                "texto": "respuesta",
                "tipo": "reply",
                "en_respuesta_a": "at://external/parent",
                "conversacion_id": "at://external/root",
                "cita_a": None,
                "reposteo_a": None,
            },
            {
                "id": "at://origin/quote",
                "plataforma": "bluesky",
                "autor_handle": "beto.test",
                "texto": "comentario",
                "tipo": "quote",
                "en_respuesta_a": None,
                "conversacion_id": None,
                "cita_a": "at://external/quote",
                "reposteo_a": None,
            },
        ],
    )
    available = {
        "at://external/parent": PostRecord(
            id="at://external/parent",
            plataforma="bluesky",
            autor_handle="padre.test",
            texto="post padre",
            tipo="reply",
            en_respuesta_a="at://external/root",
            conversacion_id="at://external/root",
        ),
        "at://external/root": PostRecord(
            id="at://external/root",
            plataforma="bluesky",
            autor_handle="raiz.test",
            texto="inicio del hilo",
        ),
        "at://external/quote": PostRecord(
            id="at://external/quote",
            plataforma="bluesky",
            autor_handle="citado.test",
            texto="post citado",
        ),
    }

    def fetch(ids: list[str]) -> list[PostRecord]:
        return [available[post_id] for post_id in ids if post_id in available]

    output = tmp_path / "context"
    result = build_context_satellite(
        source_jsonl=source,
        satellite_jsonl=output / "satellite.jsonl",
        links_jsonl=output / "links.jsonl",
        snapshot_jsonl=output / "snapshot.jsonl",
        manifest_json=output / "manifest.json",
        fetch_posts=fetch,
        max_parent_depth=5,
    )

    assert result.origin_posts == 2
    assert result.satellite_posts == 3
    assert result.links == 3
    satellite_ids = {
        json.loads(line)["id"]
        for line in (output / "satellite.jsonl").read_text(encoding="utf-8").splitlines()
    }
    assert satellite_ids == set(available)
    assert not satellite_ids.intersection({"at://origin/reply", "at://origin/quote"})

    snapshots = {
        row["codigo"]: row
        for row in (
            json.loads(line)
            for line in (output / "snapshot.jsonl").read_text(encoding="utf-8").splitlines()
        )
    }
    reply_relations = [item["relation"] for item in snapshots["at://origin/reply"]["contexts"]]
    assert reply_relations == ["reply_root", "reply_parent"]
    assert snapshots["at://origin/quote"]["contexts"][0]["relation"] == "quote"
    assert (
        json.loads((output / "manifest.json").read_text(encoding="utf-8"))["scope"][
            "downstream_replies_included"
        ]
        is False
    )


def test_context_satellite_records_unavailable_targets(tmp_path: Path) -> None:
    source = tmp_path / "source.jsonl"
    _write_jsonl(
        source,
        [
            {
                "id": "at://origin/1",
                "plataforma": "bluesky",
                "autor_handle": "ana.test",
                "texto": "respuesta",
                "en_respuesta_a": "at://missing/parent",
            }
        ],
    )
    output = tmp_path / "context"
    result = build_context_satellite(
        source_jsonl=source,
        satellite_jsonl=output / "satellite.jsonl",
        links_jsonl=output / "links.jsonl",
        snapshot_jsonl=output / "snapshot.jsonl",
        manifest_json=output / "manifest.json",
        fetch_posts=lambda _ids: [],
    )
    assert result.unresolved_links == 1
    item = json.loads((output / "snapshot.jsonl").read_text(encoding="utf-8"))["contexts"][0]
    assert item["status"] == "unavailable"
    assert item["target"] is None


def test_bluesky_fetch_posts_batches_and_deduplicates() -> None:
    calls: list[list[str]] = []

    class FakeFeed:
        def get_posts(self, params: dict[str, list[str]]) -> SimpleNamespace:
            uris = list(params["uris"])
            calls.append(uris)
            return SimpleNamespace(
                posts=[
                    PostRecord(
                        id=uri,
                        plataforma="bluesky",
                        autor_handle="autor.test",
                        texto=uri,
                    )
                    for uri in uris
                ]
            )

    adapter = object.__new__(BlueskyAdapter)
    adapter._client = SimpleNamespace(
        app=SimpleNamespace(
            bsky=SimpleNamespace(
                feed=FakeFeed(),
            )
        )
    )

    def as_record(post: PostRecord) -> PostRecord:
        return post

    adapter._map_post_view = as_record

    requested = [f"at://post/{index}" for index in range(27)]
    received = list(adapter.fetch_posts([*requested, requested[0], ""]))

    assert [len(batch) for batch in calls] == [25, 2]
    assert [post.id for post in received] == requested
