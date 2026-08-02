# ══════════════════════════════════════════════════════════════════════════════
#  emoparse.scraping.selenium_client
#
#  Alias de compatibilidad de emoparse.acquisition.selenium_client.
# ══════════════════════════════════════════════════════════════════════════════

from emoparse.acquisition.selenium_client import SeleniumClient, SeleniumNotInstalledError

__all__ = ["SeleniumNotInstalledError", "SeleniumClient"]
