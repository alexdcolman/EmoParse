# ══════════════════════════════════════════════════════════════════════════════
#  emoparse.acquisition.base_posts
#
#  Contrato de los adapters de fuentes de posts.
# ══════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import date
from typing import Any, Iterator

from emoparse.acquisition.post_record import PostRecord


class PostSourceError(RuntimeError):
    """Error de una fuente de posts (auth, red, formato)."""


class PostSourceAdapter(ABC):
    """Adapter de una fuente de posts (plataforma, proveedor o archivo).

    Los adapters son iteradores puros: emiten `PostRecord` normalizados y no
    escriben a disco (la persistencia la maneja el CLI vía `JsonlAppender`).
    No todas las fuentes soportan los tres modos: el modo no soportado debe
    levantar NotImplementedError con un mensaje claro.
    """

    #: Identificador único de la fuente. Se usa en CLI (`--source <id>`).
    source_id: str

    #: True si la fuente puede completar `fetch_author_profile` (opt-in, --with-author-profile).
    supports_author_profile: bool = False

    def fetch_author_profile(self, handle: str) -> dict[str, Any] | None:
        """Perfil de un autor (autor_bio/autor_seguidores/autor_siguiendo/autor_verificado).

        Llamada extra por autor, fuera del flujo normal de iteración; solo se
        invoca si `supports_author_profile` es True.
        """
        raise NotImplementedError(
            f"La fuente '{self.source_id}' no soporta fetch_author_profile."
        )

    @abstractmethod
    def search(
        self,
        query: str,
        max_items: int | None = None,
        from_date: date | None = None,
        to_date: date | None = None,
        lang: str | None = None,
    ) -> Iterator[PostRecord]:
        """Itera posts que matchean una búsqueda (query, hashtag, etc.)."""

    @abstractmethod
    def fetch_thread(self, root_id: str) -> Iterator[PostRecord]:
        """Itera los posts de una conversación a partir de su raíz."""

    @abstractmethod
    def fetch_user(
        self,
        handle: str,
        max_items: int | None = None,
        from_date: date | None = None,
        to_date: date | None = None,
    ) -> Iterator[PostRecord]:
        """Itera los posts de una cuenta."""

    def close(self) -> None:
        """Libera recursos (sesiones HTTP, clientes). Default: no-op."""

    # ── Context manager ──────────────────────────────────────────────────────

    def __enter__(self) -> "PostSourceAdapter":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()
