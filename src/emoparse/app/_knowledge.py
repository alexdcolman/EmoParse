# ══════════════════════════════════════════════════════════════════════════════
#  emoparse.app._knowledge
#
#  Lectura liviana de knowledge/ para las tabs (vocabulario de semas).
# ══════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


def _knowledge_dir() -> Path:
    return Path(os.environ.get("EMOPARSE_KNOWLEDGE_DIR", "knowledge"))


def load_semas_vocab() -> dict[str, Any]:
    """Devuelve el vocabulario de semas (dimensiones + lista plana), o {}."""
    path = _knowledge_dir() / "semas.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def semas_list() -> list[str]:
    """Lista plana de semas del vocabulario curado."""
    vocab = load_semas_vocab()
    semas = vocab.get("semas") or []
    return [str(s) for s in semas if str(s).strip()]


def semas_by_dimension() -> dict[str, list[str]]:
    """Mapa dimensión → valores, para agrupar la selección de semas."""
    vocab = load_semas_vocab()
    dims = vocab.get("dimensiones") or {}
    out: dict[str, list[str]] = {}
    for dim, info in dims.items():
        if isinstance(info, dict):
            out[dim] = [str(v) for v in (info.get("valores") or [])]
    return out


def semas_jerarquia() -> dict[str, Any]:
    """Estructura declarada de las dimensiones (base / por_clase / opcionales)."""
    jer = load_semas_vocab().get("jerarquia")
    return jer if isinstance(jer, dict) else {}


def semas_estructura(clase: str | None = None) -> list[tuple[str, list[str]]]:
    """Dimensiones aplicables a `clase`, en orden jerárquico, con sus valores.

    Combina las dimensiones base, las específicas de la clase actancial y las
    generales. Excluye el valor `no_aplica` (marca de dimensión inaplicable).
    Sin jerarquía declarada, devuelve todas las dimensiones en orden de
    declaración.
    """
    by_dim = semas_by_dimension()

    def _vals(dim: str) -> list[str]:
        return [v for v in by_dim.get(dim, []) if v != "no_aplica"]

    jer = semas_jerarquia()
    if not jer:
        return [(d, _vals(d)) for d in by_dim]

    orden = list(jer.get("base") or [])
    if clase:
        orden += list((jer.get("por_clase") or {}).get(clase) or [])
    orden += list(jer.get("opcionales") or [])

    out: list[tuple[str, list[str]]] = []
    seen: set[str] = set()
    for dim in orden:
        if dim in by_dim and dim not in seen:
            seen.add(dim)
            out.append((dim, _vals(dim)))
    return out


def colectivo_clases() -> list[str]:
    """Clases de colectivo de identificación (unión sobre tipos de discurso)."""
    path = _knowledge_dir() / "colectivos.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    out: set[str] = set()
    if isinstance(data, dict):
        for tipo, clases in data.items():
            if tipo == "version" or not isinstance(clases, dict):
                continue
            out.update(str(c) for c in clases)
    return sorted(out)
