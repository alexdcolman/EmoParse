# ══════════════════════════════════════════════════════════════════════════════
#  emoparse.scraping.normalize
#
#  Alias de compatibilidad de emoparse.acquisition.normalize.
# ══════════════════════════════════════════════════════════════════════════════

from emoparse.acquisition.normalize import (
    clean_whitespace,
    normalize_date,
    normalize_url,
    strip_boilerplate,
)

__all__ = [
    "clean_whitespace",
    "strip_boilerplate",
    "normalize_date",
    "normalize_url",
]
