"""Resolución determinista del destinatario directo de una respuesta."""

from __future__ import annotations

from typing import Any, Protocol


class PostsReader(Protocol):
    """Lectura mínima requerida del repositorio de posts."""

    def get_post(self, post_id: str) -> dict[str, Any] | None: ...


def reply_target(
    post_id: str,
    posts_repo: PostsReader | None,
) -> dict[str, str] | None:
    """Cuenta destinataria directa de una respuesta, desde la relación del hilo.

    Devuelve None para posts originales, padres ausentes o registros sin handle.
    La justificación distingue explícitamente una respuesta de una @mención.
    """
    if posts_repo is None:
        return None
    try:
        post = posts_repo.get_post(post_id)
    except Exception:
        return None
    parent_id = str((post or {}).get("en_respuesta_a") or "").strip()
    if not parent_id:
        return None
    try:
        parent = posts_repo.get_post(parent_id)
    except Exception:
        parent = None
    handle = str((parent or {}).get("autor_handle") or "").strip().lstrip("@")
    if not handle:
        return None
    return {
        "actor": f"@{handle}",
        "tipo": "destinatario_mencionado",
        "justificacion": "Cuenta autora del post al que responde directamente.",
    }
