# ══════════════════════════════════════════════════════════════════════════════
#  emoparse.network.embeddings
#
#  Agrupamiento de posts por contenido semántico.
#
#  Complementa los otros dos criterios de agrupamiento del paquete: la
#  estructura de interacción (quién le responde o sigue a quién) y el
#  parecido entre simulacros (qué historia emocional cuenta cada post). Este
#  agrupa por lo que los posts dicen, con independencia de con quién se
#  interactúa y de cómo se caracterizó la emoción.
#
#  Requiere el extra `embeddings` (sentence-transformers). El modelo por
#  defecto es multilingüe y chico: el corpus es de posts, no de documentos
#  largos, y el grafo de vecinos se arma una vez por run.
#
#  El grafo se construye por k vecinos más cercanos y se agrupa con el mismo
#  Louvain que el resto del paquete, de modo que las comunidades semánticas
#  sean comparables con las de interacción.
# ══════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

from typing import Any, Sequence

import pandas as pd

#: Modelo por defecto. Multilingüe, 384 dimensiones: buena relación entre
#: calidad en español y costo. Para más precisión (y ~3x de cómputo),
#: 'sentence-transformers/paraphrase-multilingual-mpnet-base-v2'.
MODELO_DEFAULT = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"

#: Vecinos por nodo en el grafo semántico. Más vecinos, comunidades más
#: grandes y difusas.
K_VECINOS = 10

#: Coseno mínimo para conservar una arista de vecindad.
UMBRAL_DEFAULT = 0.45

#: Mínimo de caracteres para que un post aporte señal semántica.
MIN_CARACTERES = 12


class EmbeddingsUnavailableError(RuntimeError):
    """sentence-transformers no está instalado."""


def _st() -> Any:
    try:
        from sentence_transformers import SentenceTransformer
    except ImportError as e:
        raise EmbeddingsUnavailableError(
            "sentence-transformers no está instalado. Instalá el extra: "
            'pip install -e ".[embeddings]"'
        ) from e
    return SentenceTransformer


def embed(
    textos: Sequence[str],
    modelo: str = MODELO_DEFAULT,
    batch_size: int = 64,
) -> Any:
    """Vectores normalizados de una lista de textos.

    Normalizados a norma 1, de modo que el producto interno sea el coseno.
    """
    SentenceTransformer = _st()
    encoder = SentenceTransformer(modelo)
    return encoder.encode(
        list(textos),
        batch_size=batch_size,
        convert_to_numpy=True,
        normalize_embeddings=True,
        show_progress_bar=False,
    )


def knn_pairs(
    vectores: Any,
    k: int = K_VECINOS,
    umbral: float = UMBRAL_DEFAULT,
) -> pd.DataFrame:
    """Pares (i, j) de los k vecinos más cercanos de cada vector.

    Se calcula por bloques de filas para no materializar la matriz de
    similitud completa, que en decenas de miles de posts no entra en memoria.
    """
    import numpy as np

    n = int(vectores.shape[0])
    if n < 2:
        return pd.DataFrame(columns=["i", "j", "similitud"])
    k = max(1, min(k, n - 1))
    bloque = max(1, min(512, n))
    pares: dict[tuple[int, int], float] = {}
    for inicio in range(0, n, bloque):
        fin = min(inicio + bloque, n)
        cos = vectores[inicio:fin] @ vectores.T
        for fila in range(fin - inicio):
            i = inicio + fila
            cos[fila, i] = -1.0  # nunca vecino de sí mismo
            vecinos = np.argpartition(cos[fila], -k)[-k:]
            for j in vecinos:
                sim = float(cos[fila, j])
                if sim < umbral:
                    continue
                clave = (i, int(j)) if i < int(j) else (int(j), i)
                if sim > pares.get(clave, -1.0):
                    pares[clave] = sim
    if not pares:
        return pd.DataFrame(columns=["i", "j", "similitud"])
    return pd.DataFrame(
        [{"i": i, "j": j, "similitud": round(s, 4)}
         for (i, j), s in pares.items()]
    ).sort_values("similitud", ascending=False).reset_index(drop=True)


def agrupar_por_contenido(
    df_posts: pd.DataFrame,
    modelo: str = MODELO_DEFAULT,
    k: int = K_VECINOS,
    umbral: float = UMBRAL_DEFAULT,
    seed: int = 42,
) -> tuple[pd.DataFrame, dict[str, int]]:
    """Comunidades semánticas del corpus de posts.

    Devuelve las aristas de vecindad (con `origen`/`destino` como post_id,
    listas para persistir junto al resto de los grafos) y el mapa post_id →
    comunidad. Los posts sin texto suficiente quedan fuera: un repost puro no
    tiene contenido propio que agrupar.
    """
    from emoparse.network.metrics import _nx

    registros = [
        r for r in df_posts.to_dict(orient="records")
        if len(str(r.get("texto") or "").strip()) >= MIN_CARACTERES
    ]
    if len(registros) < 2:
        return pd.DataFrame(columns=["origen", "destino", "peso"]), {}

    ids = [str(r["post_id"]) for r in registros]
    vectores = embed([str(r["texto"]) for r in registros], modelo=modelo)
    pares = knn_pairs(vectores, k=k, umbral=umbral)
    if pares.empty:
        return pd.DataFrame(columns=["origen", "destino", "peso"]), {}

    aristas = pd.DataFrame({
        "origen": [ids[int(i)] for i in pares["i"]],
        "destino": [ids[int(j)] for j in pares["j"]],
        "peso": pares["similitud"].astype(float),
    })

    nx = _nx()
    G = nx.Graph()
    for r in aristas.to_dict(orient="records"):
        G.add_edge(r["origen"], r["destino"], weight=float(r["peso"]))
    comunidades = nx.community.louvain_communities(G, weight="weight", seed=seed)
    ordenadas = sorted(
        (sorted(str(n) for n in c) for c in comunidades),
        key=lambda c: (-len(c), c[0]),
    )
    return aristas, {nodo: i for i, c in enumerate(ordenadas) for nodo in c}


def terminos_por_comunidad(
    df_posts: pd.DataFrame,
    comunidades: dict[str, int],
    top: int = 8,
    min_longitud: int = 4,
) -> pd.DataFrame:
    """Términos que distinguen a cada comunidad semántica.

    Los vectores agrupan, pero no explican: esta tabla da la lectura. Puntúa
    cada término por su frecuencia en la comunidad contra su frecuencia en el
    resto del corpus, de modo que lo que aparece en todas las comunidades no
    describa a ninguna.
    """
    import re
    from collections import Counter

    texto_por_post = {
        str(r["post_id"]): str(r.get("texto") or "")
        for r in df_posts.to_dict(orient="records")
    }
    por_comunidad: dict[int, Counter] = {}
    global_counts: Counter = Counter()
    for post_id, comunidad in comunidades.items():
        tokens = [
            t for t in re.findall(r"\w+", texto_por_post.get(post_id, "").lower())
            if len(t) >= min_longitud and not t.isdigit()
        ]
        por_comunidad.setdefault(int(comunidad), Counter()).update(set(tokens))
        global_counts.update(set(tokens))

    filas: list[dict[str, Any]] = []
    for comunidad, counts in sorted(por_comunidad.items()):
        n = sum(counts.values()) or 1
        total = sum(global_counts.values()) or 1
        puntuados = sorted(
            (
                (t, c, (c / n) / (global_counts[t] / total))
                for t, c in counts.items() if c >= 2
            ),
            key=lambda x: (-x[2], -x[1]),
        )
        filas.append({
            "comunidad": comunidad,
            "posts": len([1 for v in comunidades.values() if v == comunidad]),
            "terminos": ", ".join(t for t, _c, _s in puntuados[:top]),
        })
    return pd.DataFrame(filas)
