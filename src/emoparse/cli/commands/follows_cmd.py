# ══════════════════════════════════════════════════════════════════════════════
#  emoparse.cli.commands.follows_cmd
#
#  Subcomando `emoparse follows`: adquiere el grafo de seguimiento del corpus.
#
#  Flujo:
#  1) Toma las cuentas del corpus (de la DB del run, o de un archivo).
#  2) Por cada cuenta, pide a la fuente a quién sigue.
#  3) Conserva solo las aristas cuyo destino también está en el corpus.
#  4) Persiste el grafo `follow` en `aristas` (idempotente por grafo).
#
#  Se pide únicamente el lado saliente. La arista A→B se captura desde la
#  lista de A, así que listar seguidores no aportaría ninguna arista nueva y
#  costaría dos órdenes de magnitud más: una cuenta sigue a cientos, pero
#  puede tener cientos de miles de seguidores.
#
#  El seguimiento es una foto del momento de la captura, no del momento en
#  que se escribió cada post: quien lea el grafo tiene que saberlo.
#
#  El comando es interruptible y reanudable: al reanudar, las cuentas ya
#  resueltas se saltean salvo que se pase --rehacer.
# ══════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd
from loguru import logger

from emoparse.acquisition import get_post_source
from emoparse.acquisition.base_posts import PostSourceError
from emoparse.acquisition.post_sources import POST_SOURCE_IDS
from emoparse.acquisition.pseudonym import Pseudonymizer
from emoparse.network import (
    compute_node_metrics,
    detect_communities,
    to_graph,
)
from emoparse.network.builders import EDGE_COLUMNS, GRAFO_FOLLOW
from emoparse.network.metrics import NetworkUnavailableError
from emoparse.storage.db import Database
from emoparse.storage.red import RedRepository
from emoparse.storage.runs import RunsRepository

#: Tope de cuentas seguidas que se piden por cuenta. Acota el costo ante
#: cuentas que siguen a decenas de miles sin aportar señal de comunidad.
MAX_FOLLOWS_DEFAULT = 5000


def register(subparsers: argparse._SubParsersAction) -> None:
    """Registra `follows` como subcomando en el CLI principal."""
    p = subparsers.add_parser(
        "follows",
        help="Adquiere el grafo de seguimiento entre las cuentas del corpus.",
        description=(
            "Pide a la fuente a quién sigue cada cuenta del corpus y persiste "
            "como grafo 'follow' las aristas internas al corpus. Habilita el "
            "análisis de comunidades y cliques por seguimiento en "
            "`emoparse network` y en la tab Red."
        ),
    )
    p.add_argument("--db", required=True, help="Path a la DB SQLite del run.")
    p.add_argument(
        "--source",
        required=True,
        choices=POST_SOURCE_IDS,
        help="Fuente desde la que consultar el seguimiento.",
    )
    p.add_argument(
        "--handles",
        type=Path,
        default=None,
        help="Archivo con un handle por línea. Necesario cuando el corpus "
        "está seudonimizado: la DB guarda alias, que no se pueden "
        "consultar en la plataforma.",
    )
    p.add_argument(
        "--pseudonymize",
        action="store_true",
        help="Escribe las aristas con los alias de --salt, para que el grafo "
        "quede en los mismos términos que un corpus seudonimizado.",
    )
    p.add_argument(
        "--salt",
        type=Path,
        default=None,
        help="Archivo de sal de la seudonimización (el mismo que usó `acquire --pseudonymize`).",
    )
    p.add_argument(
        "--seed",
        type=int,
        default=42,
        help="Seed para la detección de comunidades (reproducibilidad).",
    )
    p.add_argument(
        "--max-follows",
        type=int,
        default=MAX_FOLLOWS_DEFAULT,
        metavar="N",
        help=f"Tope de seguidos consultados por cuenta (default {MAX_FOLLOWS_DEFAULT}).",
    )
    p.add_argument(
        "--rehacer",
        action="store_true",
        help="Descarta el grafo persistido y vuelve a consultar todas las "
        "cuentas. Sin esta flag, se reanuda: solo se consultan las que "
        "todavía no tienen aristas.",
    )
    p.add_argument(
        "--timeout",
        type=float,
        default=20.0,
        help="Timeout HTTP por request (segundos), si la fuente lo usa.",
    )
    p.set_defaults(handler=run)


def run(args: argparse.Namespace) -> int:
    """Ejecuta el subcomando. Devuelve exit code (0 = ok)."""
    db_path = Path(args.db).expanduser().resolve()
    if not db_path.is_file():
        logger.error(f"[follows] DB no encontrada: {db_path}")
        return 1
    if args.pseudonymize and args.salt is None:
        logger.error("[follows] --pseudonymize requiere --salt.")
        return 2

    db = Database(db_path)
    RunsRepository(db).ensure_migrations()
    red_repo = RedRepository(db)

    corpus = _handles_del_corpus(db)
    if not corpus:
        logger.error(
            "[follows] El run no tiene cuentas (tabla `posts` vacía). "
            "El grafo de seguimiento requiere un corpus de género tuit."
        )
        return 1

    consultables = _handles_consultables(args, corpus)
    if consultables is None:
        return 2

    try:
        adapter = get_post_source(args.source, timeout=args.timeout)
    except PostSourceError as e:
        logger.error(f"[follows] {e}")
        return 2
    if not getattr(adapter, "supports_follows", False):
        logger.error(
            f"[follows] La fuente '{args.source}' no expone el seguimiento de las cuentas."
        )
        adapter.close()
        return 2

    alias = Pseudonymizer(args.salt).alias if args.pseudonymize else None
    previas = pd.DataFrame() if args.rehacer else red_repo.load_edges(GRAFO_FOLLOW)
    ya_resueltas = set(previas["origen"].astype(str).str.lower()) if not previas.empty else set()
    if ya_resueltas:
        logger.info(
            f"[follows] Reanudo: {len(ya_resueltas)} cuenta(s) ya tenían "
            "aristas persistidas. Usá --rehacer para consultarlas de nuevo."
        )

    filas = [] if previas.empty else previas.to_dict(orient="records")
    consultadas = 0
    try:
        with adapter:
            for handle, clave in consultables:
                if (alias(handle) if alias else handle).lower() in ya_resueltas:
                    continue
                nuevas = _follows_de(adapter, handle, clave, corpus, alias, args.max_follows)
                filas.extend(nuevas)
                consultadas += 1
                logger.info(
                    f"[follows] {consultadas}/{len(consultables)} "
                    f"@{handle}: {len(nuevas)} arista(s) internas al corpus."
                )
    except KeyboardInterrupt:
        logger.warning(
            "[follows] Interrumpido. Persisto lo adquirido hasta acá; "
            "volvé a correr el comando para continuar."
        )

    df = pd.DataFrame(filas, columns=list(EDGE_COLUMNS))
    n = red_repo.replace_edges(GRAFO_FOLLOW, df)
    n_nodos, n_com = _medir_y_persistir(red_repo, df, args.seed)
    logger.info(
        f"[follows] {n} arista(s) entre {n_nodos} cuenta(s) en el grafo "
        f"'{GRAFO_FOLLOW}', {n_com} comunidad(es). Es una foto del "
        f"seguimiento al momento de esta consulta."
    )
    return 0


# ══════════════════════════════════════════════════════════════════════════════
#  Helpers
# ══════════════════════════════════════════════════════════════════════════════


def _medir_y_persistir(red_repo: RedRepository, df: pd.DataFrame, seed: int) -> tuple[int, int]:
    """Calcula métricas y comunidades del grafo de follows y las persiste.

    El grafo de seguimiento es dirigido (A sigue a B no implica B sigue a A);
    las comunidades se detectan sobre su versión no dirigida, como en el resto
    de los grafos de cuentas. Sin networkx el grafo queda igual persistido,
    solo que sin métricas: se avisa y se sigue.
    """
    if df.empty:
        return 0, 0
    try:
        G = to_graph(df, directed=True)
        metricas = compute_node_metrics(G)
        comunidades = detect_communities(G, seed=seed)
    except NetworkUnavailableError as e:
        logger.warning(
            f"[follows] {e} El grafo queda persistido sin métricas; instalá "
            "el extra [network] y volvé a correr para medirlo."
        )
        return 0, 0
    red_repo.replace_metrics(GRAFO_FOLLOW, metricas, comunidades)
    n_com = len(set(comunidades.values())) if comunidades else 0
    return G.number_of_nodes(), n_com


def _handles_del_corpus(db: Database) -> set[str]:
    """Cuentas autoras del corpus, sin distinguir mayúsculas."""
    rows = db.execute(
        "SELECT DISTINCT autor_handle FROM posts WHERE autor_handle IS NOT NULL"
    ).fetchall()
    return {str(r["autor_handle"]).lstrip("@").lower() for r in rows}


def _handles_consultables(
    args: argparse.Namespace, corpus: set[str]
) -> list[tuple[str, str]] | None:
    """Pares (handle real a consultar, clave con la que figura en el corpus).

    Con corpus en claro ambos coinciden. Con corpus seudonimizado hacen
    falta los handles reales por archivo: el alias es un hash y no se puede
    revertir para preguntarle a la plataforma.
    """
    if args.handles is None:
        if args.pseudonymize:
            logger.error(
                "[follows] Con --pseudonymize hace falta --handles: la DB "
                "guarda alias, que no se pueden consultar en la plataforma."
            )
            return None
        return sorted((h, h) for h in corpus)

    path = Path(args.handles).expanduser().resolve()
    if not path.is_file():
        logger.error(f"[follows] Archivo de handles no encontrado: {path}")
        return None
    reales = [
        linea.strip().lstrip("@").lower()
        for linea in path.read_text(encoding="utf-8").splitlines()
        if linea.strip() and not linea.startswith("#")
    ]
    if args.pseudonymize:
        alias = Pseudonymizer(args.salt).alias
        pares = [(h, alias(h).lower()) for h in reales]
    else:
        pares = [(h, h) for h in reales]
    fuera = [h for h, clave in pares if clave not in corpus]
    if fuera:
        logger.warning(
            f"[follows] {len(fuera)} handle(s) del archivo no figuran como "
            "autores del corpus; los consulto igual, pero sus aristas solo "
            "entran si el destino sí está."
        )
    return sorted(pares)


def _follows_de(
    adapter,
    handle: str,
    clave: str,
    corpus: set[str],
    alias,
    max_follows: int | None,
) -> list[dict[str, object]]:
    """Aristas de seguimiento de una cuenta, filtradas al corpus."""
    try:
        seguidos = list(adapter.fetch_follows(handle, max_items=max_follows))
    except Exception as e:
        logger.warning(f"[follows] No pude leer el seguimiento de @{handle}: {e}")
        return []
    filas = []
    for seguido in seguidos:
        destino = str(seguido).lstrip("@").lower()
        destino_clave = alias(destino).lower() if alias else destino
        if destino_clave not in corpus or destino_clave == clave:
            continue
        filas.append(
            {
                "grafo": GRAFO_FOLLOW,
                "origen": clave,
                "destino": destino_clave,
                # El seguimiento no se materializa en ningún post ni tiene fecha
                # que la plataforma exponga: son aristas de estado, no de acto.
                "post_id": None,
                "peso": 1.0,
                "fecha": None,
            }
        )
    return filas
