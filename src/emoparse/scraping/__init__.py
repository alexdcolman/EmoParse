# ══════════════════════════════════════════════════════════════════════════════
#  emoparse.scraping
#
#  Scraping con arquitectura source-adapter.
# ══════════════════════════════════════════════════════════════════════════════

from emoparse.scraping.base import DiscursoRecord, SourceAdapter
from emoparse.scraping.persist import CsvAppender
from emoparse.scraping.sources import SOURCES, get_source

__all__ = [
    "DiscursoRecord",
    "SourceAdapter",
    "CsvAppender",
    "SOURCES",
    "get_source",
]
