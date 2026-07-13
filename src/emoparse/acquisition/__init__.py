# ══════════════════════════════════════════════════════════════════════════════
#  emoparse.acquisition
#
#  Adquisición de corpus con arquitectura source-adapter.
#
#  Dos familias de fuentes:
#  - Discursos (texto largo, un documento por URL): `SourceAdapter` +
#    `DiscursoRecord`, persistidos a CSV vía `CsvAppender`.
#  - Posts de redes sociales (documentos cortos con estructura conversacional
#    y metadatos de circulación): `PostSourceAdapter` + `PostRecord`,
#    persistidos a JSONL vía `JsonlAppender`.
# ══════════════════════════════════════════════════════════════════════════════

from emoparse.acquisition.base import DiscursoRecord, SourceAdapter
from emoparse.acquisition.base_posts import PostSourceAdapter
from emoparse.acquisition.jsonl_appender import JsonlAppender
from emoparse.acquisition.persist import CsvAppender
from emoparse.acquisition.post_record import PostRecord
from emoparse.acquisition.post_sources import POST_SOURCE_IDS, get_post_source
from emoparse.acquisition.sources import SOURCES, get_source

__all__ = [
    "DiscursoRecord",
    "SourceAdapter",
    "CsvAppender",
    "SOURCES",
    "get_source",
    "PostRecord",
    "PostSourceAdapter",
    "JsonlAppender",
    "POST_SOURCE_IDS",
    "get_post_source",
]
