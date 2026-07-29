# ══════════════════════════════════════════════════════════════════════════════
#  emoparse.core.prompts.metadata
#
#  Wrapper Jinja2. Firma pública estable.
# ══════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

from emoparse.core.prompts._loader import render


def render_system(
    diccionario: str,
    tipos: str | None = None,
    template: str = "metadata_system",
) -> str:
    """SYSTEM de metadata.

    `diccionario` es el dump JSON-stringificado de tipos de discurso.
    `tipos` es el vocabulario cerrado formateado cuando el género restringe
    los tipos válidos; el template alternativo (vía `Genre.prompt_overrides`)
    lo consume en lugar del diccionario.
    """
    return render(template, diccionario=diccionario, tipos=tipos)


def render_user(
    codigo: str,
    resumen: str,
    fragmentos: str,
    bio: str | None = None,
    adjuntos: str | None = None,
    contexto_hilo: str | None = None,
) -> str:
    """USER de metadata. Datos variables del discurso concreto.

    `bio` (cuenta autora) y `adjuntos` (embed del post) son contexto
    opcional: ayudan a situar el tipo de discurso sin forzarlo.
    `contexto_hilo` es la conversación en la que se inserta el post: el tipo
    de discurso puede transformarse a lo largo de un hilo, así que ayuda a
    clasificar el post en su lugar, sin determinarlo.
    """
    return render(
        "metadata_user",
        codigo=codigo,
        resumen=resumen,
        fragmentos=fragmentos,
        bio=bio,
        adjuntos=adjuntos,
        contexto_hilo=contexto_hilo,
    )
