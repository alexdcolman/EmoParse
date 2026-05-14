"""Cache LLM transparente para EmoParse.

Provee CachedBackend y CacheRepository para uso con LLMBackend.
"""

from emoparse.core.cache.backend import CachedBackend
from emoparse.core.cache.keys import CacheKey, make_cache_key
from emoparse.core.cache.repository import CachedEntry, CacheRepository

__all__ = [
    "CachedBackend",
    "CacheKey",
    "CachedEntry",
    "CacheRepository",
    "make_cache_key",
]
