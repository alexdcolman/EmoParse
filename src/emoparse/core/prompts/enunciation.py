# ══════════════════════════════════════════════════════════════════════════════
#  emoparse.core.prompts.enunciation
#
#  Wrapper Jinja2. Firma pública estable.
# ══════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

from emoparse.core.prompts._loader import render


def render_system(
    heuristicas: str | None = None,
    colectivos: str | None = None,
    template: str = "enunciation_system",
) -> str:
    """SYSTEM de enunciation.

    `colectivos` es la ontología de colectivos de identificación formateada
    por tipo de discurso; si None, no se inyecta esa sección. `template`
    permite a los géneros sustituir el system vía `Genre.prompt_overrides`
    (p. ej. 'enunciation_system_tuit'); el alternativo debe aceptar las
    mismas variables.
    """
    return render(
        template,
        heuristicas=heuristicas,
        colectivos=colectivos,
    )


def render_user(
    codigo: str,
    resumen: str,
    fragmentos: str,
    enunciador: str | None = None,
    repertorio: str | None = None,
    bio: str | None = None,
    adjuntos: str | None = None,
    roles_block: str | None = None,
    contexto_hilo: str | None = None,
) -> str:
    """USER de enunciation con datos del discurso concreto.

    `enunciador` es el enunciador ya identificado (determinista o por el
    sub-paso de identificación); si se pasa, el prompt instruye devolverlo
    tal cual. `repertorio` es el texto formateado de colectivos conocidos de
    ese enunciador (KB de enunciación); si None, no se inyecta esa sección.
    `bio` es la bio de la cuenta autora y `adjuntos` la información del embed
    del post: contexto opcional que no fuerza inferencias. `roles_block` lista
    los roles enunciativos válidos para el tipo de discurso de este documento
    (con su descripción y, si hay, indicadores orientativos). `contexto_hilo`
    es la conversación a la que el post pertenece, para desambiguar la
    destinación sin ser fuente de enunciatarios.
    """
    return render(
        "enunciation_user",
        codigo=codigo,
        resumen=resumen,
        fragmentos=fragmentos,
        enunciador=enunciador,
        repertorio=repertorio,
        bio=bio,
        adjuntos=adjuntos,
        roles_block=roles_block,
        contexto_hilo=contexto_hilo,
    )


def render_enunciator_id_system(heuristicas: str | None = None) -> str:
    """SYSTEM del sub-paso de identificación del enunciador.

    Prompt mínimo (apto para modelo chico) que identifica solo la
    denominación normalizada del enunciador; el resto de la estructura
    enunciativa se identifica después, con el enunciador ya fijado.
    """
    return render("enunciator_id_system", heuristicas=heuristicas)
