# ══════════════════════════════════════════════════════════════════════════════
#  emoparse.network.metrics
#
#  Grafos networkx, métricas por nodo y detección de comunidades.
#
#  Requiere el extra `network` (networkx). La intermediación se omite en
#  grafos grandes (costo O(n·m)); las comunidades usan Louvain (built-in de
#  networkx ≥3) sobre la versión no dirigida, con seed fija para
#  reproducibilidad.
#
#  Comunidad y clique responden preguntas distintas: la comunidad es una zona
#  densa que particiona el grafo, la clique es un conjunto donde todos se
#  vinculan con todos y puede solaparse con otras. En un grafo de follows la
#  clique se busca sobre los vínculos recíprocos: seguir a alguien que no te
#  sigue no constituye un grupo.
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
            'networkx no está instalado. Instalá el extra: pip install -e ".[network]"'
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
            columns=["nodo", "grado_in", "grado_out", "grado_total", "pagerank", "intermediacion"]
        )
    dirigido = G.is_directed()
    pagerank = nx.pagerank(G, weight="weight")
    if G.number_of_nodes() <= betweenness_max_nodes:
        intermediacion = nx.betweenness_centrality(G, weight=None)
    else:
        intermediacion = {}

    rows = []
    for nodo in G.nodes():
        rows.append(
            {
                "nodo": str(nodo),
                "grado_in": int(G.in_degree(nodo)) if dirigido else None,
                "grado_out": int(G.out_degree(nodo)) if dirigido else None,
                "grado_total": int(G.degree(nodo)),
                "pagerank": float(pagerank.get(nodo, 0.0)),
                "intermediacion": (float(intermediacion[nodo]) if nodo in intermediacion else None),
            }
        )
    return pd.DataFrame(rows).sort_values("pagerank", ascending=False).reset_index(drop=True)


def mutual_subgraph(G: Any) -> Any:
    """Grafo no dirigido de los vínculos recíprocos de un grafo dirigido.

    En un grafo no dirigido devuelve el mismo grafo: ya no hay reciprocidad
    que exigir.
    """
    nx = _nx()
    if not G.is_directed():
        return G
    M = nx.Graph()
    M.add_nodes_from(G.nodes())
    for u, v, d in G.edges(data=True):
        if G.has_edge(v, u):
            M.add_edge(u, v, weight=float(d.get("weight", 1.0)))
    return M


def detect_cliques(
    G: Any,
    min_size: int = 3,
    mutual_only: bool = True,
    limit: int | None = None,
) -> list[list[str]]:
    """Cliques maximales de al menos `min_size` nodos, de mayor a menor.

    Con `mutual_only` la búsqueda corre sobre los vínculos recíprocos, que es
    lo que da sentido a la clique en grafos de seguimiento o de respuesta.
    Enumerar cliques es exponencial en el peor caso: `limit` corta la
    enumeración en grafos densos, devolviendo lo hallado hasta ahí.
    """
    nx = _nx()
    base = mutual_subgraph(G) if mutual_only else (G.to_undirected() if G.is_directed() else G)
    if base.number_of_nodes() == 0:
        return []
    encontradas: list[list[str]] = []
    for clique in nx.find_cliques(base):
        if len(clique) >= min_size:
            encontradas.append(sorted(str(n) for n in clique))
            if limit is not None and len(encontradas) >= limit:
                break
    return sorted(encontradas, key=lambda c: (-len(c), c[0]))


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
