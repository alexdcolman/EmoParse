"""Subcomando `emoparse cite-corpus`: construye un corpus satélite de posts."""

from __future__ import annotations

import argparse
import json
import uuid
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from loguru import logger

from emoparse.acquisition import get_post_source
from emoparse.acquisition.base_posts import PostSourceError
from emoparse.acquisition.post_record import PostRecord
from emoparse.inputs.loader import InputError
from emoparse.inputs.posts_loader import PostsBundle, load_posts, posts_to_discursos
from emoparse.pipeline.thread_builder import build_threads
from emoparse.storage.db import Database
from emoparse.storage.discursos import DiscursosRepository
from emoparse.storage.hilos import HilosRepository
from emoparse.storage.models import RunContext
from emoparse.storage.posts import PostsRepository
from emoparse.storage.runs import RunsRepository
from emoparse.storage.satellites import SatelliteRegistration, SatellitesRepository

COMMAND_NAME = "cite-corpus"

_REL_FIELDS: tuple[tuple[str, str], ...] = (
    ("en_respuesta_a", "reply_parent"),
    ("conversacion_id", "reply_root"),
    ("cita_a", "quote"),
    ("reposteo_a", "repost"),
)


def register(subparsers: argparse._SubParsersAction) -> None:  # type: ignore[type-arg]
    """Registra `cite-corpus` en el CLI."""
    p = subparsers.add_parser(
        COMMAND_NAME,
        help="Construir un corpus satélite desde relaciones entre posts.",
        description=(
            "Parte de una SQLite de posts ya preparada, resuelve padres, raíz, citas y reposts "
            "fuera del corpus y publica una SQLite satélite independiente. No ejecuta LLM."
        ),
    )
    p.add_argument("--db", required=True, type=Path, help="SQLite origen ya preparada.")
    p.add_argument(
        "--source",
        default=None,
        help="Fuente capaz de resolver ids concretos. Default: plataforma única del corpus.",
    )
    p.add_argument(
        "--out",
        type=Path,
        default=None,
        help="SQLite satélite. Default: <db>.satellite.sqlite.",
    )
    p.add_argument(
        "--profundidad",
        type=int,
        default=1,
        metavar="N",
        help="Generaciones de contexto saliente a resolver. Default: 1.",
    )
    p.add_argument(
        "--max",
        dest="max_items",
        type=int,
        default=None,
        metavar="N",
        help="Máximo de posts externos que puede incorporar el satélite.",
    )
    p.add_argument(
        "--timeout",
        type=float,
        default=20.0,
        help="Timeout de la fuente si su adapter lo admite.",
    )
    p.set_defaults(handler=handle)


def handle(args: argparse.Namespace) -> int:
    """Construye y registra un satélite de forma transaccional."""
    origin_path = Path(args.db).expanduser().resolve()
    if not origin_path.is_file():
        logger.error(f"[cite-corpus] DB origen no encontrada: {origin_path}")
        return 1
    if args.profundidad < 1:
        logger.error("[cite-corpus] --profundidad debe ser >= 1.")
        return 2
    if args.max_items is not None and args.max_items < 1:
        logger.error("[cite-corpus] --max debe ser >= 1.")
        return 2

    out_path = (
        Path(args.out).expanduser().resolve()
        if args.out is not None
        else origin_path.with_name(origin_path.stem + ".satellite.sqlite")
    )
    if out_path.exists():
        logger.error(f"[cite-corpus] El destino ya existe: {out_path}")
        return 1

    origin_db = Database(origin_path)
    try:
        if not origin_db.table_exists("runs") or not origin_db.table_exists("posts"):
            logger.error("[cite-corpus] La DB no es un run de posts preparado por EmoParse.")
            return 1
        origin_rows = [
            dict(r)
            for r in origin_db.execute("SELECT * FROM posts ORDER BY post_id").fetchall()
        ]
        if not origin_rows:
            logger.error("[cite-corpus] La DB origen no contiene posts.")
            return 1
        run_row = origin_db.execute("SELECT run_id FROM runs LIMIT 1").fetchone()
        origin_run_id = str(run_row["run_id"])
        source_id = _resolve_source(args.source, origin_rows)
        try:
            adapter = get_post_source(source_id, timeout=args.timeout)
        except PostSourceError as exc:
            logger.error(f"[cite-corpus] {exc}")
            return 1

        try:
            with adapter:
                result = _expand(
                    origin_rows=origin_rows,
                    adapter=adapter,
                    profundidad=args.profundidad,
                    max_items=args.max_items,
                )
        except (PostSourceError, NotImplementedError) as exc:
            logger.error(f"[cite-corpus] La fuente '{source_id}' no puede resolver posts: {exc}")
            return 1

        satellite_id = f"{origin_run_id}__satellite__{uuid.uuid4().hex[:12]}"
        temp_path = out_path.with_name(f".{out_path.name}.{uuid.uuid4().hex}.tmp")
        try:
            _write_satellite(
                temp_path=temp_path,
                satellite_id=satellite_id,
                origin_path=origin_path,
                source_id=source_id,
                profundidad=args.profundidad,
                max_items=args.max_items,
                acquired=result.acquired,
                links=result.links,
            )
            out_path.parent.mkdir(parents=True, exist_ok=True)
            temp_path.replace(out_path)
            try:
                SatellitesRepository(origin_db).register(
                    SatelliteRegistration(
                        satellite_id=satellite_id,
                        satellite_path=out_path,
                        source_id=source_id,
                        marco="bola_de_nieve",
                        profundidad=args.profundidad,
                        max_items=args.max_items,
                    )
                )
            except Exception:
                out_path.unlink(missing_ok=True)
                raise
        finally:
            _remove_sqlite_files(temp_path)

        resolved = sum(1 for row in result.links if row["status"] == "resolved")
        unavailable = sum(1 for row in result.links if row["status"] == "unavailable")
        limited = sum(1 for row in result.links if row["status"] == "limit_reached")
        print()
        print(f"=== Corpus satélite {satellite_id} ===")
        print(f"Origen:      {origin_path}")
        print(f"Satélite:    {out_path}")
        print("Marco:       bola_de_nieve")
        print(f"Profundidad: {args.profundidad}")
        print(f"Posts nuevos: {len(result.acquired)}")
        print(
            f"Vínculos:     {len(result.links)} ({resolved} resueltos, "
            f"{unavailable} no disponibles, {limited} por límite)"
        )
        return 0
    except Exception as exc:  # noqa: BLE001
        logger.error(f"[cite-corpus] Falló la construcción: {exc}")
        return 1
    finally:
        origin_db.close_thread_connection()


class _ExpansionResult:
    def __init__(self, acquired: dict[str, PostRecord], links: list[dict[str, Any]]) -> None:
        self.acquired = acquired
        self.links = links


def _resolve_source(explicit: str | None, rows: list[dict[str, Any]]) -> str:
    if explicit:
        return explicit
    platforms = {str(row.get("plataforma") or "").strip() for row in rows}
    platforms.discard("")
    if len(platforms) != 1:
        raise ValueError("--source es obligatorio cuando el corpus mezcla plataformas.")
    platform = next(iter(platforms))
    return "x_api" if platform == "x" else platform


def _expand(
    *,
    origin_rows: list[dict[str, Any]],
    adapter: Any,
    profundidad: int,
    max_items: int | None,
) -> _ExpansionResult:
    origin = {str(row["post_id"]): row for row in origin_rows}
    acquired: dict[str, PostRecord] = {}
    acquired_rows: dict[str, dict[str, Any]] = {}
    links: list[dict[str, Any]] = []
    seen_link_keys: set[tuple[str, str, str, str, int]] = set()
    visited_by_origin: dict[str, set[str]] = {post_id: {post_id} for post_id in origin}
    frontier: list[tuple[str, str, dict[str, Any]]] = [
        (post_id, post_id, row) for post_id, row in sorted(origin.items())
    ]

    for generation in range(1, profundidad + 1):
        pending: list[tuple[str, str, str, str]] = []
        for origin_id, source_post_id, row in frontier:
            for target_id, relation in _references(
                row,
                generation=generation,
                origin_row=origin[origin_id],
            ):
                key = (origin_id, source_post_id, target_id, relation, generation)
                if key in seen_link_keys:
                    continue
                seen_link_keys.add(key)
                pending.append((origin_id, source_post_id, target_id, relation))

        unresolved_ids = sorted(
            {
                target_id
                for _origin_id, _source_id, target_id, _relation in pending
                if target_id not in origin and target_id not in acquired_rows
            }
        )
        remaining = None if max_items is None else max(max_items - len(acquired), 0)
        if remaining is None:
            to_fetch = unresolved_ids
            limited_ids: set[str] = set()
        else:
            to_fetch = unresolved_ids[:remaining]
            limited_ids = set(unresolved_ids[remaining:])

        received: dict[str, PostRecord] = {}
        if to_fetch:
            received = {record.id: record for record in adapter.fetch_posts(to_fetch)}
            requested = set(to_fetch)
            for post_id in sorted(received):
                if post_id not in requested or post_id in origin:
                    continue
                record = received[post_id]
                acquired[post_id] = record
                acquired_rows[post_id] = record.to_json_dict()
        missing_ids = set(to_fetch) - set(received)

        next_frontier: list[tuple[str, str, dict[str, Any]]] = []
        for origin_id, source_post_id, target_id, relation in pending:
            if target_id in origin:
                status = "resolved"
                target_location = "origin"
                target_row = origin[target_id]
            elif target_id in acquired_rows:
                status = "resolved"
                target_location = "satellite"
                target_row = acquired_rows[target_id]
            elif target_id in limited_ids:
                status = "limit_reached"
                target_location = "external"
                target_row = None
            elif target_id in missing_ids:
                status = "unavailable"
                target_location = "external"
                target_row = None
            else:
                status = "unavailable"
                target_location = "external"
                target_row = None
            links.append(
                {
                    "origin_post_id": origin_id,
                    "source_post_id": source_post_id,
                    "target_post_id": target_id,
                    "relation": relation,
                    "generation": generation,
                    "status": status,
                    "source_location": "origin" if source_post_id in origin else "satellite",
                    "target_location": target_location,
                }
            )
            if status == "resolved" and target_row is not None and generation < profundidad:
                visited = visited_by_origin[origin_id]
                if target_id not in visited:
                    visited.add(target_id)
                    next_frontier.append((origin_id, target_id, target_row))
        frontier = next_frontier
        if not frontier and generation < profundidad:
            break

    links.sort(
        key=lambda row: (
            row["origin_post_id"],
            row["generation"],
            row["source_post_id"],
            row["relation"],
            row["target_post_id"],
        )
    )
    positions: dict[str, int] = {}
    for row in links:
        origin_id = str(row["origin_post_id"])
        positions[origin_id] = positions.get(origin_id, 0) + 1
        row["position"] = positions[origin_id]
    return _ExpansionResult(acquired=acquired, links=links)


def _references(
    row: dict[str, Any],
    *,
    generation: int,
    origin_row: dict[str, Any],
) -> Iterable[tuple[str, str]]:
    source_id = str(row.get("post_id") or row.get("id") or "")
    parent_id = _clean(row.get("en_respuesta_a"))
    root_id = _clean(row.get("conversacion_id"))
    for field, base_relation in _REL_FIELDS:
        target_id = _clean(row.get(field))
        if not target_id or target_id == source_id:
            continue
        if field == "conversacion_id" and target_id == parent_id:
            continue
        relation = base_relation
        if field == "en_respuesta_a" and generation > 1:
            origin_root = _clean(origin_row.get("conversacion_id"))
            relation = "reply_root" if origin_root and target_id == origin_root else "reply_ancestor"
        if field == "conversacion_id" and root_id == source_id:
            continue
        yield target_id, relation


def _write_satellite(
    *,
    temp_path: Path,
    satellite_id: str,
    origin_path: Path,
    source_id: str,
    profundidad: int,
    max_items: int | None,
    acquired: dict[str, PostRecord],
    links: list[dict[str, Any]],
) -> None:
    _remove_sqlite_files(temp_path)
    db = Database(temp_path)
    try:
        ctx = RunContext(
            run_id=satellite_id,
            config={
                "_emoparse": {
                    "satellite": {
                        "origin_db": str(origin_path),
                        "source_id": source_id,
                        "marco": "bola_de_nieve",
                        "profundidad": profundidad,
                        "max_items": max_items,
                    }
                }
            },
            notes="Corpus satélite determinista construido por emoparse cite-corpus.",
        )
        RunsRepository(db).bootstrap(ctx)
        satellites = SatellitesRepository(db)
        satellites.ensure_satellite_tables()
        satellites.set_marco("bola_de_nieve")

        if acquired:
            jsonl_path = temp_path.with_suffix(temp_path.suffix + ".posts.jsonl")
            try:
                jsonl_path.write_text(
                    "".join(
                        json.dumps(
                            acquired[post_id].to_json_dict(),
                            ensure_ascii=False,
                            sort_keys=True,
                        )
                        + "\n"
                        for post_id in sorted(acquired)
                    ),
                    encoding="utf-8",
                )
                bundle = load_posts(jsonl_path)
            finally:
                jsonl_path.unlink(missing_ok=True)
            df_posts, df_hilos = build_threads(bundle.posts)
            bundle = PostsBundle(posts=df_posts, autores=bundle.autores, hilos=df_hilos)
            post_repo = PostsRepository(db)
            posts_rows = bundle.posts.to_dict(orient="records")
            post_repo.upsert_posts(posts_rows)
            post_repo.upsert_autores(
                [
                    {
                        "plataforma": row["plataforma"],
                        "handle": row["handle"],
                        "display_name": row.get("display_name"),
                        "extras": {"n_posts": int(row.get("n_posts", 0))},
                    }
                    for row in bundle.autores.to_dict(orient="records")
                ]
            )
            for row in posts_rows:
                media = row.get("media") or []
                if isinstance(media, list) and media:
                    post_repo.replace_media(str(row["post_id"]), media)
            if bundle.hilos is not None and not bundle.hilos.empty:
                HilosRepository(db).upsert_hilos(bundle.hilos.to_dict(orient="records"))
            try:
                discursos = posts_to_discursos(bundle.posts)
            except InputError:
                discursos = None
            if discursos is not None:
                DiscursosRepository(db).upsert_inputs(
                    [
                        (
                            str(row["codigo"]),
                            {k: value for k, value in row.to_dict().items() if k != "codigo"},
                        )
                        for _, row in discursos.iterrows()
                    ]
                )
        satellites.replace_links(links)
        with db.transaction() as cur:
            cur.execute("UPDATE runs SET status = 'completed', finished_at = CURRENT_TIMESTAMP")
        db.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    finally:
        db.close_thread_connection()


def _remove_sqlite_files(path: Path) -> None:
    for suffix in ("", "-wal", "-shm"):
        Path(str(path) + suffix).unlink(missing_ok=True)


def _clean(value: Any) -> str | None:
    text = str(value).strip() if value is not None else ""
    return text or None
