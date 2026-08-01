# ══════════════════════════════════════════════════════════════════════════════
#  emoparse.viz.foria
#
#  Paleta fórica canónica y derivación del color de una emoción.
#
#  Fuente única de los colores del sistema: la foria es la propiedad que
#  organiza la lectura visual de todo el dashboard, de modo que el color de
#  una emoción no es arbitrario sino un tono de su foria dominante. Lo
#  consumen `viz.charts`, `viz.network_charts` y `app.styles` (que exporta
#  la paleta como variables CSS), para que gráficos y marcado compartan
#  literalmente los mismos valores.
#
#  Los valores de foria llegan sin tildes desde el schema (`euforico`,
#  `disforico`, ...), pero el texto de la UI y los payloads antiguos pueden
#  traerlos acentuados: toda entrada pasa por `normalizar`.
# ══════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

import colorsys
import unicodedata
from zlib import crc32

import pandas as pd

#: Colores por foria. Claves normalizadas; `None` cubre el dato ausente
#: (una emoción sin caracterizar no es lo mismo que una indeterminada).
FORIA_COLORS: dict[str | None, str] = {
    "euforico":      "#2c6e63",
    "disforico":     "#a6412c",
    "ambiforico":    "#9a7a2e",
    "aforico":       "#7c7f79",
    "indeterminado": "#4a4d52",
    None:            "#33363b",
}

#: Etiquetas visibles de cada foria (femenino: concuerdan con "foria").
FORIA_LABELS: dict[str, str] = {
    "euforico":      "eufórica",
    "disforico":     "disfórica",
    "ambiforico":    "ambifórica",
    "aforico":       "afórica",
    "indeterminado": "indeterminada",
}

#: Marcas tipográficas de foria para chips y listados compactos.
FORIA_ICONS: dict[str, str] = {
    "euforico":      "↑",
    "disforico":     "↓",
    "ambiforico":    "↕",
    "aforico":       "–",
    "indeterminado": "?",
}

#: Orden de lectura de las forias (positiva → mezcla → neutra → negativa).
#: No es un continuo: agrupa por una propiedad ya analizada de cada emoción.
FORIA_ORDEN: tuple[str, ...] = (
    "euforico", "ambiforico", "aforico", "disforico", "indeterminado",
)

#: Cantidad de tonos por foria y amplitud del salto de luminosidad entre
#: ellos. El tono varía; el matiz no: dos emociones disfóricas se distinguen
#: entre sí sin dejar de leerse como disfóricas. La escala se desplaza hacia
#: el lado claro (`_TONO_BASE`) porque el fondo del dashboard es oscuro y los
#: tonos por debajo del color base se empastan contra él.
_N_TONOS = 7
_TONO_BASE = 2
_PASO_LUZ = 0.062


def normalizar(valor: object) -> str | None:
    """Devuelve la clave canónica de foria, o None si no hay dato.

    Tolera tildes y mayúsculas: `"Disfórico"` y `"disforico"` resuelven a la
    misma clave. Un valor desconocido se trata como ausente.
    """
    if valor is None or (isinstance(valor, float) and pd.isna(valor)):
        return None
    txt = unicodedata.normalize("NFKD", str(valor)).strip().lower()
    txt = "".join(c for c in txt if not unicodedata.combining(c))
    if not txt or txt in ("nan", "none", "—"):
        return None
    return txt if txt in FORIA_LABELS else None


def color(valor: object) -> str:
    """Color plano de una foria (sin modular por emoción)."""
    return FORIA_COLORS[normalizar(valor)]


def etiqueta(valor: object) -> str:
    """Etiqueta visible de una foria ('sin caracterizar' si no hay dato)."""
    clave = normalizar(valor)
    return FORIA_LABELS[clave] if clave else "sin caracterizar"


def icono(valor: object) -> str:
    """Marca tipográfica de una foria ('·' si no hay dato)."""
    clave = normalizar(valor)
    return FORIA_ICONS[clave] if clave else "·"


def color_emocion(emocion: object, foria: object = None) -> str:
    """Color de una emoción: un tono estable de su foria.

    El tono se deriva del nombre de la emoción con un hash determinista, de
    modo que la misma emoción conserva su color entre runs y entre tabs.
    """
    base = color(foria)
    nombre = str(emocion or "").strip().lower()
    if not nombre:
        return base
    idx = crc32(nombre.encode("utf-8")) % _N_TONOS
    return _modular(base, (idx - _TONO_BASE) * _PASO_LUZ)


def mapa_colores(
    df: pd.DataFrame,
    emo_col: str = "tipo_emocion",
    foria_col: str = "foria",
) -> dict[str, str]:
    """Mapa emoción → color a partir de la foria dominante observada.

    La foria se decide por la moda de las filas de esa emoción en el propio
    DataFrame: una emoción que en este corpus se caracterizó mayormente como
    disfórica se pinta disfórica, aunque la ontología la admita ambivalente.
    """
    if df.empty or emo_col not in df.columns:
        return {}
    emociones = [e for e in df[emo_col].dropna().unique() if str(e).strip()]
    if foria_col not in df.columns:
        return {str(e): color_emocion(e, None) for e in emociones}
    out: dict[str, str] = {}
    for e in emociones:
        serie = df.loc[df[emo_col] == e, foria_col].map(normalizar).dropna()
        dominante = serie.mode().iloc[0] if not serie.empty else None
        out[str(e)] = color_emocion(e, dominante)
    return out


def foria_dominante(
    df: pd.DataFrame,
    emo_col: str = "tipo_emocion",
    foria_col: str = "foria",
) -> dict[str, str | None]:
    """Mapa emoción → foria dominante observada (None si no hay dato)."""
    if df.empty or emo_col not in df.columns or foria_col not in df.columns:
        return {}
    out: dict[str, str | None] = {}
    for e in df[emo_col].dropna().unique():
        serie = df.loc[df[emo_col] == e, foria_col].map(normalizar).dropna()
        out[str(e)] = serie.mode().iloc[0] if not serie.empty else None
    return out


def orden_emociones(
    df: pd.DataFrame,
    emo_col: str = "tipo_emocion",
    foria_col: str = "foria",
) -> list[str]:
    """Emociones presentes ordenadas por foria dominante y luego alfabético."""
    if df.empty or emo_col not in df.columns:
        return []
    emos = [str(e) for e in df[emo_col].dropna().unique() if str(e).strip()]
    dom = foria_dominante(df, emo_col=emo_col, foria_col=foria_col)
    rank = {f: i for i, f in enumerate(FORIA_ORDEN)}
    return sorted(
        emos,
        key=lambda e: (rank.get(dom.get(e) or "", len(FORIA_ORDEN)), _fold(e)),
    )


def texto_sobre(color_fondo: str) -> str:
    """Color de texto legible sobre un fondo del color dado."""
    try:
        r, g, b = _rgb(color_fondo)
    except (ValueError, IndexError):
        return "#ffffff"
    luminancia = 0.299 * r + 0.587 * g + 0.114 * b
    return "#0e0f13" if luminancia > 150 else "#ffffff"


def rgba(color_hex: str, alpha: float) -> str:
    """Traduce un color hex a `rgba(...)` con la opacidad dada."""
    r, g, b = _rgb(color_hex)
    return f"rgba({r},{g},{b},{alpha})"


# ══════════════════════════════════════════════════════════════════════════════
#  Helpers internos
# ══════════════════════════════════════════════════════════════════════════════

def _rgb(color_hex: str) -> tuple[int, int, int]:
    """Componentes enteros de un color `#rrggbb`."""
    c = str(color_hex).lstrip("#")
    return int(c[0:2], 16), int(c[2:4], 16), int(c[4:6], 16)


def _modular(color_hex: str, delta_luz: float) -> str:
    """Aclara u oscurece un color conservando su matiz.

    La saturación acompaña al salto para que los tonos claros no se laven:
    sin eso, dos emociones de la misma foria terminan indistinguibles sobre
    fondo oscuro.
    """
    r, g, b = (v / 255 for v in _rgb(color_hex))
    h, luz, sat = colorsys.rgb_to_hls(r, g, b)
    luz = min(max(luz + delta_luz, 0.18), 0.76)
    sat = min(max(sat * (1 + delta_luz * 0.6), 0.06), 1.0)
    r2, g2, b2 = colorsys.hls_to_rgb(h, luz, sat)
    return "#%02x%02x%02x" % (
        round(r2 * 255), round(g2 * 255), round(b2 * 255)
    )


def _fold(s: object) -> str:
    """Minúsculas sin acentos, para ordenar de forma estable."""
    txt = unicodedata.normalize("NFKD", str(s or ""))
    return "".join(c for c in txt if not unicodedata.combining(c)).lower()
