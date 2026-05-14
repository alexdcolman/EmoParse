# ══════════════════════════════════════════════════════════════════════════════
#  emoparse.scraping.selenium_client
#
#  Wrapper Selenium opcional.
# ══════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

import time
from typing import Any

from loguru import logger


class SeleniumNotInstalledError(RuntimeError):
    """Error si Selenium no está instalado."""


class SeleniumClient:
    """Wrapper headless de Chrome con fallback."""

    def __init__(
        self,
        *,
        headless: bool = True,
        page_load_wait: float = 1.5,
    ) -> None:
        self._headless = headless
        self._wait = page_load_wait
        self._driver: Any | None = None

    def start(self) -> None:
        """Inicia Chrome. Lanza SeleniumNotInstalledError si falta Selenium."""
        if self._driver is not None:
            return
        try:
            from selenium import webdriver
            from selenium.webdriver.chrome.options import Options
        except ImportError as e:
            raise SeleniumNotInstalledError(
                "Selenium no instalado. Instalá con:\n"
                "  pip install 'emoparse[scraping_selenium]'"
            ) from e

        options = Options()
        options.page_load_strategy = "eager"  # no esperar imágenes/analytics
        if self._headless:
            options.add_argument("--headless=new")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--disable-gpu")
        options.add_argument(
            "user-agent=Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )

        try:
            from selenium.webdriver.chrome.service import Service
            from webdriver_manager.chrome import ChromeDriverManager
            self._driver = webdriver.Chrome(
                service=Service(ChromeDriverManager().install()),
                options=options,
            )
            logger.info("[Selenium] Driver iniciado con webdriver-manager")
        except Exception as e:
            logger.warning(f"[Selenium] webdriver-manager falló: {e}. Probando PATH...")
            try:
                self._driver = webdriver.Chrome(options=options)
                logger.info("[Selenium] Driver iniciado desde PATH")
            except Exception as e2:
                raise RuntimeError(
                    f"No se pudo iniciar ChromeDriver: {e2}\n"
                    "Instalá: pip install 'emoparse[scraping_selenium]'\n"
                    "O descargá chromedriver y agregá al PATH."
                ) from e2

        self._driver.set_page_load_timeout(30)
        self._driver.implicitly_wait(8)

    def get_html(self, url: str) -> str:
        """Navega a URL y devuelve HTML renderizado."""
        if self._driver is None:
            self.start()
        assert self._driver is not None
        self._driver.get(url)
        time.sleep(self._wait)
        return self._driver.page_source

    def click_and_get_html(self, url: str, next_button_xpath: str) -> str:
        """Navega, clickea botón y devuelve HTML nuevo."""
        if self._driver is None:
            self.start()
        assert self._driver is not None
        from selenium.webdriver.common.by import By
        from selenium.common.exceptions import NoSuchElementException

        try:
            boton = self._driver.find_element(By.XPATH, next_button_xpath)
            self._driver.execute_script("arguments[0].scrollIntoView(true);", boton)
            time.sleep(0.5)
            boton.click()
            time.sleep(self._wait)
        except NoSuchElementException:
            return ""
        return self._driver.page_source

    def close(self) -> None:
        if self._driver is not None:
            try:
                self._driver.quit()
            except Exception:
                pass
            self._driver = None

    def __enter__(self) -> SeleniumClient:
        self.start()
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()
