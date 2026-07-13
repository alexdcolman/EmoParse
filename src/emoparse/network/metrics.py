# ══════════════════════════════════════════════════════════════════════════════
#  emoparse.network.metrics
#
#  Grafos networkx, métricas por nodo y detección de comunidades.
#
#  Requiere el extra `network` (networkx). La intermediación se omite en
#  grafos grandes (costo O(n·m)); las comunidades usan Louvain (built-in de
#  networkx ≥3) sobre la versión no dirigida, con seed fija para
#  reproducibilidad.
# ══════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

from typing import Any

import pandas as pd


class NetworkUnavailableError(RuntimeError):
    """networkx no está instalado."""


def _nx() -> Any:
    try:
        import networkx
    except ImportError as e:
        raise NetworkUnavailableError(
            "networkx no está instalado. Instalá el extra: "
            'pip install -e ".[network]"'
        ) from e
    return networkx


#: Umbral de nodos por encima del cual se omite la intermediación.
BETWEENNESS_MAX_NODES = 2000


def to_graph(df_edges: pd.DataFrame, directed: bool = True) -> Any:
    """Construye un grafo networkx agregando pesos de aristas repetidas."""
    nx = _nx()
    G = nx.DiGraph() if directed else nx.Graph()
    for r in df_edges.to_dict(orient="records"):
        u, v = str(r["origen"]), str(r["destino"])
        w = float(r.get("peso", 1.0))
        if G.has_edge(u, v):
            G[u][v]["weight"] += w
        else:
            G.add_edge(u, v, weight=w)
    return G


def compute_node_metrics(
    G: Any,
    betweenness_max_nodes: int = BETWEENNESS_MAX_NODES,
) -> pd.DataFrame:
    """Métricas por nodo: grados, PageRank e intermediación (si es viable)."""
    nx = _nx()
    if G.number_of_nodes() == 0:
        return pd.DataFrame(
            columns=["nodo", "grado_in", "grado_out", "grado_total",
                     "pagerank", "intermediacion"]
        )
    dirigido = G.is_directed()
    pagerank = nx.pagerank(G, weight="weight")
    if G.number_of_nodes() <= betweenness_max_nodes:
        intermediacion = nx.betweenness_centrality(G, weight=None)
    else:
        intermediacion = {}

    rows = []
    for nodo in G.nodes():
        rows.append({
            "nodo": str(nodo),
            "grado_in": int(G.in_degree(nodo)) if dirigido else None,
            "grado_out": int(G.out_degree(nodo)) if dirigido else None,
            "grado_total": int(G.degree(nodo)),
            "pagerank": float(pagerank.get(nodo, 0.0)),
            "intermediacion": (
                float(intermediacion[nodo]) if nodo in intermediacion else None
            ),
        })
    return pd.DataFrame(rows).sort_values(
        "pagerank", ascending=False
    ).reset_index(drop=True)


def detect_communities(G: Any, seed: int = 42) -> dict[str, int]:
    """Comunidades Louvain (sobre el grafo no dirigido), nodo → id.

    Con seed fija el resultado es reproducible para el mismo grafo.
    """
    nx = _nx()
    if G.number_of_nodes() == 0:
        return {}
    U = G.to_undirected() if G.is_directed() else G
    comunidades = nx.community.louvain_communities(U, weight="weight", seed=seed)
    # Ids estables: comunidades ordenadas por tamaño desc y primer nodo.
    ordenadas = sorted(
        (sorted(str(n) for n in c) for c in comunidades),
        key=lambda c: (-len(c), c[0]),
    )
    return {nodo: i for i, c in enumerate(ordenadas) for nodo in c}
