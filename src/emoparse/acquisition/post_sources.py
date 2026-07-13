# ══════════════════════════════════════════════════════════════════════════════
#  emoparse.acquisition.post_sources
#
#  Registry de adapters de posts, con carga perezosa.
#
#  La carga perezosa evita que importar `emoparse.acquisition` exija tener
#  instaladas las dependencias de todas las fuentes (p. ej. atproto): cada
#  adapter se importa recién cuando se lo pide, y un ImportError se traduce a
#  un mensaje con el extra a instalar.
# ══════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

import importlib
import inspect
from typing import Any

from emoparse.acquisition.base_posts import PostSourceAdapter, PostSourceError

#: source_id → (módulo, clase, extra de pip para el mensaje de error).
_POST_SOURCES: dict[str, tuple[str, str, str | None]] = {
    "bluesky": ("emoparse.acquisition.sources.bluesky", "BlueskyAdapter", "bluesky"),
    "x_api": ("emoparse.acquisition.sources.x_api", "XApiAdapter", None),
    "jsonl": ("emoparse.acquisition.sources.jsonl_import", "JsonlImportAdapter", None),
    "csv": ("emoparse.acquisition.sources.dataset_import", "CsvImportAdapter", None),
}

#: Ids disponibles, para `choices` del CLI.
POST_SOURCE_IDS: tuple[str, ...] = tuple(sorted(_POST_SOURCES))


def get_post_source(source_id: str, **kwargs: Any) -> PostSourceAdapter:
    """Construye el adapter de una fuente de posts.

    Filtra `kwargs` por la firma del constructor del adapter, de modo que el
    CLI pueda pasar un set uniforme de opciones (timeout, path, ...) sin que
    cada adapter deba aceptar parámetros que no usa.
    """
    if source_id not in _POST_SOURCES:
        raise PostSourceError(
            f"Fuente de posts desconocida: '{source_id}'. "
            f"Disponibles: {', '.join(POST_SOURCE_IDS)}"
        )
    module_name, class_name, extra = _POST_SOURCES[source_id]
    try:
        module = importlib.import_module(module_name)
    except ImportError as e:
        hint = f' Instalá el extra: pip install -e ".[{extra}]"' if extra else ""
        raise PostSourceError(
            f"No pude importar la fuente '{source_id}': {e}.{hint}"
        ) from e
    cls = getattr(module, class_name)

    accepted = _accepted_params(cls)
    filtered = {k: v for k, v in kwargs.items() if k in accepted and v is not None}
    try:
        adapter: PostSourceAdapter = cls(**filtered)
    except (TypeError, ValueError) as e:
        raise PostSourceError(
            f"No pude construir la fuente '{source_id}': {e}"
        ) from e
    return adapter


def _accepted_params(cls: type) -> set[str]:
    """Nombres de parámetros que acepta el constructor de la clase."""
    sig = inspect.signature(cls.__init__)
    return {
        name
        for name, p in sig.parameters.items()
        if name != "self"
        and p.kind in (p.POSITIONAL_OR_KEYWORD, p.KEYWORD_ONLY)
    }
