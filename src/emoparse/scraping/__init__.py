# ══════════════════════════════════════════════════════════════════════════════
#  emoparse.scraping
#
#  Alias de compatibilidad: el paquete fue renombrado a `emoparse.acquisition`.
# ══════════════════════════════════════════════════════════════════════════════

import warnings

from emoparse.acquisition import (
    SOURCES,
    CsvAppender,
    DiscursoRecord,
    SourceAdapter,
    get_source,
)

warnings.warn(
    "emoparse.scraping está deprecado y será removido en una versión futura; "
    "usá emoparse.acquisition.",
    DeprecationWarning,
    stacklevel=2,
)

__all__ = [
    "DiscursoRecord",
    "SourceAdapter",
    "CsvAppender",
    "SOURCES",
    "get_source",
]
