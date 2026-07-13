# ══════════════════════════════════════════════════════════════════════════════
#  emoparse.network.export
#
#  Exportación de grafos y métricas a formatos externos (Gephi, CSV).
# ══════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd

from emoparse.network.metrics import _nx


def export_graph(
    G: Any,
    out_dir: Path | str,
    nombre: str,
    node_attrs: pd.DataFrame | None = None,
    communities: dict[str, int] | None = None,
) -> list[Path]:
    """Exporta un grafo a GEXF + CSVs de nodos y aristas.

    `node_attrs` (con columna `nodo`) y `communities` se anexan como
    atributos de nodo, visibles en Gephi.
    """
    nx = _nx()
    out = Path(out_dir).expanduser().resolve()
    out.mkdir(parents=True, exist_ok=True)

    if node_attrs is not None and not node_attrs.empty:
        indexed = node_attrs.set_index("nodo")
        for nodo in G.nodes():
            if str(nodo) in indexed.index:
                for col, val in indexed.loc[str(nodo)].items():
                    if val is not None and not (
                        isinstance(val, float) and pd.isna(val)
                    ):
                        G.nodes[nodo][str(col)] = _gexf_safe(val)
    if communities:
        for nodo in G.nodes():
            if str(nodo) in communities:
                G.nodes[nodo]["comunidad"] = int(communities[str(nodo)])

    paths: list[Path] = []
    gexf = out / f"{nombre}.gexf"
    nx.write_gexf(G, gexf)
    paths.append(gexf)

    edges_csv = out / f"{nombre}_aristas.csv"
    pd.DataFrame(
        [
            {"origen": u, "destino": v, "peso": d.get("weight", 1.0)}
            for u, v, d in G.edges(data=True)
        ]
    ).to_csv(edges_csv, index=False, encoding="utf-8")
    paths.append(edges_csv)

    if node_attrs is not None and not node_attrs.empty:
        nodes_csv = out / f"{nombre}_nodos.csv"
        df = node_attrs.copy()
        if communities:
            df["comunidad"] = df["nodo"].map(
                lambda n: communities.get(str(n))
            )
        df.to_csv(nodes_csv, index=False, encoding="utf-8")
        paths.append(nodes_csv)
    return paths


def _gexf_safe(val: Any) -> Any:
    """GEXF no admite None ni tipos exóticos: castear a tipos simples."""
    if isinstance(val, (int, float, str, bool)):
        return val
    return str(val)
