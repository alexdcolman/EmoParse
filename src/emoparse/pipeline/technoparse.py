# ══════════════════════════════════════════════════════════════════════════════
#  emoparse.pipeline.technoparse
#
#  Extracción determinista de tecnolingüísticos, sin LLM.
#
#  El principio rector es no borrar sino anotar: el texto de la unidad no se
#  altera nunca; cada tecnolingüístico (hashtag, mención, URL, emoji,
#  tecnografismo) se extrae con sus offsets [inicio, fin) y sus atributos.
#  Funciones puras y testeables; la persistencia vive en `storage.tecno` y la
#  orquestación en `pipeline.stages.TechnoparseStage`.
#
#  Tipos de entidad:
#  - hashtag: con función sintáctica 'integrada' (participa de la sintaxis de
#    la frase) o 'pospuesta' (etiqueta en el bloque final del post).
#  - mencion: @handle, con posición 'vocativo_inicial' (encabeza el post,
#    convención de reply) o 'integrada'.
#  - url: normalizada a su dominio. Se reconocen tanto los links con esquema
#    como los que el post trae pelados ("youtube.com/watch", "bit.ly/x"),
#    porque la plataforma los recorta y les pega una elipsis.
#  - emoji: normalizado a shortcode. Con la librería `emoji` (extra `techno`)
#    se capturan secuencias ZWJ y modificadores; sin ella, un fallback por
#    rangos Unicode cubre los emojis simples.
#  - tecnografismo: subtipos 'mayusculas' (con alcance 'palabra' aislada,
#    'expresion' para corridas de varias palabras en caps, o 'frase' cuando
#    cubren casi todo el texto, normalizadas a 'mayusculas_sostenidas'; una
#    corrida no se interrumpe por cifras ni signos intercalados),
#    'alargamiento' (letra repetida ≥3), 'risa' (jajaja y variantes),
#    'puntuacion' (!!, ?!, ...). Los tokens aislados en caps de menos de 5
#    letras o sin vocales se omiten (siglas, no tecnografismos), y los
#    suspensivos pegados o inmediatamente posteriores a una URL también
#    (truncado automático de la plataforma, no gesto expresivo).
# ══════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any


try:
    import emoji as _emoji_lib
except ImportError:
    _emoji_lib = None


@dataclass(frozen=True)
class TecnoEntidad:
    """Un tecnolingüístico localizado en el texto de una unidad."""

    tipo: str          # 'hashtag'|'mencion'|'url'|'emoji'|'tecnografismo'
    valor: str         # tal como aparece en el texto
    valor_norm: str    # normalizado (ver docstring del módulo)
    inicio: int        # offset inicial (inclusive)
    fin: int           # offset final (exclusive)
    extra: dict[str, Any] = field(default_factory=dict)


# ══════════════════════════════════════════════════════════════════════════════
#  Regexes
# ══════════════════════════════════════════════════════════════════════════════

#: Hashtag: '#' + secuencia de caracteres de palabra (unicode).
_HASHTAG_RE = re.compile(r"#(\w+)", re.UNICODE)

#: Mención: '@' + handle. Cubre handles de X (\w) y de Bluesky/Mastodon
#: (con puntos y guiones internos, sin terminar en ellos).
_MENCION_RE = re.compile(r"@([A-Za-z0-9_](?:[A-Za-z0-9_.\-]*[A-Za-z0-9_])?)")

#: Dominios de primer nivel admitidos en las URLs sin esquema. La lista
#: acotada evita confundir un link con una abreviatura o con una oración sin
#: espacio tras el punto ("terminó.Ver más"): sin ella, cualquier palabra con
#: punto interno pasaría por URL.
_TLD = (
    "com|net|org|edu|gov|gob|int|mil|info|io|ly|me|tv|app|dev|news|ai|xyz"
    "|link|site|online|blog|press|social|fm|cc|sh|be|gl|gd"
    "|ar|bo|br|ca|cl|co|de|es|fr|it|mx|pe|pt|py|uk|us|uy|ve"
)

#: URL con esquema, con `www.` o con dominio pelado ("youtube.com/watch",
#: "bit.ly/x", "clarin.com"). Los links sin esquema son habituales en los
#: posts: la plataforma los renderiza recortados y les pega una elipsis, que
#: sin este reconocimiento quedaba suelta y se anotaba como suspensivos
#: expresivos. El lookbehind protege los handles de Bluesky y Mastodon
#: (@juan.bsky.social no es una URL).
_URL_RE = re.compile(
    r"(?:https?://|www\.)\S+"
    r"|(?<![@\w.\-/])(?:[\w\-]+\.)+(?:" + _TLD + r")(?:\.[a-z]{2})?"
    r"(?:/\S*)?(?![\w\-])",
    re.UNICODE | re.IGNORECASE,
)

#: Puntuación final que no forma parte de una URL.
_URL_TRAIL = ".,;:!?)»\"'”’…"

#: Prefijo de retweet clásico ("RT @user: ...").
_RT_PREFIX_RE = re.compile(r"^RT\s+@([A-Za-z0-9_](?:[A-Za-z0-9_.\-]*[A-Za-z0-9_])?):?\s*")

#: Token íntegramente en mayúsculas (≥2 letras). Los tokens se agrupan en
#: corridas (ver _caps_runs); el umbral por token aislado se aplica después.
_CAPS_TOKEN_RE = re.compile(r"\b[A-ZÁÉÍÓÚÜÑ]{2,}\b")

#: Longitud máxima de un separador entre dos tokens de una misma corrida de
#: mayúsculas. Acota la unión a separadores breves, no a bloques de texto.
_CAPS_GAP_MAX = 24

#: Vocales (con acentos) para el descarte de siglas.
_VOCALES = set("AEIOUÁÉÍÓÚÜ")

#: Palabra genérica (≥2 letras) para estimar la cobertura de mayúsculas.
_PALABRA_RE = re.compile(r"\b[^\W\d_]{2,}\b", re.UNICODE)

#: Alargamiento: una letra repetida 3+ veces dentro de una palabra.
_ALARGAMIENTO_RE = re.compile(r"\b\w*?(\w)\1{2,}\w*\b", re.UNICODE)

#: Risas: jajaja / jejeje / jsjsjs / kakaka y variantes, ≥4 caracteres.
_RISA_RE = re.compile(r"\b(?:[jk][aeiou]){2,}[jk]?\b|\b(?:js){2,}j?\b", re.IGNORECASE)

#: Puntuación expresiva: !!+, ??+, combinaciones ?!/!?, suspensivos.
_PUNTUACION_RE = re.compile(r"(?:[!?]*[!?]{2,}[!?]*|\.{3,}|…+)")

#: Fallback de emojis por rangos Unicode (BMP/SMP más frecuentes). No captura
#: secuencias ZWJ compuestas; para eso está la librería `emoji`.
_EMOJI_FALLBACK_RE = re.compile(
    "["
    "\U0001F300-\U0001FAFF"   # símbolos, emoticones, transporte, suplementos
    "\U00002600-\U000027BF"   # misc symbols + dingbats
    "\U0001F1E6-\U0001F1FF"   # banderas (regional indicators)
    "\u2764\u2B50\u2B06\u2B07"
    "]+"
)


# ══════════════════════════════════════════════════════════════════════════════
#  API principal
# ══════════════════════════════════════════════════════════════════════════════

def parse_texto(texto: str) -> list[TecnoEntidad]:
    """Extrae todos los tecnolingüísticos de un texto, ordenados por inicio."""
    entidades: list[TecnoEntidad] = []
    entidades.extend(extract_urls(texto))
    # Las URLs se enmascaran para el resto de los extractores con su span
    # crudo completo (incluida la elipsis de truncado que la plataforma pega
    # al link): un '#', un 'www' o unos '...' dentro o al final de una URL no
    # son tecnolingüísticos.
    url_spans = _url_raw_spans(texto)
    ocupado = list(url_spans)
    entidades.extend(extract_hashtags(texto, ocupado))
    entidades.extend(extract_menciones(texto, ocupado))
    emojis = extract_emojis(texto)
    entidades.extend(emojis)
    ocupado = url_spans + _spans([e for e in entidades if e.tipo != "url"])
    tecnografismos = extract_tecnografismos(texto, ocupado)
    # Suspensivos inmediatamente posteriores a una URL (a lo sumo un espacio
    # de por medio): truncado de plataforma, no gesto expresivo.
    fines_url = {fin for _, fin in url_spans}
    tecnografismos = [
        e for e in tecnografismos
        if not (
            e.extra.get("subtipo") == "puntuacion"
            and e.valor_norm == "suspensivos"
            and (
                any(e.inicio - fin in (0, 1) for fin in fines_url)
                or _cierra_token_de_link(texto, e.inicio)
            )
        )
    ]
    entidades.extend(tecnografismos)
    entidades.sort(key=lambda e: (e.inicio, e.fin))
    return entidades


def detect_repost_prefix(texto: str) -> str | None:
    """Devuelve el handle del prefijo 'RT @user:' si el texto empieza así."""
    m = _RT_PREFIX_RE.match(texto)
    return m.group(1) if m else None


def menciones_handles(entidades: list[TecnoEntidad]) -> list[TecnoEntidad]:
    """Filtra las entidades de tipo mención."""
    return [e for e in entidades if e.tipo == "mencion"]


# ══════════════════════════════════════════════════════════════════════════════
#  Extractores
# ══════════════════════════════════════════════════════════════════════════════

def extract_urls(texto: str) -> list[TecnoEntidad]:
    """URLs http(s), normalizadas a su dominio."""
    out: list[TecnoEntidad] = []
    for m in _URL_RE.finditer(texto):
        raw = m.group(0)
        # La puntuación de cierre pertenece a la frase, no a la URL.
        trimmed = raw.rstrip(_URL_TRAIL)
        fin = m.start() + len(trimmed)
        dominio = _dominio(trimmed)
        out.append(TecnoEntidad(
            tipo="url", valor=trimmed, valor_norm=dominio,
            inicio=m.start(), fin=fin,
        ))
    return out


def extract_hashtags(
    texto: str,
    ocupado: list[tuple[int, int]] | None = None,
) -> list[TecnoEntidad]:
    """Hashtags con su función sintáctica (integrada / pospuesta)."""
    ocupado = ocupado or []
    cola_inicio = _inicio_bloque_final(texto)
    out: list[TecnoEntidad] = []
    for m in _HASHTAG_RE.finditer(texto):
        if _solapa(m.start(), m.end(), ocupado):
            continue
        funcion = "pospuesta" if m.start() >= cola_inicio else "integrada"
        out.append(TecnoEntidad(
            tipo="hashtag",
            valor=m.group(0),
            valor_norm=m.group(1).lower(),
            inicio=m.start(),
            fin=m.end(),
            extra={"funcion_sintactica": funcion},
        ))
    return out


def extract_menciones(
    texto: str,
    ocupado: list[tuple[int, int]] | None = None,
) -> list[TecnoEntidad]:
    """Menciones @handle con su posición (vocativo inicial / integrada)."""
    ocupado = ocupado or []
    fin_vocativo = _fin_bloque_vocativo(texto)
    out: list[TecnoEntidad] = []
    for m in _MENCION_RE.finditer(texto):
        if _solapa(m.start(), m.end(), ocupado):
            continue
        posicion = "vocativo_inicial" if m.end() <= fin_vocativo else "integrada"
        out.append(TecnoEntidad(
            tipo="mencion",
            valor=m.group(0),
            valor_norm=m.group(1).lower(),
            inicio=m.start(),
            fin=m.end(),
            extra={"posicion": posicion},
        ))
    return out


def extract_emojis(texto: str) -> list[TecnoEntidad]:
    """Emojis con shortcode. Usa la librería `emoji` si está disponible."""
    if _emoji_lib is not None:
        out = []
        for item in _emoji_lib.emoji_list(texto):
            ch = item["emoji"]
            out.append(TecnoEntidad(
                tipo="emoji",
                valor=ch,
                valor_norm=_emoji_lib.demojize(ch, language="es").strip(":"),
                inicio=item["match_start"],
                fin=item["match_end"],
            ))
        return out
    # Fallback sin dependencia: rangos básicos, cada codepoint por separado.
    out = []
    for m in _EMOJI_FALLBACK_RE.finditer(texto):
        for offset, ch in enumerate(m.group(0)):
            nombre = unicodedata.name(ch, "emoji").lower().replace(" ", "_")
            out.append(TecnoEntidad(
                tipo="emoji", valor=ch, valor_norm=nombre,
                inicio=m.start() + offset, fin=m.start() + offset + 1,
            ))
    return out


def extract_tecnografismos(
    texto: str,
    ocupado: list[tuple[int, int]] | None = None,
) -> list[TecnoEntidad]:
    """Tecnografismos: mayúsculas sostenidas, alargamientos, risas, puntuación.

    Un mismo span produce una sola entidad: la primera clase que lo capture
    (orden: risa → mayúsculas → alargamiento → puntuación) se queda con él.
    Las mayúsculas se agrupan en corridas para respetar expresiones y
    fórmulas ("HIJO DE PUTA", "LEY DE EXTRANJERIZACIÓN DE TIERRAS" son una
    entidad cada una, no una por palabra); si cubren casi toda la frase, una
    única entidad normalizada a 'mayusculas_sostenidas' evita la dispersión.
    Un token aislado en caps con letra repetida ("GOOOOL") se clasifica como
    alargamiento, y "JAJAJA" sigue siendo risa.
    """
    externos = ocupado or []
    out: list[TecnoEntidad] = []

    def _libre(inicio: int, fin: int) -> bool:
        return not _solapa(inicio, fin, externos) and not _solapa(
            inicio, fin, _spans(out)
        )

    for m in _RISA_RE.finditer(texto):
        if len(m.group(0)) < 4 or not _libre(m.start(), m.end()):
            continue
        out.append(TecnoEntidad(
            tipo="tecnografismo", valor=m.group(0),
            valor_norm="risa", inicio=m.start(), fin=m.end(),
            extra={"subtipo": "risa"},
        ))

    out.extend(_extract_mayusculas(texto, externos, out))

    for m in _ALARGAMIENTO_RE.finditer(texto):
        if not _libre(m.start(), m.end()):
            continue
        if any(ch.isdigit() for ch in m.group(0)):
            continue  # '2000', 'v1.000': repetición numérica, no expresiva
        colapsado = re.sub(r"(\w)\1{2,}", r"\1", m.group(0))
        out.append(TecnoEntidad(
            tipo="tecnografismo", valor=m.group(0),
            valor_norm=colapsado.lower(), inicio=m.start(), fin=m.end(),
            extra={"subtipo": "alargamiento"},
        ))

    for m in _PUNTUACION_RE.finditer(texto):
        if not _libre(m.start(), m.end()):
            continue
        out.append(TecnoEntidad(
            tipo="tecnografismo", valor=m.group(0),
            valor_norm=_norm_puntuacion(m.group(0)),
            inicio=m.start(), fin=m.end(),
            extra={"subtipo": "puntuacion"},
        ))
    return out


def _extract_mayusculas(
    texto: str,
    externos: list[tuple[int, int]],
    previas: list[TecnoEntidad],
) -> list[TecnoEntidad]:
    """Mayúsculas sostenidas como corridas, con alcance frase/expresión/palabra.

    Agrupa en corridas los tokens en caps separados solo por material no
    léxico (espacios, comas, cifras, signos: "UN 90% POR DEBAJO" no corta la
    corrida), sin atravesar otra entidad ya extraída. Si las corridas cubren
    al menos el 80% de las palabras del texto (con un mínimo de 4), emite una
    única entidad normalizada a 'mayusculas_sostenidas' (alcance 'frase'). Si
    no, cada corrida multi-palabra es una entidad (alcance 'expresion') y cada
    token aislado, una entidad (alcance 'palabra') solo si tiene al menos 5
    letras y alguna vocal: los tokens cortos o sin vocales son siglas, no
    tecnografismos. Un token aislado con letra repetida se cede al extractor
    de alargamientos.
    """
    def _libre(inicio: int, fin: int) -> bool:
        return not _solapa(inicio, fin, externos) and not _solapa(
            inicio, fin, _spans(previas)
        )

    tokens = [
        m for m in _CAPS_TOKEN_RE.finditer(texto) if _libre(m.start(), m.end())
    ]
    if not tokens:
        return []

    # Corridas: tokens consecutivos separados solo por material no léxico
    # (espacios, comas, cifras, signos) y sin ninguna otra entidad de por medio.
    ocupados = externos + _spans(previas)
    runs: list[list[re.Match[str]]] = []
    actual = [tokens[0]]
    for tok in tokens[1:]:
        inicio, fin = actual[-1].end(), tok.start()
        gap = texto[inicio:fin]
        if _gap_continua(gap) and not _solapa(inicio, fin, ocupados):
            actual.append(tok)
        else:
            runs.append(actual)
            actual = [tok]
    runs.append(actual)

    out: list[TecnoEntidad] = []
    palabras = [
        m for m in _PALABRA_RE.finditer(texto)
        if not _solapa(m.start(), m.end(), externos)
    ]
    n_caps = sum(len(r) for r in runs)
    if palabras and len(palabras) >= 4 and n_caps / len(palabras) >= 0.8:
        inicio = runs[0][0].start()
        fin = runs[-1][-1].end()
        out.append(TecnoEntidad(
            tipo="tecnografismo", valor=texto[inicio:fin],
            valor_norm="mayusculas_sostenidas", inicio=inicio, fin=fin,
            extra={"subtipo": "mayusculas", "alcance": "frase"},
        ))
        return out

    for run in runs:
        if len(run) >= 2:
            # Una corrida de mayúsculas es un grito completo: se emite entera,
            # con las siglas que contenga ("BASTA FMI" es un solo tecnografismo).
            inicio, fin = run[0].start(), run[-1].end()
            valor = texto[inicio:fin]
            out.append(TecnoEntidad(
                tipo="tecnografismo", valor=valor,
                valor_norm=re.sub(r"[\s,]+", " ", valor).strip().lower(),
                inicio=inicio, fin=fin,
                extra={"subtipo": "mayusculas", "alcance": "expresion"},
            ))
            continue
        _emitir_token_aislado(run[0], texto, out)
    return out


def _emitir_token_aislado(
    m: re.Match[str],
    texto: str,
    out: list[TecnoEntidad],
) -> None:
    """Emite un token en caps aislado, salvo que sea sigla o alargamiento.

    Solo aplica al token solitario: una sigla suelta ("FMI", "CFK") no es un
    grito, así que no se anota. Dentro de una corrida, en cambio, la sigla
    es parte del grito y no pasa por acá.
    """
    palabra = m.group(0)
    if re.search(r"(\w)\1{2,}", palabra):
        return  # "GOOOOL": lo toma el extractor de alargamientos
    if len(palabra) < 5 or not (_VOCALES & set(palabra)):
        return  # sigla probable (LLA, CFK, PAMI, FMI)
    out.append(TecnoEntidad(
        tipo="tecnografismo", valor=palabra,
        valor_norm=palabra.lower(), inicio=m.start(), fin=m.end(),
        extra={"subtipo": "mayusculas", "alcance": "palabra"},
    ))


# ══════════════════════════════════════════════════════════════════════════════
#  Helpers
# ══════════════════════════════════════════════════════════════════════════════

def _url_raw_spans(texto: str) -> list[tuple[int, int]]:
    """Spans crudos de las URLs (match completo, sin recorte de puntuación)."""
    return [(m.start(), m.end()) for m in _URL_RE.finditer(texto)]


#: Token con forma de dominio (punto seguido de letras) que no cerró como URL.
_TOKEN_LINK_RE = re.compile(r"[\w\-/?=&%]+\.[A-Za-z]{2,}[\w\-/?=&%.]*\Z")


def _cierra_token_de_link(texto: str, inicio: int) -> bool:
    """True si los suspensivos que empiezan en `inicio` cierran un link.

    Segunda red para los dominios que la lista de TLD no cubre: si lo que
    precede a la elipsis, hasta el espacio anterior, tiene forma de dominio,
    la elipsis es el recorte de la plataforma y no un gesto expresivo.
    """
    previo = texto[:inicio].rsplit(" ", 1)[-1].rsplit("\n", 1)[-1]
    return bool(previo) and _TOKEN_LINK_RE.search(previo) is not None


def _gap_continua(gap: str) -> bool:
    """True si el separador entre dos tokens en caps no corta la corrida.

    Une cuando el separador no aporta contenido léxico propio: espacios,
    comas, cifras, porcentajes, signos ("EL SALARIO ESTA UN 90% POR DEBAJO
    DEL VALOR" es una sola corrida). Corta ante cualquier letra en el medio
    ("BASTA de esto YA"), ante un salto de párrafo o ante un separador
    largo, que ya no es una pausa sino otro tramo de texto.
    """
    if not gap or len(gap) > _CAPS_GAP_MAX:
        return False
    return not any(ch.isalpha() for ch in gap) and gap.count("\n") <= 1


def _spans(entidades: list[TecnoEntidad]) -> list[tuple[int, int]]:
    """Spans ocupados por entidades ya extraídas."""
    return [(e.inicio, e.fin) for e in entidades]


def _solapa(inicio: int, fin: int, ocupado: list[tuple[int, int]]) -> bool:
    """True si [inicio, fin) se solapa con algún span ocupado."""
    return any(inicio < b and fin > a for a, b in ocupado)


def _dominio(url: str) -> str:
    """Dominio de una URL (sin esquema, path ni www.)."""
    sin_esquema = re.sub(r"^https?://", "", url)
    dominio = sin_esquema.split("/", 1)[0].split("?", 1)[0].lower()
    return dominio.removeprefix("www.")


def _inicio_bloque_final(texto: str) -> int:
    """Offset donde empieza el bloque final de hashtags/URLs del post.

    Un hashtag es 'pospuesto' cuando vive en la cola del post, después del
    último contenido proposicional: se recorta desde el final todo lo que sea
    hashtags, URLs, emojis, espacios y puntuación, y lo que quede antes marca
    la frontera. Heurística conservadora: en la duda, integrada.
    """
    resto = texto
    while True:
        recortado = resto.rstrip()
        recortado = re.sub(r"(?:#\w+)\Z", "", recortado, flags=re.UNICODE)
        recortado = re.sub(f"(?:{_URL_RE.pattern})" + r"\Z", "", recortado,
                           flags=re.UNICODE | re.IGNORECASE)
        recortado = re.sub(r"[\s.,;:!?…]+\Z", "", recortado)
        if _emoji_lib is not None:
            spans = _emoji_lib.emoji_list(recortado)
            if spans and spans[-1]["match_end"] == len(recortado):
                recortado = recortado[: spans[-1]["match_start"]]
        else:
            recortado = re.sub(
                _EMOJI_FALLBACK_RE.pattern + r"\Z", "", recortado
            )
        if recortado == resto:
            return len(recortado)
        resto = recortado


def _fin_bloque_vocativo(texto: str) -> int:
    """Offset donde termina la cadena inicial de @menciones (convención reply)."""
    m = re.match(
        r"(?:@[A-Za-z0-9_](?:[A-Za-z0-9_.\-]*[A-Za-z0-9_])?[\s,]*)+", texto
    )
    return m.end() if m else 0


def _norm_puntuacion(valor: str) -> str:
    """Colapsa la puntuación expresiva a su clase."""
    if "…" in valor or valor.startswith("..."):
        return "suspensivos"
    if "!" in valor and "?" in valor:
        return "interrogacion_exclamacion"
    if "!" in valor:
        return "exclamacion_multiple"
    return "interrogacion_multiple"
