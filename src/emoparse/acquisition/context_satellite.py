"""Construcción determinista de contexto externo para corpus de posts.

Este módulo no ejecuta stages ni mezcla el corpus origen con los posts usados
como contexto. Produce un satélite normalizado, vínculos tipados y una instantánea
por unidad apta para el servicio de anotación.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from emoparse.acquisition.post_record import PostRecord

FetchPosts = Callable[[list[str]], Iterable[PostRecord]]


@dataclass(frozen=True)
class ContextBuildResult:
    origin_posts: int
    origins_with_context: int
    satellite_posts: int
    links: int
    unresolved_links: int
    source_sha256: str
    satellite_sha256: str
    links_sha256: str
    snapshot_sha256: str


def build_context_satellite(
    *,
    source_jsonl: Path,
    satellite_jsonl: Path,
    links_jsonl: Path,
    snapshot_jsonl: Path,
    manifest_json: Path,
    fetch_posts: FetchPosts,
    max_parent_depth: int = 5,
) -> ContextBuildResult:
    """Construye contexto de padres, raíz, cita y repost para un corpus.

    Los posts del corpus origen nunca se copian al satélite. Los vínculos pueden
    apuntar al propio corpus (`source=origin`) o a posts adquiridos en el
    satélite (`source=satellite`). Las referencias no resolubles quedan
    registradas con `status=unavailable`.
    """
    if max_parent_depth < 1:
        raise ValueError("`max_parent_depth` debe ser mayor o igual que 1")
    source_raw = source_jsonl.read_bytes()
    origin = _load_jsonl(source_jsonl)
    by_id = {str(row["id"]): row for row in origin}
    if len(by_id) != len(origin):
        raise ValueError("el corpus origen contiene ids duplicados")
    platforms = {str(row.get("plataforma") or "") for row in origin}
    if platforms != {"bluesky"}:
        raise ValueError("7.1A solo admite corpus de Bluesky")

    external: dict[str, dict[str, Any]] = {}
    unavailable: set[str] = set()

    def resolve(ids: Iterable[str]) -> None:
        requested = sorted(
            {
                post_id
                for post_id in ids
                if post_id
                and post_id not in by_id
                and post_id not in external
                and post_id not in unavailable
            }
        )
        for start in range(0, len(requested), 25):
            batch = requested[start : start + 25]
            received = {record.id: record.to_json_dict() for record in fetch_posts(batch)}
            external.update(received)
            unavailable.update(set(batch) - set(received))

    seeds: set[str] = set()
    for row in origin:
        seeds.update(_direct_reference_ids(row))
    resolve(seeds)

    parent_paths: dict[str, list[str]] = {}
    for origin_id, row in by_id.items():
        current = _clean(row.get("en_respuesta_a"))
        chain: list[str] = []
        seen = {origin_id}
        for _depth in range(max_parent_depth):
            if not current or current in seen:
                break
            seen.add(current)
            chain.append(current)
            resolve([current])
            target = by_id.get(current) or external.get(current)
            if target is None:
                break
            current = _clean(target.get("en_respuesta_a"))
        parent_paths[origin_id] = chain

    links: list[dict[str, Any]] = []
    snapshots: list[dict[str, Any]] = []
    origins_with_context = 0

    for origin_id, row in by_id.items():
        items: list[dict[str, Any]] = []
        chain = parent_paths[origin_id]
        root_id = _clean(row.get("conversacion_id"))

        if root_id and root_id not in chain and root_id != origin_id:
            resolve([root_id])
            items.append(
                _context_item(
                    origin_id=origin_id,
                    relation="reply_root",
                    depth=None,
                    target_id=root_id,
                    origin=by_id,
                    satellite=external,
                )
            )

        for depth, target_id in reversed(list(enumerate(chain, start=1))):
            if depth == 1:
                relation = "reply_parent"
            elif target_id == root_id:
                relation = "reply_root"
            else:
                relation = "reply_ancestor"
            items.append(
                _context_item(
                    origin_id=origin_id,
                    relation=relation,
                    depth=depth,
                    target_id=target_id,
                    origin=by_id,
                    satellite=external,
                )
            )

        for field, relation in (("cita_a", "quote"), ("reposteo_a", "repost")):
            target_id = _clean(row.get(field))
            if not target_id:
                continue
            resolve([target_id])
            items.append(
                _context_item(
                    origin_id=origin_id,
                    relation=relation,
                    depth=None,
                    target_id=target_id,
                    origin=by_id,
                    satellite=external,
                )
            )

        if items:
            origins_with_context += 1
        for position, item in enumerate(items, start=1):
            item["position"] = position
            links.append({key: value for key, value in item.items() if key != "target"})
        snapshots.append(
            {
                "codigo": origin_id,
                "plataforma": "bluesky",
                "contexts": items,
            }
        )

    satellite_rows = [external[key] for key in sorted(external)]
    link_rows = sorted(
        links,
        key=lambda row: (
            str(row["origin_post_id"]),
            int(row["position"]),
            str(row["target_post_id"]),
        ),
    )
    snapshot_rows = sorted(snapshots, key=lambda row: str(row["codigo"]))

    _write_jsonl(satellite_jsonl, satellite_rows)
    _write_jsonl(links_jsonl, link_rows)
    _write_jsonl(snapshot_jsonl, snapshot_rows)

    result = ContextBuildResult(
        origin_posts=len(origin),
        origins_with_context=origins_with_context,
        satellite_posts=len(satellite_rows),
        links=len(link_rows),
        unresolved_links=sum(row["status"] != "resolved" for row in link_rows),
        source_sha256=hashlib.sha256(source_raw).hexdigest(),
        satellite_sha256=_sha256(satellite_jsonl),
        links_sha256=_sha256(links_jsonl),
        snapshot_sha256=_sha256(snapshot_jsonl),
    )
    manifest_json.parent.mkdir(parents=True, exist_ok=True)
    manifest_json.write_text(
        json.dumps(
            {
                "schema": 1,
                "purpose": "golden_v2_tuit_annotation_context",
                "platform": "bluesky",
                "scope": {
                    "outgoing_relations": [
                        "reply_parent",
                        "reply_ancestor",
                        "reply_root",
                        "quote",
                        "repost",
                    ],
                    "max_parent_depth": max_parent_depth,
                    "downstream_replies_included": False,
                },
                "counts": {
                    "origin_posts": result.origin_posts,
                    "origins_with_context": result.origins_with_context,
                    "satellite_posts": result.satellite_posts,
                    "links": result.links,
                    "unresolved_links": result.unresolved_links,
                },
                "sha256": {
                    "source": result.source_sha256,
                    "satellite": result.satellite_sha256,
                    "links": result.links_sha256,
                    "snapshot": result.snapshot_sha256,
                },
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return result


def _direct_reference_ids(row: dict[str, Any]) -> set[str]:
    return {
        value
        for value in (
            _clean(row.get("en_respuesta_a")),
            _clean(row.get("conversacion_id")),
            _clean(row.get("cita_a")),
            _clean(row.get("reposteo_a")),
        )
        if value
    }


def _context_item(
    *,
    origin_id: str,
    relation: str,
    depth: int | None,
    target_id: str,
    origin: dict[str, dict[str, Any]],
    satellite: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    target = origin.get(target_id) or satellite.get(target_id)
    source = "origin" if target_id in origin else "satellite"
    status = "resolved" if target is not None else "unavailable"
    return {
        "origin_post_id": origin_id,
        "relation": relation,
        "depth": depth,
        "target_post_id": target_id,
        "status": status,
        "source": source if target is not None else "external",
        "target": _context_target(target) if target is not None else None,
    }


def _context_target(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": str(row["id"]),
        "autor_handle": str(row.get("autor_handle") or ""),
        "autor_display": _clean(row.get("autor_display")),
        "texto": str(row.get("texto") or ""),
        "fecha": _clean(row.get("fecha")),
        "tipo": str(row.get("tipo") or "original"),
        "url": _clean(row.get("url")),
    }


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line_number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not raw.strip():
            continue
        value = json.loads(raw)
        if not isinstance(value, dict) or not _clean(value.get("id")):
            raise ValueError(f"{path}:{line_number}: registro inválido")
        rows.append(value)
    if not rows:
        raise ValueError(f"{path}: corpus vacío")
    return rows


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows),
        encoding="utf-8",
    )


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _clean(value: Any) -> str | None:
    text = str(value).strip() if value is not None else ""
    return text or None
