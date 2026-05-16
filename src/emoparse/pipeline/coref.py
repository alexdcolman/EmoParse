# ══════════════════════════════════════════════════════════════════════════════
#  emoparse.pipeline.coref
#
#  Clustering léxico conservador de menciones de actores dentro de un mismo
#  discurso.
# ══════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

import unicodedata
from collections.abc import Iterable

#: Mention key: (unit_idx, mention_idx_within_frase).
MentionKey = tuple[int, int]


#: Stopwords castellanas a descartar para el match por tokens.
_STOPWORDS: frozenset[str] = frozenset({
    "el", "la", "los", "las",
    "un", "una", "unos", "unas",
    "de", "del", "al",
    "y", "o", "u",
    "a", "en", "con", "por", "para", "sobre",
    "que", "se", "su", "sus",
    "mi", "tu",
    "este", "esta", "estos", "estas",
    "ese", "esa", "esos", "esas",
})


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
    return [t for t in raw if len(t) > 1 and t not in _STOPWORDS]


def cluster_mentions_within_discurso(
    actors_by_frase: Iterable[tuple[int, list[dict]]],
) -> list[set[MentionKey]]:
    """Agrupa menciones de actores que claramente refieren a la misma entidad.

    Heurística conservadora:
      1. Normalización (lowercase, sin tildes, strip).
      2. Match exacto sobre el string normalizado → mismo cluster.
      3. Match por subset de tokens significativos: si ambas menciones
         comparten al menos un token no-stopword Y uno está contenido
         en el otro (subset de tokens), se agrupan.

    No agrupa (para evitar falsos positivos):
      - Aposiciones implícitas.
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
            if toks_i <= toks_j or toks_j <= toks_i:
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
