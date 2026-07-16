"""Versión canónica de EmoParse.

Política de versionado: Semantic Versioning (https://semver.org/lang/es/).
"""

from __future__ import annotations

__all__ = ["__version__", "VERSION", "VERSION_INFO"]

__version__ = "0.6.1"

VERSION = __version__

#: Tupla parseada para comparaciones programáticas.
#: (major, minor, patch, [pre-release], [build]).
VERSION_INFO = (0, 6, 1)
