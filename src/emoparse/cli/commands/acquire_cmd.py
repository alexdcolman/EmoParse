# ══════════════════════════════════════════════════════════════════════════════
#  emoparse.cli.commands.acquire_cmd
#
#  Subcomando `emoparse acquire`: adquiere posts de una fuente al JSONL.
#
#  Flujo:
#  1) Resuelve el adapter vía `get_post_source(--source)`.
#  2) Inicializa JsonlAppender sobre --out (append idempotente por id).
#  3) Itera posts según el modo (--query | --user | --thread) hasta agotar
#     o --max.
#  4) Filtra por --from / --to (best-effort, post-fetch) y, si se pidió,
#     seudonimiza antes de escribir.
#
#  El comando es interruptible: Ctrl-C deja el JSONL con todo lo extraído
#  hasta ahí. Re-correrlo reanuda donde quedó (dedupe por id del appender).
# ══════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path
from typing import Iterator

from loguru import logger

from emoparse.acquisition import JsonlAppender, get_post_source
from emoparse.acquisition.base_posts import PostSourceError
from emoparse.acquisition.post_record import PostRecord
from emoparse.acquisition.post_sources import POST_SOURCE_IDS
from emoparse.acquisition.pseudonym import Pseudonymizer
from emoparse.cli.commands.scrape_cmd import parse_date


def add_subparser(subparsers: argparse._SubParsersAction) -> argparse.ArgumentParser:
    """Registra `acquire` como subcomando en el CLI principal."""
    p = subparsers.add_parser(
        "acquire",
        help="Adquirir posts de una fuente al JSONL.",
        description=(
            "Adquiere posts (tuits y afines) de una fuente registrada. Modo "
            "append incremental: se puede interrumpir y reanudar (dedupe por "
            "id). El JSONL resultante se analiza con `emoparse run --genre "
            "tuit --input <archivo>.jsonl`."
        ),
    )
    p.add_argument(
        "--source",
        required=True,
        choices=POST_SOURCE_IDS,
        help="Fuente de posts (ej. bluesky, jsonl, csv).",
    )
    p.add_argument(
        "--out",
        required=True,
        type=Path,
        help="JSONL de salida. Se crea si no existe; append si ya existe.",
    )
    modo = p.add_mutually_exclusive_group(required=True)
    modo.add_argument(
        "--query",
        help="Búsqueda (texto libre, hashtag, operadores de la fuente).",
    )
    modo.add_argument(
        "--user",
        help="Handle de una cuenta cuyos posts adquirir.",
    )
    modo.add_argument(
        "--thread",
        help="Id del post raíz de una conversación a adquirir completa.",
    )
    p.add_argument(
        "--max",
        type=int,
        default=None,
        help="Máximo de posts a extraer en esta corrida. None = sin tope.",
    )
    p.add_argument(
        "--min-conv-posts",
        type=int,
        default=None,
        metavar="N",
        help=(
            "Solo con --query: adquiere únicamente conversaciones con al "
            "menos N posts. Por cada resultado de búsqueda se expande su "
            "hilo completo (una llamada por conversación candidata, "
            "deduplicadas); las conversaciones más cortas se descartan. "
            "Agnóstico de la fuente: usa el fetch_thread del adapter."
        ),
    )
    p.add_argument(
        "--max-convs",
        type=int,
        default=None,
        metavar="M",
        help=(
            "Con --min-conv-posts: corta tras adquirir M conversaciones que "
            "pasaron el filtro (economía de adquisición)."
        ),
    )
    p.add_argument(
        "--from",
        dest="from_date",
        type=parse_date,
        default=None,
        metavar="YYYY-MM-DD",
        help="Solo posts con fecha >= esta. Best-effort si la fuente no "
             "filtra por fecha.",
    )
    p.add_argument(
        "--to",
        dest="to_date",
        type=parse_date,
        default=None,
        metavar="YYYY-MM-DD",
        help="Solo posts con fecha <= esta.",
    )
    p.add_argument(
        "--lang",
        default=None,
        help="Filtro de idioma (código ISO, ej. 'es') si la fuente lo soporta.",
    )
    p.add_argument(
        "--input",
        dest="path",
        default=None,
        help="Archivo de entrada para fuentes de importación (jsonl, csv).",
    )
    p.add_argument(
        "--mapping",
        default=None,
        help="JSON {campo_normalizado: columna} para la fuente csv.",
    )
    p.add_argument(
        "--with-media",
        action="store_true",
        help="Descarga las imágenes adjuntas a <out>_media/ y registra "
             "path_local en cada post (solo imágenes, con tope de tamaño).",
    )
    p.add_argument(
        "--with-author-profile",
        action="store_true",
        help="Completa autor_bio/autor_seguidores/autor_siguiendo/autor_verificado "
             "con una llamada extra por autor (cache en memoria). Solo si la "
             "fuente lo soporta; se ignora con un warning si no.",
    )
    p.add_argument(
        "--pseudonymize",
        action="store_true",
        help="Seudonimiza handles al escribir (sal persistida en "
             "<out>.salt). Ver emoparse/acquisition/README.md.",
    )
    p.add_argument(
        "--timeout",
        type=float,
        default=20.0,
        help="Timeout HTTP por request (segundos), si la fuente lo usa.",
    )
    p.set_defaults(handler=run)
    return p


def run(args: argparse.Namespace) -> int:
    """Ejecuta el subcomando. Devuelve exit code (0 = ok)."""
    logger.info(
        f"[acquire] source={args.source} out={args.out} "
        f"query={args.query!r} user={args.user!r} thread={args.thread!r} "
        f"max={args.max} from={args.from_date} to={args.to_date}"
    )

    try:
        adapter = get_post_source(
            args.source,
            path=args.path,
            mapping=args.mapping,
            timeout=args.timeout,
        )
    except PostSourceError as e:
        logger.error(f"[acquire] {e}")
        return 2

    if args.min_conv_posts is not None and args.query is None:
        logger.error(
            "[acquire] --min-conv-posts requiere --query (la búsqueda es la "
            "que descubre conversaciones candidatas)."
        )
        return 2
    if args.max_convs is not None and args.min_conv_posts is None:
        logger.error("[acquire] --max-convs requiere --min-conv-posts.")
        return 2

    pseudonymizer = (
        Pseudonymizer(Path(f"{args.out}.salt")) if args.pseudonymize else None
    )
    downloader = None
    if args.with_media:
        from emoparse.acquisition.media_download import MediaDownloader
        downloader = MediaDownloader(
            Path(args.out).parent / (Path(args.out).stem + "_media")
        )
    enricher = None
    if args.with_author_profile:
        if getattr(adapter, "supports_author_profile", False):
            from emoparse.acquisition.author_enrichment import AuthorEnricher
            enricher = AuthorEnricher(adapter)
        else:
            logger.warning(
                f"[acquire] La fuente '{args.source}' no soporta "
                "--with-author-profile, lo ignoro."
            )
    appender = JsonlAppender(args.out)

    n_written = 0
    n_skipped = 0
    n_filtered = 0

    try:
        with adapter, appender:
            iterador = (
                _iterate_conversaciones(adapter, args)
                if args.min_conv_posts is not None
                else _iterate(adapter, args)
            )
            for record in iterador:
                if appender.has_id(record.id):
                    n_skipped += 1
                    continue
                if not _date_in_range(record, args):
                    n_filtered += 1
                    continue
                if downloader is not None:
                    record = downloader.apply(record)
                if enricher is not None:
                    record = enricher.apply(record)
                if pseudonymizer is not None:
                    record = pseudonymizer.apply(record)
                appender.append(record)
                n_written += 1
                preview = record.texto[:70].replace("\n", " ")
                logger.info(
                    f"[acquire] ✓ {n_written:5d}  {record.fecha or '-':<20s}  "
                    f"@{record.autor_handle}: {preview}"
                )
                if args.max is not None and n_written >= args.max:
                    break
    except KeyboardInterrupt:
        logger.warning("[acquire] Interrumpido por usuario. JSONL preservado.")
    except PostSourceError as e:
        logger.error(f"[acquire] Fuente falló: {e}")
        return 1
    finally:
        if downloader is not None:
            downloader.close()

    logger.info(
        f"[acquire] DONE. escritos={n_written} ya_estaban={n_skipped} "
        f"fuera_de_rango={n_filtered} → {args.out}"
    )
    return 0


def _iterate_conversaciones(
    adapter, args: argparse.Namespace
) -> Iterator[PostRecord]:
    """Búsqueda filtrada por conversaciones de al menos N posts.

    Estrategia económica: itera la búsqueda; por cada post cuya conversación
    no fue vista aún, expande el hilo completo UNA vez (fetch_thread sobre la
    raíz). Si el hilo tiene al menos --min-conv-posts posts, los emite todos
    (el dedupe por id del appender absorbe repetidos); si no, descarta la
    conversación. Corta al llegar a --max-convs conversaciones adquiridas.
    El tope --max sigue aplicando sobre los posts escritos, en el loop.
    """
    minimo = int(args.min_conv_posts)
    max_convs = args.max_convs
    vistas: set[str] = set()
    adquiridas = 0

    for hit in adapter.search(
        args.query,
        max_items=None,
        from_date=args.from_date,
        to_date=args.to_date,
        lang=args.lang,
    ):
        raiz = str(hit.conversacion_id or hit.id)
        if raiz in vistas:
            continue
        vistas.add(raiz)
        try:
            posts = list(adapter.fetch_thread(raiz))
        except Exception as e:
            logger.warning(
                f"[acquire] No pude expandir la conversación {raiz!r}: {e}. "
                "La salteo."
            )
            continue
        if not posts:
            posts = [hit]
        if len(posts) < minimo:
            logger.debug(
                f"[acquire] Conversación {raiz!r} con {len(posts)} post(s) "
                f"< {minimo}: descartada."
            )
            continue
        adquiridas += 1
        logger.info(
            f"[acquire] Conversación {adquiridas}"
            + (f"/{max_convs}" if max_convs else "")
            + f": {len(posts)} post(s) ({raiz})."
        )
        yield from posts
        if max_convs is not None and adquiridas >= max_convs:
            return


def _iterate(adapter, args: argparse.Namespace) -> Iterator[PostRecord]:
    """Elige el modo de iteración según las flags."""
    if args.query is not None:
        return adapter.search(
            args.query,
            max_items=None,  # el tope lo aplica el loop, sobre lo escrito
            from_date=args.from_date,
            to_date=args.to_date,
            lang=args.lang,
        )
    if args.user is not None:
        return adapter.fetch_user(
            args.user,
            max_items=None,
            from_date=args.from_date,
            to_date=args.to_date,
        )
    return adapter.fetch_thread(args.thread)


def _date_in_range(record: PostRecord, args: argparse.Namespace) -> bool:
    """Filtra por --from / --to. Si la fecha no parsea, se incluye igual."""
    if not args.from_date and not args.to_date:
        return True
    if not record.fecha:
        return True
    try:
        d = datetime.strptime(str(record.fecha)[:10], "%Y-%m-%d").date()
    except ValueError:
        logger.debug(f"[acquire] Fecha no parseable: {record.fecha!r}, incluyo igual")
        return True
    if args.from_date and d < args.from_date:
        return False
    if args.to_date and d > args.to_date:
        return False
    return True
