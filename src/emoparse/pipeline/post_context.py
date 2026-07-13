# ══════════════════════════════════════════════════════════════════════════════
#  emoparse.pipeline.post_context
#
#  Contexto conversacional y tecnodiscursivo para agentes sobre posts.
#
#  Dos providers deterministas que las stages LLM inyectan como columnas
#  opcionales del DataFrame de entrada (`contexto_hilo`, `tecno`):
#
#  - Contexto de hilo: la cadena de posts a los que la unidad responde
#    (padres, del más lejano al inmediato) y, si cita, el post citado.
#    Acotado por cantidad y caracteres: los padres inmediatos importan más.
#  - Contexto tecno: los tecnolingüísticos ya extraídos por technoparse,
#    en formato compacto, con el prior afectivo de los emojis cuando el
#    léxico o la etapa emoji_affect lo resolvieron.
# ══════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

from typing import Any, Callable

from emoparse.storage.posts import PostsRepository
from emoparse.storage.tecno import TecnoRepository

#: Máximo de posts padre incluidos en el contexto de hilo.
_MAX_PARENTS = 5

#: Máximo de caracteres del contexto de hilo.
_MAX_CHARS = 1400


def make_hilo_context_provider(
    posts_repo: PostsRepository,
    max_parents: int = _MAX_PARENTS,
    max_chars: int = _MAX_CHARS,
) -> Callable[[str], str | None]:
    """Provider codigo → contexto conversacional formateado (o None)."""

    def provider(codigo: str) -> str | None:
        post = posts_repo.get_post(codigo)
        if post is None:
            return None

        lineas: list[str] = []

        # Cadena de padres, del inmediato hacia arriba.
        cadena: list[str] = []
        actual = post
        vistos = {str(post["post_id"])}
        while len(cadena) < max_parents:
            parent_id = actual.get("en_respuesta_a")
            if not parent_id:
                break
            padre = posts_repo.get_post(str(parent_id))
            if padre is None:
                cadena.append("(post anterior no capturado)")
                break
            if str(padre["post_id"]) in vistos:
                break
            vistos.add(str(padre["post_id"]))
            cadena.append(_format_post(padre))
            actual = padre
        if cadena:
            cadena.reverse()
            lineas.extend(cadena)

        # Post citado (quote): discurso referido explícito.
        cita_id = post.get("cita_a")
        if cita_id:
            citado = posts_repo.get_post(str(cita_id))
            if citado is not None:
                lineas.append("POST CITADO (discurso referido): " + _format_post(citado))
            else:
                lineas.append("POST CITADO (discurso referido): (no capturado)")

        if not lineas:
            return None
        texto = "\n".join(lineas)
        if len(texto) > max_chars:
            # Recortar desde el principio: los padres inmediatos y la cita
            # (al final) son lo más relevante para desambiguar.
            texto = "(...)\n" + texto[-max_chars:]
        return texto

    return provider


def make_tecno_context_provider(
    tecno_repo: TecnoRepository,
    emoji_lexicon: dict[str, Any] | None = None,
) -> Callable[[str, int], str | None]:
    """Provider (codigo, unit_idx) → tecnolingüísticos formateados (o None)."""
    lexicon = (emoji_lexicon or {}).get("emojis", {}) if emoji_lexicon else {}

    def provider(codigo: str, unit_idx: int) -> str | None:
        entidades = tecno_repo.list_for_unit(codigo, unit_idx)
        if not entidades:
            return None
        grupos: dict[str, list[str]] = {}
        for e in entidades:
            tipo = str(e["tipo"])
            grupos.setdefault(tipo, []).append(_format_entidad(e, lexicon))
        partes = [
            f"{_LABELS.get(tipo, tipo)}: " + ", ".join(valores)
            for tipo, valores in grupos.items()
        ]
        return " | ".join(partes)

    return provider


def make_media_context_provider(
    posts_repo: PostsRepository,
) -> Callable[[str], str | None]:
    """Provider codigo → descripciones generadas de la media del post.

    Requiere la stage `vision_describe` corrida antes; sin descripciones
    devuelve None (los posts sin media no pagan costo alguno).
    """

    def provider(codigo: str) -> str | None:
        descripciones = posts_repo.media_descripciones_of_post(codigo)
        if not descripciones:
            return None
        lineas = []
        for i, m in enumerate(descripciones, start=1):
            payload = m.get("descripcion_payload")
            if not isinstance(payload, dict):
                continue
            linea = (
                f"[imagen {i}: {payload.get('tipo_imagen', 'otro')}] "
                f"{payload.get('descripcion', '')}"
            )
            texto = str(payload.get("texto_en_imagen") or "").strip()
            if texto:
                linea += f' | TEXTO EN LA IMAGEN: "{texto}"'
            tecno = str(payload.get("elementos_tecnograficos") or "").strip()
            if tecno:
                linea += f" | Tecnográficos: {tecno}"
            lineas.append(linea)
        return "\n".join(lineas) if lineas else None

    return provider


def make_reframing_context_provider(
    posts_repo: PostsRepository,
) -> Callable[[str], str | None]:
    """Provider codigo → línea con la operación de redocumentación del post.

    Solo posts que citan/repostean y ya clasificados por la stage reframing.
    """
    import json as _json

    def provider(codigo: str) -> str | None:
        post = posts_repo.get_post(codigo)
        if post is None:
            return None
        raw = post.get("reframing_payload")
        if not raw:
            return None
        payload = raw
        if isinstance(raw, str):
            try:
                payload = _json.loads(raw)
            except _json.JSONDecodeError:
                return None
        if not isinstance(payload, dict):
            return None
        return (
            "OPERACIÓN SOBRE LO CITADO (clasificada): "
            f"{payload.get('operacion', '?')} | emociones del texto citado: "
            f"{payload.get('emociones_citadas', '?')}"
        )

    return provider


# ══════════════════════════════════════════════════════════════════════════════
#  Formateo
# ══════════════════════════════════════════════════════════════════════════════

_LABELS = {
    "hashtag": "hashtags",
    "mencion": "menciones",
    "url": "urls",
    "emoji": "emojis",
    "tecnografismo": "tecnografismos",
}


def _format_post(post: dict[str, Any]) -> str:
    """Una línea '@autor: texto' truncada."""
    texto = str(post.get("texto") or "").replace("\n", " ").strip()
    if len(texto) > 280:
        texto = texto[:280] + "…"
    return f"@{post.get('autor_handle', '?')}: {texto}"


def _format_entidad(e: dict[str, Any], lexicon: dict[str, Any]) -> str:
    """Representación compacta de una entidad para el prompt."""
    valor = str(e["valor"])
    extra = e.get("extra") if isinstance(e.get("extra"), dict) else {}
    tipo = str(e["tipo"])

    if tipo == "hashtag":
        funcion = extra.get("funcion_sintactica")
        return f"{valor} ({funcion})" if funcion else valor

    if tipo == "mencion":
        posicion = extra.get("posicion")
        return f"{valor} ({posicion})" if posicion else valor

    if tipo == "emoji":
        afecto = extra.get("afecto")
        if isinstance(afecto, dict) and afecto.get("candidato"):
            det = str(afecto.get("candidato"))
            foria = afecto.get("foria")
            return f"{valor} [{det}{', ' + str(foria) if foria else ''}]"
        prior = lexicon.get(valor)
        if isinstance(prior, dict):
            cands = "/".join(prior.get("candidatos", [])[:2])
            amb = ", ambiguo" if prior.get("ambiguo") else ""
            return f"{valor} [candidatos: {cands}{amb}]" if cands else valor
        return valor

    if tipo == "tecnografismo":
        subtipo = extra.get("subtipo", "")
        return f"'{valor}' ({subtipo})" if subtipo else f"'{valor}'"

    return str(e.get("valor_norm") or valor)
