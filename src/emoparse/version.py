"""Versión canónica de EmoParse.

Política de versionado: Semantic Versioning (https://semver.org/lang/es/).
"""

from __future__ import annotations

__all__ = ["__version__", "VERSION", "VERSION_INFO"]

__version__: str = "0.3.0"

VERSION: str = __version__

#: Tupla parseada para comparaciones programáticas.
#: (major, minor, patch, [pre-release], [build]).
VERSION_INFO: tuple[int, int, int] = (0, 3, 0)
