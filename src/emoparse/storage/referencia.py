# ══════════════════════════════════════════════════════════════════════════════
#  emoparse.storage.referencia
#
#  Identidad referencial: cuándo un texto nombra una entidad, cuántas nombra y
#  cuál es el referente canónico de cada rol de una emoción.
#
#  Es la única fuente de verdad de esa resolución: la comparten las stages, el
#  dashboard y el export, de modo que ninguna vista pueda mostrar dos
#  referentes donde el modelo de datos define uno.
# ══════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

import re
from typing import Any, Protocol

from emoparse.core.text import canonical_slug, sanitize_referent_label

#: Marcas de una unidad con sus canónicos: {marca normalizada: {canónico: prelación}}.
MarcaMap = dict[str, dict[str, tuple[int, int, int]]]

#: Índice de marcas de una función: (codigo, unit_idx) → MarcaMap.
MarcaIndex = dict[tuple[str, int], MarcaMap]

#: Valores que cuentan como "sin referente" y no generan canónico.
_DESCONOCIDO = frozenset(
    {
        "",
        "no identificado",
        "no_identificado",
        "no identificada",
        "no se identifica",
        "no_se_identifica",
        "ninguno",
        "ninguna",
        "?",
        "desconocido",
        "desconocida",
    }
)

#: Prefijos de slug que delatan un deíctico o una etiqueta de rol enunciativo
#: devueltos como si fueran un referente ("enunciador", "los enunciatarios",
#: "nosotros_enunciador_nacion_pueblo"). Nombran una posición, no designan a
#: nadie: el referente concreto lo resuelve `pipeline.deixis` o la revisión.
_PREFIJOS_ROL: tuple[str, ...] = (
    "nosotros",
    "nosotras",
    "nuestro",
    "nuestra",
    "enunciador",
    "enunciadora",
    "enunciante",
    "enunciatario",
    "enunciataria",
    "enunciatarios",
    "enunciatarias",
    "auditorio",
    "destinatario",
    "destinatarios",
)

#: Grupo de un vínculo según su procedencia. Los deícticos son sugerencias
#: (ver `schema.CREATE_MENCION_CANONICO`): inscriben la marca en un referente
#: del dispositivo enunciativo, pero no gobiernan un simulacro mientras haya
#: un referente inferido en el discurso, ni siquiera aceptados. Que rijan una
#: emoción concreta es una decisión por emoción, no un efecto de aceptarlos.
_GRUPO_DEICTICO = 1
_ORIGIN_GRUPO = {"deixis_llm": _GRUPO_DEICTICO, "deixis": _GRUPO_DEICTICO}

#: Grupo de un vínculo rechazado. No resuelve nada, pero se conserva en el
#: índice: un referente descartado para una marca tampoco puede volver por la
#: puerta de atrás del canónico derivado de la inferencia.
_GRUPO_RECHAZADO = 2

#: Prelación por estado del vínculo: lo revisado manda sobre lo propuesto.
_STATUS_RANK = {"accepted": 0, "proposed": 1}

#: Prelación por procedencia, dentro de un mismo grupo y estado.
_ORIGIN_RANK = {
    "human": 0,
    "technoparse": 1,
    "llm": 2,
    "coref": 3,
    "auto": 4,
    "deixis_llm": 5,
    "deixis": 6,
}

#: Prelación de un vínculo con estado u origen no reconocidos.
_SIN_PRELACION = (9, 9, 9)

#: Tablas que componen la base de marcas discursivas.
_TABLAS_MARCAS = ("menciones", "mencion_funcion", "mencion_canonico")


class Executor(Protocol):
    """Acceso a la DB con `execute`: `storage.db.Database` o `sqlite3.Connection`."""

    def execute(self, sql: str, params: Any = ...) -> Any: ...


# ── Identidad referencial ────────────────────────────────────────────────────


def es_referente_desconocido(value: str | None) -> bool:
    """True si la marca o la inferencia no aporta referente."""
    return str(value or "").strip().lower() in _DESCONOCIDO


def es_canonico_invalido(slug: str) -> bool:
    """True si el slug no puede ser un canónico automático.

    Dos clases: deícticos y etiquetas de rol sin resolver (construcciones
    sobre "nosotros", "enunciador" o "enunciatario": el referente concreto lo
    resuelve `deixis` o la revisión, no un canónico nuevo) y entidades
    compuestas que fusionan referentes ("javier_milei_y_asistentes": son dos
    experienciadores, no uno). La marca se conserva; solo se bloquea la
    propuesta automática de canónico.
    """
    if not slug:
        return False
    if slug in ("yo", "vos", "ustedes", "vosotros"):
        return True
    if any(slug == p or slug.startswith(p + "_") for p in _PREFIJOS_ROL):
        return True
    return "_y_" in slug or "_e_" in slug


# ── Coordinación: cuántas entidades nombra un texto ──────────────────────────

#: Separadores de coordinación: comas y conjunciones (y/e/o/u) como palabra.
_CONJ_RE = re.compile(r"\s*(?:,|\by\b|\be\b|\bo\b|\bu\b)\s*", re.IGNORECASE)

#: Detecta si hay al menos una conjunción coordinante (señal de enumeración).
_HAS_CONJ_RE = re.compile(r"\b(?:y|e|o|u)\b", re.IGNORECASE)

#: Segmentos triviales (solo artículo/determinante) que no son entidad.
_ARTICULOS = frozenset(
    {
        "el",
        "la",
        "los",
        "las",
        "un",
        "una",
        "unos",
        "unas",
        "lo",
        "su",
        "sus",
    }
)

#: Preposiciones que introducen un complemento capaz de llevarse toda una
#: enumeración: "encuentro entre Sánchez, Mamdani, Trump y Milei" nombra un
#: referente (el encuentro), no cuatro. Si el primer segmento trae una, la
#: coordinación no es del nivel superior y el texto no se parte.
_PREP_REGENTE_RE = re.compile(r"\b(?:entre|con|contra|junto a|frente a)\s+\S", re.IGNORECASE)


def split_coordinacion(text: str | None) -> list[str]:
    """Parte una marca o una inferencia coordinada en sus entidades singulares.

    Conservador: solo parte si hay una conjunción coordinante (y/e/o/u), así no
    corta comas apositivas ("Milei, el presidente"), y no parte cuando la
    enumeración está regida por una preposición del primer segmento. Descarta
    segmentos triviales (solo artículo) y deduplica. Si no hay enumeración
    clara, devuelve el texto entero.

    Ej.: "los socialistas y el estatismo" → ["los socialistas", "el estatismo"].
    Ej.: "la academia, los organismos internacionales, la política y la teoría
    económica" → los 4 sintagmas. Ej.: "paz y prosperidad" → ["paz",
    "prosperidad"]. Ej.: "encuentro entre Sánchez, Trump y Milei" → sin partir.
    """
    t = str(text or "").strip()
    if not t or not _HAS_CONJ_RE.search(t):
        return [t] if t else []
    parts = [p.strip() for p in _CONJ_RE.split(t) if p and p.strip()]
    parts = [p for p in parts if len(p) >= 3 and p.lower() not in _ARTICULOS]
    if parts and _PREP_REGENTE_RE.search(parts[0]):
        return [t]
    seen: set[str] = set()
    out: list[str] = []
    for p in parts:
        k = p.lower()
        if k not in seen:
            seen.add(k)
            out.append(p)
    return out if len(out) >= 2 else [t]


# ── Índice de marcas ─────────────────────────────────────────────────────────


def hay_base_de_marcas(db: Executor) -> bool:
    """True si el run ya materializó la base de marcas discursivas."""
    faltan = set(_TABLAS_MARCAS)
    marcadores = ", ".join(f"'{t}'" for t in _TABLAS_MARCAS)
    for row in db.execute(
        f"SELECT name FROM sqlite_master WHERE type='table' AND name IN ({marcadores})"
    ):
        faltan.discard(row["name"])
    return not faltan


def marca_canonicos_index(
    db: Executor,
    funcion: str,
    codigo: str | None = None,
) -> MarcaIndex:
    """Índice de los vínculos marca↔referente de una función actancial.

    `funcion` es 'experienciador', 'fuente' o 'actor'. Cada canónico queda con
    su prelación (grupo, estado, procedencia), que es la que decide cuál de
    varios vínculos de una misma marca resuelve la emoción. Los rechazados
    entran con su propio grupo: no resuelven, pero constan como descartados.
    """
    if not hay_base_de_marcas(db):
        return {}
    sql = (
        "SELECT m.codigo AS codigo, m.unit_idx AS unit_idx, m.marca AS marca, "
        "mc.canonical_id AS cid, mc.status AS status, mc.origin AS origin "
        "FROM menciones m "
        "JOIN mencion_funcion mf ON mf.mencion_id = m.id AND mf.funcion = ? "
        "JOIN mencion_canonico mc ON mc.mencion_id = m.id"
    )
    params: list[Any] = [funcion]
    if codigo:
        sql += " WHERE m.codigo = ?"
        params.append(codigo)

    index: MarcaIndex = {}
    for row in db.execute(sql, tuple(params)):
        cid = row["cid"]
        marca = str(row["marca"] or "").strip().lower()
        if not cid or not marca:
            continue
        prelacion = (
            _GRUPO_RECHAZADO
            if row["status"] == "rejected"
            else _ORIGIN_GRUPO.get(row["origin"], 0),
            _STATUS_RANK.get(row["status"], _SIN_PRELACION[1]),
            _ORIGIN_RANK.get(row["origin"], _SIN_PRELACION[2]),
        )
        entrada = index.setdefault((row["codigo"], int(row["unit_idx"])), {}).setdefault(marca, {})
        if prelacion < entrada.get(cid, _SIN_PRELACION):
            entrada[cid] = prelacion
    return index


# ── Resolución ───────────────────────────────────────────────────────────────


def _candidatos_de_marca(
    marca_map: MarcaMap | None, marca: str | None
) -> list[tuple[str, tuple[int, ...]]]:
    """Canónicos que matchean una marca, con su clave de orden, ya ordenados.

    Match exacto; si no lo hay, por contención en ambos sentidos, que mapea
    una marca compuesta a sus sub-referentes ("libertarios, radicales y
    macristas"). La clave ordena por prelación del vínculo y, dentro de ella,
    por posición en la marca, para que una enumeración se lea en el orden del
    texto; ante contención en la misma posición manda la marca más específica.
    """
    objetivo = str(marca or "").strip().lower()
    if not marca_map or not objetivo:
        return []
    if objetivo in marca_map:
        candidatos = [(objetivo, marca_map[objetivo])]
    else:
        candidatos = [
            (texto, cids)
            for texto, cids in marca_map.items()
            if texto in objetivo or objetivo in texto
        ]
    mejor: dict[str, tuple[int, ...]] = {}
    for texto, cids in candidatos:
        posicion = max(objetivo.find(texto), 0)
        for cid, prelacion in cids.items():
            clave = (*prelacion, posicion, -len(texto))
            if clave < mejor.get(cid, (*_SIN_PRELACION, len(objetivo), 0)):
                mejor[cid] = clave
    return sorted(mejor.items(), key=lambda kv: (kv[1], kv[0]))


def canonicos_de_marca(marca_map: MarcaMap | None, marca: str | None) -> list[str]:
    """Canónicos que resuelven una marca, en orden de aparición en ella.

    Devuelve un solo grupo de procedencia: las sugerencias deícticas quedan
    afuera mientras haya un referente inferido en el discurso, y solo resuelven
    la marca cuando son lo único que hay. Los rechazados nunca resuelven.

    Y solo resuelven si son una: varias sugerencias deícticas compitiendo por
    una marca sin referente inferido son una ambigüedad, no un referente. Si
    resolviera por orden, aceptar una cambiaría el experienciador de todos los
    simulacros de la unidad de golpe. Sin resolución, cada simulacro espera su
    atribución por emoción.
    """
    candidatos = [
        (cid, clave)
        for cid, clave in _candidatos_de_marca(marca_map, marca)
        if clave[0] != _GRUPO_RECHAZADO
    ]
    if not candidatos:
        return []
    grupo = min(clave[0] for _, clave in candidatos)
    elegidos = [cid for cid, clave in candidatos if clave[0] == grupo]
    if grupo == _GRUPO_DEICTICO and len(elegidos) > 1:
        return []
    return elegidos


def rechazados_de_marca(marca_map: MarcaMap | None, marca: str | None) -> set[str]:
    """Canónicos descartados para una marca."""
    return {
        cid for cid, clave in _candidatos_de_marca(marca_map, marca) if clave[0] == _GRUPO_RECHAZADO
    }


def canonicos_de_override(value: Any) -> list[str]:
    """Canónicos de una atribución por emoción (str, lista o "a; b")."""
    if value is None:
        return []
    items = value if isinstance(value, (list, tuple)) else str(value).split(";")
    out: list[str] = []
    for item in items:
        texto = str(item).strip()
        if texto and texto not in out:
            out.append(texto)
    return out


def primer_canonico(value: Any) -> str:
    """Primer canónico de una atribución por emoción, o "" si no hay."""
    fijados = canonicos_de_override(value)
    return fijados[0] if fijados else ""


def canonicos_de_inferencia(inferencia: str | None) -> list[str]:
    """Canónicos derivados de la inferencia del modelo, sin pasar por la marca.

    Último recurso de la resolución: una marca sin vínculo no debería obligar
    a las vistas a caer a la forma cruda del modelo. Si la inferencia enumera
    entidades, devuelve una por entidad. Son los mismos slugs que propone la
    base de marcas, así que no introduce referentes nuevos.
    """
    texto = sanitize_referent_label(inferencia)
    if es_referente_desconocido(texto):
        return []
    out: list[str] = []
    for parte in split_coordinacion(texto):
        slug = canonical_slug(parte)
        if slug and not es_canonico_invalido(slug) and slug not in out:
            out.append(slug)
    return out


def resolver_canonicos(
    marca_map: MarcaMap | None,
    marca: str | None,
    *,
    override: Any = None,
    inferencia: str | None = None,
) -> list[str]:
    """Los referentes canónicos de un rol de la emoción, en orden.

    Prelación:
      1. `override`: la atribución por emoción (columna canónica, fijada por la
         revisión o por el desdoblamiento del explode).
      2. Los vínculos marca↔referente de mayor prelación: aceptado antes que
         propuesto, y la inferencia del discurso antes que una sugerencia
         deíctica sin aceptar.
      3. `inferencia`: los slugs de lo que infirió el modelo, para las marcas
         que todavía no tienen vínculo.

    Es la resolución de la FUENTE, que puede combinar entidades: "libertarios,
    radicales y macristas" desencadena una sola emoción con tres referentes.
    El experienciador usa `resolver_canonico`: uno solo por emoción.
    """
    fijados = canonicos_de_override(override)
    if fijados:
        return fijados
    ligados = canonicos_de_marca(marca_map, marca)
    if ligados:
        return ligados
    if inferencia is None:
        return []
    # El piso no puede resucitar lo descartado: un referente rechazado para
    # esta marca queda fuera aunque el slug de la inferencia lo reproduzca.
    rechazados = rechazados_de_marca(marca_map, marca)
    return [c for c in canonicos_de_inferencia(inferencia) if c not in rechazados]


def resolver_canonico(
    marca_map: MarcaMap | None,
    marca: str | None,
    *,
    override: Any = None,
    inferencia: str | None = None,
) -> str:
    """El referente canónico de un rol de la emoción: uno, o "" si no hay.

    Misma prelación que `resolver_canonicos`, quedándose con el primero. Es la
    resolución del EXPERIENCIADOR: una emoción nunca tiene dos. Cuando una
    marca queda ligada a varios referentes aceptados, la emoción se desdobla
    (una por referente) en la capa de datos antes de llegar acá.
    """
    resueltos = resolver_canonicos(marca_map, marca, override=override, inferencia=inferencia)
    return resueltos[0] if resueltos else ""
