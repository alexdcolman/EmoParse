# ══════════════════════════════════════════════════════════════════════════════
#  emoparse.network.builders
#
#  Construcción de aristas de interacción desde DataFrames de posts y
#  tecno-entidades. Funciones puras, sin DB ni networkx.
#
#  Grafos:
#  - reply:      autor → autor del post al que responde (interacción directa).
#  - mention:    autor → handle mencionado en el texto (interpelación).
#  - rt:         autor → autor del post reposteado (difusión).
#  - qt:         autor → autor del post citado (retome).
#  - hashtag_co: hashtag ↔ hashtag co-ocurrentes en un mismo post (no
#                dirigido; se emite con origen < destino).
#
#  En reply/rt/qt el destino requiere que el post referido esté capturado
#  (para conocer a su autor); las referencias a posts ausentes se omiten.
# ══════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

from itertools import combinations

import pandas as pd

#: Grafos disponibles.
GRAFOS: tuple[str, ...] = ("reply", "mention", "rt", "qt", "hashtag_co")

#: Columnas del DataFrame de aristas.
EDGE_COLUMNS: tuple[str, ...] = ("grafo", "origen", "destino", "post_id", "peso", "fecha")


def build_edges(
    df_posts: pd.DataFrame,
    df_tecno: pd.DataFrame | None = None,
    graphs: tuple[str, ...] = GRAFOS,
) -> pd.DataFrame:
    """Construye las aristas de los grafos pedidos.

    `df_posts` requiere columnas: post_id, autor_handle, en_respuesta_a,
    reposteo_a, cita_a, fecha. `df_tecno` (para mention y hashtag_co)
    requiere: codigo, unit_idx, tipo, valor_norm.
    """
    frames: list[pd.DataFrame] = []
    autor_por_post = {
        str(r["post_id"]): str(r["autor_handle"])
        for r in df_posts.to_dict(orient="records")
    }
    fecha_por_post = {
        str(r["post_id"]): r.get("fecha")
        for r in df_posts.to_dict(orient="records")
    }

    for ref_col, grafo in (("en_respuesta_a", "reply"),
                           ("reposteo_a", "rt"),
                           ("cita_a", "qt")):
        if grafo not in graphs:
            continue
        frames.append(_ref_edges(df_posts, autor_por_post, ref_col, grafo))

    if df_tecno is not None and not df_tecno.empty:
        if "mention" in graphs:
            frames.append(
                _mention_edges(df_tecno, autor_por_post, fecha_por_post)
            )
        if "hashtag_co" in graphs:
            frames.append(_hashtag_co_edges(df_tecno, fecha_por_post))

    if not frames:
        return pd.DataFrame(columns=list(EDGE_COLUMNS))
    out = pd.concat(frames, ignore_index=True)
    return out[list(EDGE_COLUMNS)] if not out.empty else out


# ══════════════════════════════════════════════════════════════════════════════
#  Constructores por grafo
# ══════════════════════════════════════════════════════════════════════════════

def _ref_edges(
    df_posts: pd.DataFrame,
    autor_por_post: dict[str, str],
    ref_col: str,
    grafo: str,
) -> pd.DataFrame:
    """Aristas autor→autor por referencia a otro post (reply/rt/qt)."""
    rows = []
    for r in df_posts.to_dict(orient="records"):
        ref = r.get(ref_col)
        if ref is None or (isinstance(ref, float) and pd.isna(ref)) or not str(ref).strip():
            continue
        destino = autor_por_post.get(str(ref))
        if destino is None:
            continue  # post referido no capturado: autor desconocido
        rows.append({
            "grafo": grafo,
            "origen": str(r["autor_handle"]),
            "destino": destino,
            "post_id": str(r["post_id"]),
            "peso": 1.0,
            "fecha": r.get("fecha"),
        })
    return pd.DataFrame(rows, columns=list(EDGE_COLUMNS))


def _mention_edges(
    df_tecno: pd.DataFrame,
    autor_por_post: dict[str, str],
    fecha_por_post: dict[str, object],
) -> pd.DataFrame:
    """Aristas autor→handle mencionado (desde tecno_entidades)."""
    menciones = df_tecno[df_tecno["tipo"] == "mencion"]
    rows = []
    for r in menciones.to_dict(orient="records"):
        post_id = str(r["codigo"])
        origen = autor_por_post.get(post_id)
        if origen is None:
            continue
        destino = str(r["valor_norm"]).lower()
        if destino == origen.lower():
            continue  # automención
        rows.append({
            "grafo": "mention",
            "origen": origen,
            "destino": destino,
            "post_id": post_id,
            "peso": 1.0,
            "fecha": fecha_por_post.get(post_id),
        })
    return pd.DataFrame(rows, columns=list(EDGE_COLUMNS))


def _hashtag_co_edges(
    df_tecno: pd.DataFrame,
    fecha_por_post: dict[str, object],
) -> pd.DataFrame:
    """Aristas hashtag↔hashtag co-ocurrentes en un mismo post."""
    tags = df_tecno[df_tecno["tipo"] == "hashtag"]
    rows = []
    for (codigo, _unit), grp in tags.groupby(["codigo", "unit_idx"], sort=True):
        valores = sorted({str(v).lower() for v in grp["valor_norm"]})
        for a, b in combinations(valores, 2):
            rows.append({
                "grafo": "hashtag_co",
                "origen": a,
                "destino": b,
                "post_id": str(codigo),
                "peso": 1.0,
                "fecha": fecha_por_post.get(str(codigo)),
            })
    return pd.DataFrame(rows, columns=list(EDGE_COLUMNS))
