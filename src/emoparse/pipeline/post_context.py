# ══════════════════════════════════════════════════════════════════════════════
#  emoparse.pipeline.post_context
#
#  Contexto conversacional y tecnodiscursivo para agentes sobre posts.
#
#  Providers deterministas que las stages LLM inyectan como columnas
#  opcionales del DataFrame de entrada (`contexto_hilo`, `tecno`,
#  `media_desc`, `emotion_rolling`):
#
#  - Contexto de hilo: la cadena de posts a los que la unidad responde
#    (padres, del más lejano al inmediato) y, si cita, el post citado.
#    Acotado por cantidad y caracteres: los padres inmediatos importan más.
#  - Contexto tecno: los tecnolingüísticos ya extraídos por technoparse,
#    en formato compacto, con el prior afectivo de los emojis cuando el
#    léxico o la etapa emoji_affect lo resolvieron.
#  - Emociones del hilo: las emociones que el pase 1 ya detectó en los
#    posts padre, como contexto del pase 2 en géneros conversacionales.
#  - Emociones detectadas: el inventario ya materializado de un discurso,
#    con su experienciador y su fuente, que `reframing` usa para juzgar el
#    estatuto de las emociones del post citado sin tener que reinferirlas.
# ══════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

import math
from typing import Any

from emoparse.pipeline.context_blocks import ContextBlockProvider
from emoparse.storage.emociones import EmocionesRepository
from emoparse.storage.frases import FrasesRepository
from emoparse.storage.hilos import HilosRepository
from emoparse.storage.posts import PostsRepository
from emoparse.storage.tecno import TecnoRepository
from emoparse.pipeline.technoparse import menciones_handles, parse_texto

#: Máximo de posts padre incluidos en el contexto de hilo.
_MAX_PARENTS = 5

#: Máximo de caracteres del contexto de hilo.
_MAX_CHARS = 1400

#: Máximo de intervenciones de cuentas mencionadas que participan del hilo.
_MAX_PARTICIPANT_POSTS = 2

#: Máximo de caracteres por intervención de participante mencionado.
_PARTICIPANT_POST_CHARS = 200

#: Máximo de emociones listadas del discurso citado. El inventario entra en
#: prompts batcheados: sin tope, un post muy anotado infla el batch entero.
_MAX_EMOCIONES = 6

#: Presupuestos por defecto de los bloques que antes no declaraban un límite
#: propio. Son cotas aproximadas y solo se pagan cuando el provider devuelve
#: contenido.
_TECNO_TOKENS = 300
_MEDIA_TOKENS = 400
_EMBED_TOKENS = 300
_EMOCIONES_DETECTADAS_TOKENS = 300
_REFRAMING_TOKENS = 180


def _tokens_for_chars(max_chars: int) -> int:
    """Convierte una cota histórica de caracteres a tokens aproximados."""
    return max(1, math.ceil(max_chars / 3))


def make_hilo_context_provider(
    posts_repo: PostsRepository,
    hilos_repo: HilosRepository | None = None,
    max_parents: int = _MAX_PARENTS,
    max_chars: int = _MAX_CHARS,
    include_root: bool = False,
    include_participants: bool = True,
    max_participant_posts: int = _MAX_PARTICIPANT_POSTS,
    participant_post_chars: int = _PARTICIPANT_POST_CHARS,
) -> ContextBlockProvider:
    """Provider codigo → contexto conversacional formateado (o None).

    Arma, del más lejano al inmediato, la cadena de posts a los que la unidad
    responde (marcando el padre inmediato) y, si cita, el post citado. Con
    `hilos_repo`, antepone una señal de que el post integra un hilo de N
    mensajes. Si `include_root`, encabeza con el post que abrió la
    conversación: en hilos profundos las respuestas son elípticas y el root es
    lo que fija de qué se habla, a costo fijo de un post cualquiera sea la
    profundidad; se omite cuando coincide con la unidad analizada o con alguno
    de los padres ya mostrados. Si `include_participants`, suma hasta
    `max_participant_posts` intervenciones (acotadas a
    `participant_post_chars`) de cuentas mencionadas en el texto que además
    participan del hilo. El bloque se recorta a `max_chars` conservando el
    final (padre inmediato, cita y participantes)."""

    def provider(codigo: str) -> str | None:
        post = posts_repo.get_post(codigo)
        if post is None:
            return None

        lineas: list[str] = []
        conv_id = post.get("conversacion_id")

        # Señal de pertenencia a un hilo (barata, del repositorio de hilos).
        if hilos_repo is not None and conv_id:
            hilo = hilos_repo.get_hilo(str(conv_id))
            n_posts = hilo.get("n_posts") if isinstance(hilo, dict) else None
            if isinstance(n_posts, int) and n_posts > 1:
                lineas.append(
                    f"(este post forma parte de un hilo de {n_posts} mensajes)"
                )

        # Cadena de padres, del inmediato hacia arriba.
        padres: list[dict[str, Any] | None] = []
        actual = post
        vistos = {str(post["post_id"])}
        while len(padres) < max_parents:
            parent_id = actual.get("en_respuesta_a")
            if not parent_id:
                break
            padre = posts_repo.get_post(str(parent_id))
            if padre is None:
                padres.append(None)
                break
            if str(padre["post_id"]) in vistos:
                break
            vistos.add(str(padre["post_id"]))
            padres.append(padre)
            actual = padre

        inmediato = padres[0] if padres else None
        mostrados = {str(p["post_id"]) for p in padres if isinstance(p, dict)}

        # Post que abrió la conversación. Va primero: es el que fija el objeto
        # del que se habla cuando las respuestas son elípticas. Se omite si es
        # la propia unidad o si ya aparece en la cadena de padres.
        if include_root and conv_id and str(conv_id) not in mostrados \
                and str(conv_id) != str(post["post_id"]):
            raiz = posts_repo.get_post(str(conv_id))
            if raiz is not None:
                mostrados.add(str(raiz["post_id"]))
                lineas.append("inicio del hilo → " + _format_post(raiz))

        # Del más lejano al inmediato; el inmediato (al que responde) marcado.
        for p in reversed(padres):
            if p is None:
                lineas.append("(post anterior no capturado)")
            elif p is inmediato:
                lineas.append("responde a → " + _format_post(p))
            else:
                lineas.append(_format_post(p))

        # Post citado (quote): discurso referido explícito.
        cita_id = post.get("cita_a")
        if cita_id:
            citado = posts_repo.get_post(str(cita_id))
            if citado is not None:
                lineas.append("POST CITADO (discurso referido): " + _format_post(citado))
            else:
                lineas.append("POST CITADO (discurso referido): (no capturado)")

        # Posts de cuentas mencionadas que participan del hilo.
        if include_participants and conv_id and max_participant_posts > 0:
            extra = _posts_menciones_participantes(
                post, posts_repo, str(conv_id), mostrados,
                max_participant_posts, participant_post_chars,
            )
            if extra:
                lineas.append(
                    "POSTS DE CUENTAS MENCIONADAS QUE PARTICIPAN DEL HILO:"
                )
                lineas.extend(extra)

        if not lineas:
            return None
        texto = "\n".join(lineas)
        return texto

    return ContextBlockProvider(
        name="contexto_hilo",
        target_column="contexto_hilo",
        stages=("metadata", "enunciation", "emotions", "emotions_pass2"),
        token_budget=_tokens_for_chars(max_chars),
        scope="discurso",
        keep_tail=True,
        render_fn=lambda codigo, _unit_idx: provider(codigo),
    )


def _posts_menciones_participantes(
    post: dict[str, Any],
    posts_repo: PostsRepository,
    conv_id: str,
    ya_mostrados: set[str],
    max_posts: int,
    max_chars: int,
) -> list[str]:
    """Intervenciones (hasta `max_posts`) de cuentas mencionadas en el post que
    además participan del hilo, en su propia voz. Vacío si no hay menciones,
    si ninguna participa del hilo, o si sus posts ya se mostraron como padres."""
    texto = str(post.get("texto") or "")
    if not texto:
        return []
    handles = {
        str(m.valor_norm or m.valor).lstrip("@").lower()
        for m in menciones_handles(parse_texto(texto))
    }
    handles.discard(str(post.get("autor_handle") or "").lstrip("@").lower())
    handles.discard("")
    if not handles:
        return []
    try:
        conv_posts = posts_repo.list_by_conversacion(conv_id)
    except Exception:
        return []
    pid_actual = str(post["post_id"])
    out: list[str] = []
    for p in conv_posts:
        if len(out) >= max_posts:
            break
        pid = str(p.get("post_id"))
        if pid == pid_actual or pid in ya_mostrados:
            continue
        if str(p.get("autor_handle") or "").lstrip("@").lower() in handles:
            ya_mostrados.add(pid)
            out.append(_format_post_corto(p, max_chars))
    return out


def make_hilo_emotion_context_provider(
    posts_repo: PostsRepository,
    frases_repo: FrasesRepository,
    max_parents: int = _MAX_PARENTS,
    max_chars: int = _MAX_CHARS,
) -> ContextBlockProvider:
    """Provider codigo → emociones detectadas en los posts padre (o None).

    Contexto del pase 2 para géneros con `context_unit == "hilo"`: con una
    frase por discurso, el rolling intra-discurso es vacío; la referencia
    útil son las emociones que el pase 1 ya detectó en la cadena de posts a
    los que la unidad responde. Lee el payload `emociones` (pase 1) de cada
    padre: es determinista respecto del orden en que el propio pase 2
    procesa los posts.
    """

    def provider(codigo: str) -> str | None:
        post = posts_repo.get_post(codigo)
        if post is None:
            return None

        # Cadena de padres, del inmediato hacia arriba; solo entran los que
        # tienen emociones del pase 1 (sin emociones no hay contexto útil).
        cadena: list[str] = []
        actual = post
        vistos = {str(post["post_id"])}
        saltos = 0
        while saltos < max_parents:
            parent_id = actual.get("en_respuesta_a")
            if not parent_id:
                break
            padre = posts_repo.get_post(str(parent_id))
            if padre is None or str(padre["post_id"]) in vistos:
                break
            vistos.add(str(padre["post_id"]))
            saltos += 1
            linea = _format_post_emociones(padre, frases_repo)
            if linea:
                cadena.append(linea)
            actual = padre

        if not cadena:
            return None
        # Del más lejano al inmediato, como el contexto de hilo textual.
        cadena.reverse()
        texto = "\n".join(cadena)
        return texto

    return ContextBlockProvider(
        name="emociones_hilo",
        target_column="emotion_rolling",
        stages=("emotions_pass2",),
        token_budget=_tokens_for_chars(max_chars),
        scope="discurso",
        keep_tail=True,
        render_fn=lambda codigo, _unit_idx: provider(codigo),
    )


def make_tecno_context_provider(
    tecno_repo: TecnoRepository,
    emoji_lexicon: dict[str, Any] | None = None,
    hashtags_como_bloque: bool = False,
    token_budget: int = _TECNO_TOKENS,
) -> ContextBlockProvider:
    """Provider (codigo, unit_idx) → tecnolingüísticos formateados (o None).

    Los emojis repetidos se agrupan con un contador (`😡×2`): la repetición es
    intensificación, no información nueva, y listarla una vez por ocurrencia
    duplica el bloque sin agregar nada. Con `hashtags_como_bloque`, los
    hashtags se presentan como una sola marca compuesta en lugar de una
    entrada por hashtag: en los posts que cierran con una ráfaga acumulada, el
    enunciador los tira en bloque y no los enuncia de a uno.
    """
    lexicon = (emoji_lexicon or {}).get("emojis", {}) if emoji_lexicon else {}

    def provider(codigo: str, unit_idx: int) -> str | None:
        entidades = tecno_repo.list_for_unit(codigo, unit_idx)
        if not entidades:
            return None
        grupos: dict[str, list[str]] = {}
        emojis: dict[str, dict[str, Any]] = {}
        hashtags: list[str] = []
        for e in entidades:
            tipo = str(e["tipo"])
            if tipo == "emoji":
                # Agrupar por valor conservando el orden de aparición; la
                # primera ocurrencia aporta el afecto ya resuelto.
                slot = emojis.setdefault(str(e["valor"]), {"n": 0, "e": e})
                slot["n"] += 1
                continue
            if tipo == "hashtag" and hashtags_como_bloque:
                hashtags.append(str(e["valor"]))
                continue
            grupos.setdefault(tipo, []).append(_format_entidad(e, lexicon))
        if emojis:
            grupos["emoji"] = [
                _format_entidad(slot["e"], lexicon)
                + (f" ×{slot['n']}" if slot["n"] > 1 else "")
                for slot in emojis.values()
            ]
        partes = [
            f"{_LABELS.get(tipo, tipo)}: " + ", ".join(valores)
            for tipo, valores in grupos.items()
        ]
        if hashtags:
            partes.append(
                "hashtags (ráfaga acumulada: leelos como UNA marca compuesta, "
                "no uno por hashtag): " + " ".join(hashtags)
            )
        return " | ".join(partes)

    return ContextBlockProvider(
        name="tecnolinguisticos",
        target_column="tecno",
        stages=("emotions", "emotions_pass2"),
        token_budget=token_budget,
        scope="unidad",
        render_fn=lambda codigo, unit_idx: provider(codigo, int(unit_idx)),
    )


def make_media_context_provider(
    posts_repo: PostsRepository,
    token_budget: int = _MEDIA_TOKENS,
) -> ContextBlockProvider:
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

    return ContextBlockProvider(
        name="media_descripta",
        target_column="media_desc",
        stages=("emotions", "emotions_pass2"),
        token_budget=token_budget,
        scope="discurso",
        render_fn=lambda codigo, _unit_idx: provider(codigo),
    )


def make_embed_context_provider(
    posts_repo: PostsRepository,
    token_budget: int = _EMBED_TOKENS,
) -> ContextBlockProvider:
    """Provider codigo → información adjunta del post (campo `embed` + alts).

    Extrae del JSON crudo del post los subcampos informativos del embed
    (título, descripción y dominio de un link externo; presencia de video o
    gif) y suma los alt-text de las imágenes registradas en `media`. No
    requiere `vision_describe`: es metadata que la fuente ya trae. Devuelve
    None si el post no tiene adjuntos informativos.
    """

    def provider(codigo: str) -> str | None:
        post = posts_repo.get_post(codigo)
        if post is None:
            return None
        lineas: list[str] = []

        embed = _embed_dict(post.get("raw"))
        external = embed.get("external") if isinstance(embed, dict) else None
        if isinstance(external, dict):
            titulo = str(external.get("title") or "").strip()
            desc = str(external.get("description") or "").strip()
            dominio = _dominio(str(external.get("uri") or ""))
            partes = []
            if titulo:
                partes.append(f'título: "{titulo}"')
            if desc:
                partes.append(f'descripción: "{desc}"')
            if dominio:
                partes.append(f"sitio: {dominio}")
            if partes:
                lineas.append("[link adjunto] " + " | ".join(partes))
        py_type = str(embed.get("py_type") or "") if isinstance(embed, dict) else ""
        if "video" in py_type:
            lineas.append("[video adjunto]")

        for m in posts_repo.list_media(codigo):
            alt = str(m.get("alt_text") or "").strip()
            tipo = str(m.get("tipo") or "otro")
            if alt:
                lineas.append(f'[{tipo} adjunta] alt: "{alt}"')
            elif tipo == "gif":
                lineas.append("[gif adjunto]")

        return "\n".join(lineas) if lineas else None

    return ContextBlockProvider(
        name="adjuntos_fuente",
        target_column="adjuntos",
        stages=("metadata", "enunciation", "emotions", "emotions_pass2"),
        token_budget=token_budget,
        scope="discurso",
        render_fn=lambda codigo, _unit_idx: provider(codigo),
    )


def combine_context_providers(
    *providers: ContextBlockProvider | None,
    target_column: str | None = None,
    name: str | None = None,
) -> ContextBlockProvider | None:
    """Combina providers en un bloque concatenado con destino explícito.

    Ignora los ``None`` y conserva el objeto original cuando queda un solo
    provider y no se solicita cambiar su identidad. ``target_column`` permite
    declarar la columna real en la que la stage inyectará el bloque combinado.
    """
    activos = [p for p in providers if p is not None]
    if not activos:
        return None
    if len(activos) == 1 and target_column is None and name is None:
        return activos[0]

    def provider(codigo: str, unit_idx: int | None) -> str | None:
        partes = [texto for p in activos if (texto := p(codigo, unit_idx))]
        return "\n".join(partes) if partes else None

    stages = tuple(dict.fromkeys(stage for p in activos for stage in p.stages))
    scope = "unidad" if any(p.scope == "unidad" for p in activos) else "discurso"
    return ContextBlockProvider(
        name=name or "_y_".join(p.name for p in activos),
        target_column=target_column or activos[0].target_column,
        stages=stages,
        token_budget=sum(p.token_budget for p in activos),
        scope=scope,
        render_fn=provider,
    )


def _embed_dict(raw: Any) -> dict[str, Any]:
    """El dict `embed` del JSON crudo del post ({} si no hay).

    Bluesky lo trae en `record.embed` (el record de origen) y/o en `embed`
    (la vista hidratada); se prefiere el del record, que conserva el
    external completo.
    """
    if not isinstance(raw, dict):
        return {}
    record = raw.get("record")
    if isinstance(record, dict) and isinstance(record.get("embed"), dict):
        return record["embed"]
    if isinstance(raw.get("embed"), dict):
        return raw["embed"]
    return {}


def _dominio(uri: str) -> str:
    """Dominio legible de una URI (sin esquema ni www), '' si no parsea."""
    u = uri.strip()
    if not u:
        return ""
    u = u.split("://", 1)[-1].split("/", 1)[0]
    return u.removeprefix("www.")


def make_emociones_detectadas_provider(
    emociones_repo: EmocionesRepository,
    max_emociones: int = _MAX_EMOCIONES,
    token_budget: int = _EMOCIONES_DETECTADAS_TOKENS,
) -> ContextBlockProvider:
    """Provider codigo → emociones ya materializadas del discurso (o None).

    Lo consume `reframing` sobre el post CITADO: el agente tiene que juzgar
    si el citador asume o semiotiza las emociones de lo citado, y hoy las
    reinfiere del texto crudo, sin la ontología ni las heurísticas del
    género que sí tuvo la stage `emotions`. Con el inventario ya hecho, la
    tarea vuelve a ser una sola: el estatuto.

    El experienciador es lo que decide `asumidas` vs `semiotizadas` (una
    emoción cuyo experienciador era un tercero no se "asume" del mismo modo
    que la del propio autor citado), así que va siempre. La foria se suma
    solo si `characterizer` corrió: es dependencia blanda, el bloque se
    arma igual sin ella.
    """

    def provider(codigo: str) -> str | None:
        try:
            emociones = emociones_repo.list_emociones_of_discurso(codigo)
        except Exception:
            return None
        if not emociones:
            return None
        partes = [
            _format_emocion_detectada(e) for e in emociones[:max_emociones]
        ]
        restantes = len(emociones) - len(partes)
        if restantes > 0:
            partes.append(f"(+{restantes} más)")
        return " · ".join(partes)

    return ContextBlockProvider(
        name="emociones_detectadas",
        target_column="emociones_citadas",
        stages=("reframing",),
        token_budget=token_budget,
        scope="discurso",
        render_fn=lambda codigo, _unit_idx: provider(codigo),
    )


def make_reframing_context_provider(
    posts_repo: PostsRepository,
    token_budget: int = _REFRAMING_TOKENS,
) -> ContextBlockProvider:
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

    return ContextBlockProvider(
        name="reframing",
        target_column="reframing_context",
        stages=("judge",),
        token_budget=token_budget,
        scope="discurso",
        render_fn=lambda codigo, _unit_idx: provider(codigo),
    )


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


def _format_post_corto(post: dict[str, Any], max_chars: int) -> str:
    """Una línea '@autor: texto' recortada a `max_chars` (posts de participantes)."""
    texto = str(post.get("texto") or "").replace("\n", " ").strip()
    if len(texto) > max_chars:
        texto = texto[:max_chars] + "…"
    return f"@{post.get('autor_handle', '?')}: {texto}"


def _format_post_emociones(
    post: dict[str, Any],
    frases_repo: FrasesRepository,
) -> str | None:
    """Una línea con las emociones del pase 1 de un post, o None si no hay.

    Mismo formato por emoción que el historial rolling del pase 2
    ('exp siente tipo (modo)'), con el autor del post padre como etiqueta.
    """
    codigo = str(post["post_id"])
    partes: list[str] = []
    for unit_idx, _frase in frases_repo.list_frases_of_discurso(codigo):
        payload = frases_repo.get_payload(codigo, unit_idx, "emociones")
        if not isinstance(payload, list):
            continue
        for emo in payload:
            if not isinstance(emo, dict):
                continue
            exp = emo.get("experienciador", "?")
            tipo = emo.get("tipo_emocion", "?")
            modo = emo.get("modo_existencia", "?")
            partes.append(f"{exp} siente {tipo} ({modo})")
    if not partes:
        return None
    return f"[post padre @{post.get('autor_handle', '?')}] " + "; ".join(partes)


def _format_emocion_detectada(emocion: dict[str, Any]) -> str:
    """Una emoción materializada, compacta: 'tipo (exp: X ← fuente) [foria]'.

    Prefiere los canónicos (revisados o resueltos por referencia) sobre la
    inferencia cruda: sin eso, al prompt le llegan deícticos sueltos como
    "él", que no informan nada.
    """
    tipo = (
        emocion.get("tipo_emocion_canonico")
        or emocion.get("tipo_emocion")
        or "?"
    )
    exp = (
        emocion.get("experienciador_canonico")
        or emocion.get("experienciador")
        or "?"
    )
    fuente = (
        emocion.get("fuente_canonico")
        or emocion.get("fuente_inferencia")
        or ""
    )
    linea = f"{tipo} (exp: {exp}"
    if fuente:
        linea += f" ← {fuente}"
    linea += ")"
    foria = _foria_de(emocion.get("caracterizacion_payload"))
    return f"{linea} [{foria}]" if foria else linea


def _foria_de(payload: Any) -> str:
    """Foria de una emoción caracterizada ('' si `characterizer` no corrió)."""
    import json as _json

    if isinstance(payload, str) and payload:
        try:
            payload = _json.loads(payload)
        except _json.JSONDecodeError:
            return ""
    if not isinstance(payload, dict):
        return ""
    return str(payload.get("foria") or "")


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
