# ══════════════════════════════════════════════════════════════════════════════
#  emoparse.scraping.http_client
#
#  Alias de compatibilidad de emoparse.acquisition.http_client.
# ══════════════════════════════════════════════════════════════════════════════

from emoparse.acquisition.http_client import (
    DEFAULT_USER_AGENT,
    HttpClient,
    TransientHttpError,
)

__all__ = ["DEFAULT_USER_AGENT", "TransientHttpError", "HttpClient"]
