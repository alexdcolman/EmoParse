# ══════════════════════════════════════════════════════════════════════════════
#  emoparse.network.simulacro_similarity
#
#  Parecido entre simulacros emocionales y agrupamiento narrativo.
#
#  Un simulacro es la emoción reconstruida con todos sus componentes: quién la
#  experimenta, de qué tipo es, qué la origina, qué la media, quién la
#  verifica, qué la modifica, con qué foria e intensidad. Dos posts cuentan
#  "la misma historia" cuando sus simulacros comparten esos componentes,
#  aunque no compartan una palabra.
#
#  El parecido es simbólico y explicable: se elige qué componentes cuentan y
#  con qué peso, y cada par queda con el detalle de en qué coincidió. No hay
#  vectores ni caja negra; el agrupamiento semántico por contenido de los
#  posts vive aparte, en `network.embeddings`.
#
#  Funciones puras sobre DataFrames. El agrupamiento reusa el Louvain de
#  `network.metrics` sobre el grafo de parecido, para no introducir un
#  clusterer distinto del que ya usan los grafos de interacción.
# ══════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

import pandas as pd


@dataclass(frozen=True, slots=True)
class Componente:
    """Un componente del simulacro y cómo se compara.

    `columnas` se prueban en orden y se usa la primera presente en el
    DataFrame, de modo que el componente funcione tanto con la resolución
    canónica como con el crudo del modelo. `multiple` marca los componentes
    que pueden portar varios valores (la fuente puede combinar entidades, los
    semas son un conjunto): esos se comparan por Jaccard, y los simples, por
    coincidencia exacta.
    """

    columnas: tuple[str, ...]
    multiple: bool = False
    peso: float = 1.0


#: Componentes disponibles para el parecido. Los identificadores son estables:
#: los consume la CLI (`--similitud-componentes`) y la tab.
COMPONENTES: dict[str, Componente] = {
    "experienciador": Componente(
        (
            "experienciador_canonicos",
            "experienciador_canonico",
            "experienciador_efectivo",
            "experienciador",
        ),
        multiple=True,
        peso=1.5,
    ),
    "tipo_emocion": Componente(
        ("tipo_emocion_canonico", "tipo_emocion"),
        peso=1.5,
    ),
    "fuente": Componente(
        ("fuente_canonicos", "fuente_canonico", "fuente_efectiva", "fuente_inferencia"),
        multiple=True,
        peso=1.5,
    ),
    "semas_experienciador": Componente(
        ("experienciador_semas",),
        multiple=True,
    ),
    "semas_fuente": Componente(("fuente_semas",), multiple=True),
    "mediador": Componente(("mediador",)),
    "verificador_normativo": Componente(("verificador_normativo",)),
    "verificador_observacional": Componente(("verificador_observacional",)),
    "operador_modificacion": Componente(("operador_modificacion",)),
    "polaridad": Componente(("polaridad",)),
    "foria": Componente(("foria",)),
    "intensidad": Componente(("intensidad",)),
    "dominancia": Componente(("dominancia",)),
    "tipo_configuracion": Componente(("tipo_configuracion",)),
}

#: Componentes usados si no se eligen otros: el núcleo actancial del
#: simulacro, sin los rasgos graduales que agrupan por intensidad más que
#: por historia.
COMPONENTES_DEFAULT: tuple[str, ...] = (
    "experienciador",
    "tipo_emocion",
    "fuente",
    "mediador",
    "verificador_normativo",
    "verificador_observacional",
    "operador_modificacion",
    "foria",
)

#: Parecido mínimo para que dos simulacros queden ligados.
UMBRAL_DEFAULT = 0.5

#: Un token presente en más de esta fracción de los simulacros no sirve para
#: preseleccionar candidatos: emparejaría con casi todo. Se usa igual para
#: puntuar, pero no para armar los bloques de comparación.
MAX_DF_BLOQUEO = 0.25

#: Tope de pares evaluados. Evita que un corpus grande con componentes poco
#: selectivos dispare una comparación cuadrática.
MAX_PARES = 5_000_000


class ComponenteDesconocidoError(ValueError):
    """Se pidió un componente que no está en `COMPONENTES`."""


# ══════════════════════════════════════════════════════════════════════════════
#  Rasgos
# ══════════════════════════════════════════════════════════════════════════════


def componentes_disponibles(df: pd.DataFrame) -> tuple[str, ...]:
    """Componentes que el DataFrame puede alimentar, en orden de declaración."""
    return tuple(nombre for nombre, comp in COMPONENTES.items() if _columna(df, comp) is not None)


def build_features(
    df: pd.DataFrame,
    componentes: Iterable[str] = COMPONENTES_DEFAULT,
) -> list[dict[str, frozenset[str]]]:
    """Rasgos de cada simulacro: componente → conjunto de valores.

    Los valores se normalizan y se prefijan con su componente, así el mismo
    slug en dos componentes distintos no se confunde al indexar. Un
    componente sin valor queda como conjunto vacío: no aporta ni resta.
    """
    nombres = _validar(componentes)
    columnas = {n: _columna(df, COMPONENTES[n]) for n in nombres}
    registros = df.to_dict(orient="records")
    out: list[dict[str, frozenset[str]]] = []
    for r in registros:
        rasgos: dict[str, frozenset[str]] = {}
        for nombre in nombres:
            col = columnas[nombre]
            valores = _valores(r.get(col)) if col else []
            rasgos[nombre] = frozenset(f"{nombre}={v}" for v in valores)
        out.append(rasgos)
    return out


# ══════════════════════════════════════════════════════════════════════════════
#  Parecido
# ══════════════════════════════════════════════════════════════════════════════


def similarity_pairs(
    features: list[dict[str, frozenset[str]]],
    pesos: dict[str, float] | None = None,
    umbral: float = UMBRAL_DEFAULT,
    max_df_bloqueo: float = MAX_DF_BLOQUEO,
    max_pares: int = MAX_PARES,
) -> pd.DataFrame:
    """Pares de simulacros con parecido por encima del umbral.

    Solo se comparan los pares que comparten al menos un valor selectivo
    (preselección por índice invertido): sin eso el costo es cuadrático y un
    corpus de decenas de miles de emociones no termina nunca. Los valores
    demasiado frecuentes no preseleccionan, pero sí puntúan.

    Devuelve columnas `i`, `j` (i < j), `similitud` y `comparten`, esta
    última con los componentes que coincidieron, para poder leer por qué dos
    simulacros quedaron juntos.
    """
    if len(features) < 2:
        return pd.DataFrame(columns=["i", "j", "similitud", "comparten"])

    pesos = _pesos(features[0].keys(), pesos)
    candidatos = _pares_candidatos(features, max_df_bloqueo, max_pares)
    filas: list[dict[str, Any]] = []
    for i, j in candidatos:
        similitud, comparten = _similitud(features[i], features[j], pesos)
        if similitud >= umbral:
            filas.append(
                {
                    "i": i,
                    "j": j,
                    "similitud": round(similitud, 4),
                    "comparten": ", ".join(comparten),
                }
            )
    if not filas:
        return pd.DataFrame(columns=["i", "j", "similitud", "comparten"])
    return pd.DataFrame(filas).sort_values("similitud", ascending=False).reset_index(drop=True)


def agrupar(
    pairs: pd.DataFrame,
    n_simulacros: int,
    seed: int = 42,
) -> dict[int, int]:
    """Grupos narrativos: Louvain sobre el grafo de parecido.

    Devuelve índice de simulacro → id de grupo, solo para los simulacros con
    al menos un par por encima del umbral. Los que quedan sueltos no forman
    grupo: no se los fuerza a uno.
    """
    if pairs.empty:
        return {}
    from emoparse.network.metrics import _nx

    nx = _nx()
    G = nx.Graph()
    for r in pairs.to_dict(orient="records"):
        G.add_edge(int(r["i"]), int(r["j"]), weight=float(r["similitud"]))
    if G.number_of_nodes() == 0:
        return {}
    comunidades = nx.community.louvain_communities(G, weight="weight", seed=seed)
    ordenadas = sorted(
        (sorted(int(n) for n in c) for c in comunidades),
        key=lambda c: (-len(c), c[0]),
    )
    return {nodo: i for i, c in enumerate(ordenadas) for nodo in c}


def perfil_grupos(
    df: pd.DataFrame,
    grupos: dict[int, int],
    componentes: Iterable[str] = COMPONENTES_DEFAULT,
    top: int = 3,
) -> pd.DataFrame:
    """Qué narra cada grupo: los valores dominantes de cada componente.

    Una fila por grupo, con su tamaño y, por componente, los valores más
    frecuentes con su conteo. Es la lectura del agrupamiento: sin esto, un
    id de grupo no dice nada.
    """
    if not grupos:
        return pd.DataFrame(columns=["grupo", "simulacros"])
    nombres = _validar(componentes)
    columnas = {n: _columna(df, COMPONENTES[n]) for n in nombres}
    registros = df.to_dict(orient="records")

    por_grupo: dict[int, list[dict[str, Any]]] = {}
    for idx, grupo in grupos.items():
        if 0 <= idx < len(registros):
            por_grupo.setdefault(int(grupo), []).append(registros[idx])

    filas: list[dict[str, Any]] = []
    for grupo, items in sorted(por_grupo.items()):
        fila: dict[str, Any] = {"grupo": grupo, "simulacros": len(items)}
        for nombre in nombres:
            col = columnas[nombre]
            counts: Counter = Counter()
            for r in items:
                counts.update(_valores(r.get(col)) if col else [])
            fila[nombre] = ", ".join(f"{v} ({n})" for v, n in counts.most_common(top))
        filas.append(fila)
    return pd.DataFrame(filas).sort_values("simulacros", ascending=False).reset_index(drop=True)


def grupos_por_autor(
    df: pd.DataFrame,
    grupos: dict[int, int],
    autor_por_post: dict[str, str],
) -> pd.DataFrame:
    """Reparto de los grupos narrativos entre las cuentas del corpus.

    Puente entre el agrupamiento de simulacros y la estructura de red: una
    fila por (autor, grupo) con cuántos simulacros de ese grupo enuncia. Es
    lo que permite preguntarse si una comunidad de interacción coincide con
    una comunidad narrativa.
    """
    if not grupos:
        return pd.DataFrame(columns=["autor", "grupo", "simulacros"])
    registros = df.to_dict(orient="records")
    counts: Counter = Counter()
    for idx, grupo in grupos.items():
        if not (0 <= idx < len(registros)):
            continue
        autor = autor_por_post.get(str(registros[idx].get("codigo", "")))
        if autor:
            counts[(str(autor).lower(), int(grupo))] += 1
    if not counts:
        return pd.DataFrame(columns=["autor", "grupo", "simulacros"])
    return (
        pd.DataFrame([{"autor": a, "grupo": g, "simulacros": n} for (a, g), n in counts.items()])
        .sort_values(["grupo", "simulacros"], ascending=[True, False])
        .reset_index(drop=True)
    )


#: Componentes secundarios del simulacro, en el orden en que se leen. Solo se
#: muestran los que la caracterización resolvió.
_ORDEN_SECUNDARIOS: tuple[tuple[str, str], ...] = (
    ("mediador", "mediador"),
    ("verificador_normativo", "verif. normativo"),
    ("verificador_observacional", "verif. observacional"),
    ("operador_modificacion", "operador"),
    ("polaridad", "polaridad"),
    ("foria", "foria"),
)


def describir_simulacro(row: dict[str, Any]) -> str:
    """Un simulacro en una lectura estable: quién siente qué, ante qué.

    Primero el núcleo (experienciador — tipo de emoción — fuentes), después
    los componentes que la caracterización haya resuelto, siempre en el mismo
    orden. Lo no calculado se omite en lugar de aparecer vacío, y el orden es
    fijo para que dos simulacros se puedan comparar de un vistazo.
    """
    exp = _primero(row, COMPONENTES["experienciador"].columnas) or "?"
    tipo = _primero(row, COMPONENTES["tipo_emocion"].columnas) or "?"
    fuentes = _valores(_celda(row, COMPONENTES["fuente"].columnas))
    nucleo = f"{exp} — {tipo}"
    if fuentes:
        nucleo += " ← " + ", ".join(fuentes)
    partes = [nucleo]
    for clave, etiqueta in _ORDEN_SECUNDARIOS:
        valor = _primero(row, COMPONENTES[clave].columnas)
        if valor:
            partes.append(f"{etiqueta}: {valor}")
    return " · ".join(partes)


def describir_simulacros(rows: list[dict[str, Any]]) -> str:
    """Varios simulacros de una misma unidad, numerados y en orden.

    Se ordenan por su posición en el discurso (frase y emoción), no por el
    orden en que vinieron: dos lecturas del mismo post tienen que listar lo
    mismo en la misma secuencia.
    """
    if not rows:
        return ""
    if len(rows) == 1:
        return describir_simulacro(rows[0])
    ordenados = sorted(
        rows,
        key=lambda r: (int(r.get("frase_idx") or 0), int(r.get("emocion_idx") or 0)),
    )
    return "<br>".join(f"{i}. {describir_simulacro(r)}" for i, r in enumerate(ordenados, 1))


def _celda(row: dict[str, Any], columnas: tuple[str, ...]) -> Any:
    """Primer valor no vacío entre las columnas alternativas de un componente."""
    for col in columnas:
        if col in row and _valores(row[col]):
            return row[col]
    return None


def _primero(row: dict[str, Any], columnas: tuple[str, ...]) -> str:
    """Valores de un componente, unidos para mostrar."""
    return ", ".join(_valores(_celda(row, columnas)))


def clave_simulacro(row: dict[str, Any]) -> str:
    """Identificador estable de un simulacro, para nombrarlo como nodo."""
    return (
        f"{row.get('codigo', '')}:"
        f"{int(row.get('frase_idx', 0) or 0)}:"
        f"{int(row.get('emocion_idx', 0) or 0)}"
    )


# ══════════════════════════════════════════════════════════════════════════════
#  Internos
# ══════════════════════════════════════════════════════════════════════════════


def _validar(componentes: Iterable[str]) -> tuple[str, ...]:
    """Normaliza y valida la selección de componentes."""
    nombres = tuple(dict.fromkeys(str(c).strip() for c in componentes if str(c).strip()))
    if not nombres:
        return COMPONENTES_DEFAULT
    desconocidos = [n for n in nombres if n not in COMPONENTES]
    if desconocidos:
        raise ComponenteDesconocidoError(
            f"Componentes desconocidos: {desconocidos}. Disponibles: {', '.join(COMPONENTES)}"
        )
    return nombres


def _columna(df: pd.DataFrame, comp: Componente) -> str | None:
    """Primera columna del componente presente en el DataFrame."""
    return next((c for c in comp.columnas if c in df.columns), None)


def _valores(celda: Any) -> list[str]:
    """Valores normalizados de una celda, sea escalar o colección.

    Las cadenas con `; ` se parten: es como la capa de datos junta los
    referentes de una fuente que combina entidades.
    """
    if celda is None or (isinstance(celda, float) and pd.isna(celda)):
        return []
    if isinstance(celda, (list, tuple, set, frozenset)):
        crudos: Iterable[Any] = celda
    else:
        crudos = str(celda).split(";")
    out: list[str] = []
    for v in crudos:
        s = str(v).strip().lower()
        if s and s not in out:
            out.append(s)
    return out


def _pesos(nombres: Iterable[str], pesos: dict[str, float] | None) -> dict[str, float]:
    """Peso efectivo de cada componente: el pedido, o el declarado."""
    pesos = pesos or {}
    return {
        n: float(pesos.get(n, COMPONENTES[n].peso if n in COMPONENTES else 1.0)) for n in nombres
    }


def _pares_candidatos(
    features: list[dict[str, frozenset[str]]],
    max_df_bloqueo: float,
    max_pares: int,
) -> list[tuple[int, int]]:
    """Pares que comparten al menos un valor selectivo (índice invertido)."""
    indice: dict[str, list[int]] = {}
    for idx, rasgos in enumerate(features):
        for valores in rasgos.values():
            for v in valores:
                indice.setdefault(v, []).append(idx)

    tope = max(int(len(features) * max_df_bloqueo), 2)
    pares: set[tuple[int, int]] = set()
    for postings in indice.values():
        if len(postings) > tope:
            continue  # valor poco selectivo: puntúa, pero no preselecciona
        for a in range(len(postings)):
            for b in range(a + 1, len(postings)):
                i, j = postings[a], postings[b]
                pares.add((i, j) if i < j else (j, i))
                if len(pares) >= max_pares:
                    return sorted(pares)
    return sorted(pares)


def _similitud(
    a: dict[str, frozenset[str]],
    b: dict[str, frozenset[str]],
    pesos: dict[str, float],
) -> tuple[float, list[str]]:
    """Parecido ponderado entre dos simulacros y qué componentes comparten.

    Cada componente aporta su Jaccard. Los componentes vacíos en ambos lados
    no entran en el promedio: la ausencia compartida no es evidencia de
    parecido, y contarla premiaría a los simulacros mal caracterizados.
    """
    acumulado = 0.0
    total_peso = 0.0
    comparten: list[str] = []
    for nombre, valores_a in a.items():
        valores_b = b.get(nombre, frozenset())
        if not valores_a and not valores_b:
            continue
        union = valores_a | valores_b
        interseccion = valores_a & valores_b
        jaccard = len(interseccion) / len(union) if union else 0.0
        peso = pesos.get(nombre, 1.0)
        acumulado += peso * jaccard
        total_peso += peso
        if interseccion:
            comparten.append(nombre)
    if not total_peso:
        return 0.0, []
    return acumulado / total_peso, comparten
