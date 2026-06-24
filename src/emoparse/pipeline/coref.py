# ══════════════════════════════════════════════════════════════════════════════
#  emoparse.pipeline.coref
#
#  Clustering léxico conservador de menciones de actores dentro de un mismo
#  discurso.
# ══════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

import unicodedata
from collections.abc import Iterable

from emoparse.core.text import STOPWORDS

#: Mention key: (unit_idx, mention_idx_within_frase).
MentionKey = tuple[int, int]


#: Mínimo de tokens significativos compartidos para agrupar dos menciones que
#: no son subconjunto una de la otra. Evita unir "víctimas del Holocausto" con
#: "víctimas del atentado a la AMIA" (un solo token en común).
_MIN_SHARED_TOKENS = 3

#: Mínimo de tokens del set contenido para aceptar una fusión por subconjunto.
#: Permite unir "presidente de la nación" con "presidente de la nación
#: argentina" (subconjunto de 2 tokens), pero no fusiona por un único token.
_MIN_SUBSET_TOKENS = 2


def _strip_accents(s: str) -> str:
    """Quita tildes manteniendo el resto del unicode."""
    return "".join(
        c for c in unicodedata.normalize("NFD", s)
        if unicodedata.category(c) != "Mn"
    )


def _normalize(s: str) -> str:
    """Lowercase + strip + sin tildes."""
    return _strip_accents(s.strip().lower())


def _tokenize(s: str) -> list[str]:
    """Tokeniza por whitespace; filtra stopwords y tokens cortísimos."""
    raw = _normalize(s).split()
    return [t for t in raw if len(t) > 1 and t not in STOPWORDS]


def cluster_mentions_within_discurso(
    actors_by_frase: Iterable[tuple[int, list[dict]]],
) -> list[set[MentionKey]]:
    """Agrupa menciones de actores que claramente refieren a la misma entidad.

    Heurística conservadora:
      1. Normalización (lowercase, sin tildes, strip).
      2. Match exacto sobre el string normalizado → mismo cluster.
      3. Subconjunto de tokens significativos: si el set de tokens de una
         mención está contenido en el de la otra Y tiene al menos
         `_MIN_SUBSET_TOKENS` tokens, se agrupan.
      4. Solapamiento sin subconjunto: si comparten al menos
         `_MIN_SHARED_TOKENS` tokens significativos, se agrupan.

    No agrupa (para evitar falsos positivos):
      - Menciones que comparten un único token significativo sin relación de
        subconjunto (p. ej. "víctimas del Holocausto" / "víctimas del atentado").
      - Subconjuntos de un solo token (p. ej. apellido suelto).
      - Menciones cuyos únicos tokens en común sean stopwords.
    """
    mentions: list[tuple[MentionKey, str, frozenset[str]]] = []
    for unit_idx, actors in actors_by_frase:
        if not isinstance(actors, list):
            continue
        for i, actor in enumerate(actors):
            if not isinstance(actor, dict):
                continue
            raw = str(actor.get("actor", "")).strip()
            if not raw:
                continue
            norm = _normalize(raw)
            tokens = frozenset(_tokenize(raw))
            mentions.append(((unit_idx, i), norm, tokens))

    if not mentions:
        return []

    parent: dict[int, int] = {i: i for i in range(len(mentions))}

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: int, b: int) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    for i in range(len(mentions)):
        _, norm_i, toks_i = mentions[i]
        for j in range(i + 1, len(mentions)):
            _, norm_j, toks_j = mentions[j]

            if norm_i == norm_j:
                union(i, j)
                continue

            if not toks_i or not toks_j:
                continue

            is_subset = toks_i <= toks_j or toks_j <= toks_i
            smaller = min(len(toks_i), len(toks_j))
            if is_subset and smaller >= _MIN_SUBSET_TOKENS:
                union(i, j)
                continue

            if len(toks_i & toks_j) >= _MIN_SHARED_TOKENS:
                union(i, j)

    clusters: dict[int, set[MentionKey]] = {}
    for i, (key, _, _) in enumerate(mentions):
        root = find(i)
        clusters.setdefault(root, set()).add(key)

    return list(clusters.values())


def pick_representative(
    cluster: set[MentionKey],
    actors_by_frase_map: dict[int, list[dict]],
) -> str:
    """Elige una mención representativa del cluster."""
    best: tuple[int, MentionKey, str] | None = None
    for key in cluster:
        unit_idx, mention_idx = key
        actors = actors_by_frase_map.get(unit_idx) or []
        if mention_idx >= len(actors):
            continue
        actor = actors[mention_idx]
        if not isinstance(actor, dict):
            continue
        raw = str(actor.get("actor", "")).strip()
        if not raw:
            continue
        score = len(_tokenize(raw))
        if (
            best is None
            or score > best[0]
            or (score == best[0] and key < best[1])
        ):
            best = (score, key, raw)
    return best[2] if best else ""
