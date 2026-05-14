"""Configuración global de pytest para EmoParse."""

from __future__ import annotations

import sys
from pathlib import Path


_SRC = Path(__file__).parent.parent / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))
