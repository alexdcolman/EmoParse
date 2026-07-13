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
#  - url: normalizada a su dominio.
#  - emoji: normalizado a shortcode. Con la librería `emoji` (extra `techno`)
#    se capturan secuencias ZWJ y modificadores; sin ella, un fallback por
#    rangos Unicode cubre los emojis simples.
#  - tecnografismo: subtipos 'mayusculas' (palabra de ≥4 letras en caps),
#    'alargamiento' (letra repetida ≥3), 'risa' (jajaja y variantes),
#    'puntuacion' (!!, ?!, ...).
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

#: URL http(s).
_URL_RE = re.compile(r"https?://\S+")

#: Puntuación final que no forma parte de una URL.
_URL_TRAIL = ".,;:!?)»\"'”’…"

#: Prefijo de retweet clásico ("RT @user: ...").
_RT_PREFIX_RE = re.compile(r"^RT\s+@([A-Za-z0-9_](?:[A-Za-z0-9_.\-]*[A-Za-z0-9_])?):?\s*")

#: Palabra íntegramente en mayúsculas, ≥4 letras (grito tipográfico).
_MAYUSCULAS_RE = re.compile(r"\b[A-ZÁÉÍÓÚÜÑ]{4,}\b")

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
    # Las URLs se enmascaran para el resto de los extractores: un '#' o un
    # patrón de repetición dentro de una URL no es un tecnolingüístico.
    ocupado = _spans(entidades)
    entidades.extend(extract_hashtags(texto, ocupado))
    entidades.extend(extract_menciones(texto, ocupado))
    emojis = extract_emojis(texto)
    entidades.extend(emojis)
    ocupado = _spans(entidades)
    entidades.extend(extract_tecnografismos(texto, ocupado))
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
    (orden: risa → alargamiento → mayúsculas → puntuación) se queda con él,
    así "JAJAJA" es risa y "GOOOOL" es alargamiento, no también mayúsculas.
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

    for m in _MAYUSCULAS_RE.finditer(texto):
        if not _libre(m.start(), m.end()):
            continue
        out.append(TecnoEntidad(
            tipo="tecnografismo", valor=m.group(0),
            valor_norm=m.group(0).lower(), inicio=m.start(), fin=m.end(),
            extra={"subtipo": "mayusculas"},
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


# ══════════════════════════════════════════════════════════════════════════════
#  Helpers
# ══════════════════════════════════════════════════════════════════════════════

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
        recortado = re.sub(r"https?://\S+\Z", "", recortado)
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
