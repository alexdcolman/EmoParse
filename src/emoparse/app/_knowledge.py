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
