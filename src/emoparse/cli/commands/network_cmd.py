# ══════════════════════════════════════════════════════════════════════════════
#  emoparse.cli.commands.network_cmd
#
#  Subcomando `emoparse network`: análisis de redes sobre un run de posts.
#
#  Flujo:
#  1) Lee posts, tecno_entidades y emociones de la DB del run.
#  2) Construye las aristas de los grafos pedidos (--graphs).
#  3) Calcula métricas por nodo y comunidades (Louvain, seed fija).
#  4) Persiste aristas y métricas en la DB (idempotente por grafo).
#  5) Acoplamiento emocional: matriz de transición fórica en hilos y perfil
#     por comunidad (si el run tiene emociones caracterizadas).
#  6) Con --export-dir, exporta GEXF + CSVs por grafo (abren en Gephi).
#
#  Sin LLM. Requiere el extra `network` (networkx).
# ══════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd
from loguru import logger

from emoparse.network import (
    GRAFOS,
    build_edges,
    community_emotion_profile,
    compute_node_metrics,
    detect_communities,
    foria_by_post,
    foria_transition_matrix,
    to_graph,
)
from emoparse.network.export import export_graph
from emoparse.network.metrics import NetworkUnavailableError
from emoparse.storage.db import Database
from emoparse.storage.red import RedRepository
from emoparse.storage.runs import RunsRepository


def add_subparser(subparsers: argparse._SubParsersAction) -> argparse.ArgumentParser:
    """Registra `network` como subcomando en el CLI principal."""
    p = subparsers.add_parser(
        "network",
        help="Construye y analiza las redes de interacción de un run de posts.",
        description=(
            "Construye grafos de interacción (reply, mention, rt, qt, "
            "hashtag_co) desde los posts del run, calcula métricas y "
            "comunidades, las persiste en la DB y reporta el acoplamiento "
            "con el análisis emocional. Requiere el extra [network]."
        ),
    )
    p.add_argument(
        "--db",
        required=True,
        help="Path a la DB SQLite del run.",
    )
    p.add_argument(
        "--graphs",
        default="reply,mention,rt,qt,hashtag_co",
        help="Grafos a construir, separados por coma. "
             f"Válidos: {', '.join(GRAFOS)}.",
    )
    p.add_argument(
        "--seed",
        type=int,
        default=42,
        help="Seed para la detección de comunidades (reproducibilidad).",
    )
    p.add_argument(
        "--export-dir",
        type=Path,
        default=None,
        help="Directorio para exportar GEXF + CSVs por grafo (Gephi).",
    )
    p.add_argument(
        "--top",
        type=int,
        default=10,
        help="Cantidad de nodos a mostrar en el resumen por grafo.",
    )
    p.set_defaults(handler=run)
    return p


def run(args: argparse.Namespace) -> int:
    """Ejecuta el subcomando. Devuelve exit code (0 = ok)."""
    db_path = Path(args.db).expanduser().resolve()
    if not db_path.is_file():
        logger.error(f"[network] DB no encontrada: {db_path}")
        return 1

    graphs = tuple(s.strip() for s in args.graphs.split(",") if s.strip())
    unknown = set(graphs) - set(GRAFOS)
    if unknown:
        logger.error(
            f"[network] Grafos desconocidos: {sorted(unknown)}. "
            f"Válidos: {', '.join(GRAFOS)}"
        )
        return 1

    db = Database(db_path)
    RunsRepository(db).ensure_migrations()
    df_posts = _read_df(db, "SELECT * FROM posts")
    if df_posts.empty:
        logger.error(
            "[network] El run no contiene posts (tabla `posts` vacía). "
            "El análisis de redes requiere un corpus de género tuit."
        )
        return 1
    df_tecno = _read_df(db, "SELECT * FROM tecno_entidades")
    df_emociones = _read_df(db, "SELECT * FROM emociones")

    logger.info(
        f"[network] Corpus: {len(df_posts)} posts, {len(df_tecno)} "
        f"tecno-entidades, {len(df_emociones)} emociones."
    )

    red_repo = RedRepository(db)
    try:
        _procesar_grafos(red_repo, df_posts, df_tecno, graphs, args)
    except NetworkUnavailableError as e:
        logger.error(f"[network] {e}")
        return 2

    _reporte_emocional(df_posts, df_emociones)
    return 0


# ══════════════════════════════════════════════════════════════════════════════
#  Procesamiento
# ══════════════════════════════════════════════════════════════════════════════

def _procesar_grafos(
    red_repo: RedRepository,
    df_posts: pd.DataFrame,
    df_tecno: pd.DataFrame,
    graphs: tuple[str, ...],
    args: argparse.Namespace,
) -> None:
    """Construye, mide, persiste y (opcionalmente) exporta cada grafo."""
    df_all = build_edges(df_posts, df_tecno, graphs=graphs)

    print()
    for grafo in graphs:
        df_edges = (
            df_all[df_all["grafo"] == grafo]
            if not df_all.empty
            else df_all
        )
        if df_edges.empty:
            print(f"── {grafo}: sin aristas (referencias no capturadas o corpus sin ese tipo de interacción)")
            continue

        directed = grafo != "hashtag_co"
        G = to_graph(df_edges, directed=directed)
        df_metrics = compute_node_metrics(G)
        communities = detect_communities(G, seed=args.seed)

        red_repo.replace_edges(grafo, df_edges)
        red_repo.replace_metrics(grafo, df_metrics, communities)

        n_com = len(set(communities.values())) if communities else 0
        print(
            f"── {grafo}: {G.number_of_nodes()} nodos, "
            f"{G.number_of_edges()} aristas, {n_com} comunidades"
        )
        top = df_metrics.head(args.top)
        for _, r in top.iterrows():
            com = communities.get(str(r["nodo"]))
            print(
                f"     {r['nodo'][:40]:<42s} pagerank={r['pagerank']:.4f} "
                f"grado={int(r['grado_total'])}"
                + (f" comunidad={com}" if com is not None else "")
            )

        if args.export_dir is not None:
            paths = export_graph(
                G, args.export_dir, grafo,
                node_attrs=df_metrics, communities=communities,
            )
            logger.info(
                f"[network] {grafo}: exportado → "
                + ", ".join(p.name for p in paths)
            )
    print()


def _reporte_emocional(
    df_posts: pd.DataFrame,
    df_emociones: pd.DataFrame,
) -> None:
    """Reporta la matriz de transición fórica en hilos, si hay insumos."""
    if df_emociones.empty:
        logger.info(
            "[network] Sin emociones en el run: se omite el acoplamiento "
            "emocional (corré las stages de emociones y characterizer)."
        )
        return
    foria_map = foria_by_post(df_emociones)
    matrix = foria_transition_matrix(df_posts, foria_map)
    if int(matrix.values.sum()) == 0:
        logger.info(
            "[network] Sin pares padre-hijo con foria caracterizada: se "
            "omite la matriz de transición."
        )
        return
    print("── Transiciones fóricas en hilos (padre → respuesta):")
    print(matrix.to_string())
    print()


def _read_df(db: Database, sql: str) -> pd.DataFrame:
    """Lee una consulta completa a DataFrame (tabla ausente → DF vacío)."""
    try:
        rows = db.execute(sql).fetchall()
    except Exception:
        return pd.DataFrame()
    return pd.DataFrame([dict(r) for r in rows])
