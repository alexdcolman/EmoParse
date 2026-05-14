# ══════════════════════════════════════════════════════════════════════════════
#  emoparse.scraping.http_client
#
#  Cliente HTTP con retries y backoff.
# ══════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

from typing import Any

import requests
from loguru import logger
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
    before_sleep_log,
)

import logging


#: UA de un Chrome reciente.
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)


#: Errores reintentables: red caída, server lento, rate-limit.
_RETRYABLE_HTTP = (500, 502, 503, 504, 408, 429)


class TransientHttpError(Exception):
    """Error HTTP transitorio para retry."""


class _LoguruAdapter(logging.Logger):
    """Adaptador para usar loguru con tenacity."""
    def __init__(self) -> None:
        super().__init__("scraping.http_client")

    def log(self, level: int, msg: str, *args: Any, **kwargs: Any) -> None:
        logger.opt(depth=1).log(_level_to_loguru(level), msg % args if args else msg)


def _level_to_loguru(level: int) -> str:
    """Mapea nivel stdlib a string loguru."""
    if level >= logging.ERROR:   return "ERROR"
    if level >= logging.WARNING: return "WARNING"
    if level >= logging.INFO:    return "INFO"
    return "DEBUG"


#: Logger interno para tenacity
_TENACITY_LOGGER = _LoguruAdapter()


class HttpClient:
    """Cliente HTTP con retry, backoff y keep-alive."""

    def __init__(
        self,
        *,
        timeout: float = 20.0,
        max_retries: int = 3,
        user_agent: str = DEFAULT_USER_AGENT,
    ) -> None:
        self._timeout = timeout
        self._max_retries = max_retries
        self._session = requests.Session()
        self._session.headers.update({
            "User-Agent": user_agent,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "es-AR,es;q=0.9,en;q=0.8",
        })

    def get(self, url: str, **kwargs: Any) -> requests.Response:
        """GET con retries. Lanza HTTPError o TransientHttpError."""
        @retry(
            retry=retry_if_exception_type(TransientHttpError),
            stop=stop_after_attempt(self._max_retries + 1),
            wait=wait_exponential(multiplier=1.5, min=1, max=15),
            before_sleep=before_sleep_log(_TENACITY_LOGGER, logging.WARNING),
            reraise=True,
        )
        def _do_get() -> requests.Response:
            try:
                resp = self._session.get(url, timeout=self._timeout, **kwargs)
            except (requests.ConnectionError, requests.Timeout) as e:
                raise TransientHttpError(f"red caída para {url}: {e}") from e
            if resp.status_code in _RETRYABLE_HTTP:
                raise TransientHttpError(
                    f"HTTP {resp.status_code} para {url}"
                )
            return resp

        return _do_get()

    def close(self) -> None:
        self._session.close()

    def __enter__(self) -> HttpClient:
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()
