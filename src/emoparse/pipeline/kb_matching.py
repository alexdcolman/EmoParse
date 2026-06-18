# ══════════════════════════════════════════════════════════════════════════════
#  emoparse.pipeline.kb_matching
#
#  Matching determinístico de menciones contra la KB de actores que resuelve
#  el linking con actores canónicos conocidos por coincidencia literal /
#  cuasi-literal.
#
#  Conservador: solo matchea por igualdad normalizada (sin tildes, minúsculas,
#  sin puntuación, con/sin artículos iniciales) contra los aliases / display_name
#  / canonical_id de la KB, o por igualdad de slug. NO hace fuzzy por
#  solapamiento de tokens.
# ══════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

import re
import unicodedata
from typing import Any

_ARTICLES = {"el", "la", "los", "las", "un", "una", "unos", "unas"}


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", str(s or ""))
    s = "".join(c for c in s if not unicodedata.combining(c)).lower()
    s = re.sub(r"[^a-z0-9 ]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def _norm_no_articles(s: str) -> str:
    return " ".join(t for t in _norm(s).split() if t not in _ARTICLES)


def slugify(s: str) -> str:
    base = _norm(s).replace(" ", "_")
    return re.sub(r"_+", "_", base).strip("_")


class KbMatcher:
    """Índice normalizado de la KB para matching literal/cuasi-literal."""

    def __init__(self, kb: dict[str, Any] | None) -> None:
        self._by_norm: dict[str, str] = {}
        actors = (kb or {}).get("actors") or {}
        self._canon_ids = set(actors.keys())
        # Pasada 1: formas EXACTAS normalizadas. Una forma exacta nunca debe ser
        # tapada por una forma sin-artículo de otro canónico.
        for cid, entry in actors.items():
            for f in self._forms(cid, entry):
                k = _norm(f)
                if k:
                    self._by_norm.setdefault(k, cid)
        # Pasada 2: formas sin artículos iniciales (solo si no colisionan con 1).
        for cid, entry in actors.items():
            for f in self._forms(cid, entry):
                k = _norm_no_articles(f)
                if k:
                    self._by_norm.setdefault(k, cid)

    @staticmethod
    def _forms(cid: str, entry: dict[str, Any] | None) -> list[str]:
        entry = entry or {}
        forms = [cid, cid.replace("_", " "), entry.get("display_name") or ""]
        forms += [str(a) for a in (entry.get("aliases") or [])]
        return [f for f in forms if f]

    def match(self, mention: str, *_ignored: Any, **__ignored: Any) -> str | None:
        """Linkea SOLO por el texto de la mención (literal/cuasi-literal).

        Deliberadamente ignora cualquier `canonical_id`/`display` que proponga
        el LLM: esas son conjeturas del modelo (arrastran errores de
        correferencia) y no evidencia determinística. Si la mención no matchea
        por texto, devuelve None y queda como hallazgo para revisión.
        """
        for key in (_norm(mention), _norm_no_articles(mention)):
            cid = self._by_norm.get(key)
            if cid:
                return cid
        if slugify(mention) in self._canon_ids:
            return slugify(mention)
        return None
