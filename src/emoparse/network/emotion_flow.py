# ══════════════════════════════════════════════════════════════════════════════
#  emoparse.network.emotion_flow
#
#  Circulación de emociones por la red de interacción.
#
#  `emotion_coupling` responde qué siente cada comunidad; este módulo responde
#  cómo circula lo que sienten: si la foria se contagia o se invierte al
#  responder, si eso ocurre puertas adentro de una comunidad o en el cruce
#  entre comunidades, y qué tipos de emoción se propagan más que lo que su
#  frecuencia haría esperar.
#
#  Funciones puras sobre DataFrames, sin DB ni networkx.
# ══════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

from collections import Counter
from typing import Any

import pandas as pd

from emoparse.network.emotion_coupling import FORIAS, SIN_EMOCION, _clean

#: Alcance de una arista según las comunidades de sus extremos.
ALCANCES: tuple[str, ...] = ("intra", "inter")

#: Mínimo de pares padre-hijo con un tipo de emoción para reportar su contagio.
#: Por debajo, el cociente es ruido: un solo par daría un lift enorme.
MIN_SOPORTE_CONTAGIO = 5


def tipos_por_post(df_emociones: pd.DataFrame) -> dict[str, set[str]]:
    """Tipos de emoción presentes en cada post (codigo).

    Usa `tipo_emocion_canonico` si está resuelto; si no, el crudo. Un post
    puede portar varios tipos: el contagio se mide por tipo, no por post.
    """
    out: dict[str, set[str]] = {}
    for r in df_emociones.to_dict(orient="records"):
        tipo = _clean(r.get("tipo_emocion_canonico")) or _clean(r.get("tipo_emocion"))
        if tipo:
            out.setdefault(str(r["codigo"]), set()).add(tipo)
    return out


# ══════════════════════════════════════════════════════════════════════════════
#  Contagio por tipo de emoción
# ══════════════════════════════════════════════════════════════════════════════


def contagion_lift(
    df_posts: pd.DataFrame,
    tipos: dict[str, set[str]],
    min_soporte: int = MIN_SOPORTE_CONTAGIO,
) -> pd.DataFrame:
    """Cuánto más probable es un tipo de emoción en la respuesta si ya estaba.

    Sobre los pares padre→hijo de las respuestas capturadas, compara la
    probabilidad de que la respuesta porte el tipo dado que el padre lo
    portaba, contra su frecuencia de base en las respuestas. El cociente
    (`lift`) mide propagación: por encima de 1 el tipo se replica más de lo
    que su frecuencia haría esperar; por debajo, la respuesta lo evita.

    Es una medida de asociación sobre el corpus capturado, no una prueba de
    causalidad: dos cuentas de la misma comunidad pueden coincidir en la
    emoción sin que una la contagie a la otra.
    """
    pares = _pares_respuesta(df_posts)
    if not pares:
        return pd.DataFrame(
            columns=[
                "tipo_emocion",
                "pares",
                "pares_con_padre",
                "replicas",
                "p_condicional",
                "p_base",
                "lift",
            ]
        )

    total = len(pares)
    filas: list[dict[str, Any]] = []
    universo = sorted({t for tt in tipos.values() for t in tt})
    for tipo in universo:
        con_padre = [(p, h) for p, h in pares if tipo in tipos.get(p, ())]
        if len(con_padre) < min_soporte:
            continue
        replicas = sum(1 for _, h in con_padre if tipo in tipos.get(h, ()))
        base = sum(1 for _, h in pares if tipo in tipos.get(h, ()))
        p_cond = replicas / len(con_padre)
        p_base = base / total
        filas.append(
            {
                "tipo_emocion": tipo,
                "pares": total,
                "pares_con_padre": len(con_padre),
                "replicas": replicas,
                "p_condicional": round(p_cond, 4),
                "p_base": round(p_base, 4),
                "lift": round(p_cond / p_base, 3) if p_base else None,
            }
        )
    if not filas:
        return pd.DataFrame(
            columns=[
                "tipo_emocion",
                "pares",
                "pares_con_padre",
                "replicas",
                "p_condicional",
                "p_base",
                "lift",
            ]
        )
    return (
        pd.DataFrame(filas)
        .sort_values("lift", ascending=False, na_position="last")
        .reset_index(drop=True)
    )


# ══════════════════════════════════════════════════════════════════════════════
#  Transición fórica por alcance
# ══════════════════════════════════════════════════════════════════════════════


def foria_transition_by_scope(
    df_posts: pd.DataFrame,
    foria_map: dict[str, str],
    comunidades: dict[str, int],
) -> dict[str, pd.DataFrame]:
    """Matriz de transición fórica partida en intra e inter comunidad.

    La matriz global mezcla dos fenómenos distintos: la escalada dentro de la
    propia comunidad y la que ocurre al responderle a otra. Devuelve una
    matriz por alcance, con las mismas filas y columnas que la global.

    `comunidades` mapea handle (sin distinguir mayúsculas) a id de comunidad;
    las aristas con algún extremo sin comunidad no entran en ninguna matriz.
    """
    comunidades = {str(k).lower(): v for k, v in comunidades.items()}
    autor = _autor_por_post(df_posts)
    labels = list(FORIAS)
    out = {
        alcance: pd.DataFrame(0, index=labels, columns=labels, dtype=int) for alcance in ALCANCES
    }
    for padre, hijo in _pares_respuesta(df_posts):
        alcance = _alcance(padre, hijo, autor, comunidades)
        if alcance is None:
            continue
        f_padre = foria_map.get(padre, SIN_EMOCION)
        f_hijo = foria_map.get(hijo, SIN_EMOCION)
        if SIN_EMOCION in (f_padre, f_hijo):
            continue
        if f_padre in labels and f_hijo in labels:
            out[alcance].loc[f_padre, f_hijo] += 1
    return out


def flujo_entre_comunidades(
    df_posts: pd.DataFrame,
    foria_map: dict[str, str],
    comunidades: dict[str, int],
) -> pd.DataFrame:
    """Aristas comunidad→comunidad con la composición fórica de la respuesta.

    Una fila por par de comunidades que se responden, con el volumen de
    respuestas y cómo se reparten fóricamente. Es el mapa de por dónde
    circula la emoción: qué comunidad le contesta a cuál, y en qué tono.
    """
    comunidades = {str(k).lower(): v for k, v in comunidades.items()}
    autor = _autor_por_post(df_posts)
    acumulado: dict[tuple[int, int], Counter] = {}
    for padre, hijo in _pares_respuesta(df_posts):
        c_padre = comunidades.get(autor.get(padre, ""))
        c_hijo = comunidades.get(autor.get(hijo, ""))
        if c_padre is None or c_hijo is None:
            continue
        foria = foria_map.get(hijo, SIN_EMOCION)
        if foria == SIN_EMOCION:
            continue
        acumulado.setdefault((c_padre, c_hijo), Counter())[foria] += 1

    if not acumulado:
        return pd.DataFrame(
            columns=["comunidad_origen", "comunidad_destino", "alcance", "respuestas", *FORIAS]
        )
    filas = [
        {
            # `origen` es la comunidad interpelada y `destino` la que responde:
            # la arista sigue el sentido de la respuesta, como en `aristas`.
            "comunidad_origen": int(c_padre),
            "comunidad_destino": int(c_hijo),
            "alcance": "intra" if c_padre == c_hijo else "inter",
            "respuestas": int(sum(counts.values())),
            **{f: int(counts.get(f, 0)) for f in FORIAS},
        }
        for (c_padre, c_hijo), counts in acumulado.items()
    ]
    return pd.DataFrame(filas).sort_values("respuestas", ascending=False).reset_index(drop=True)


# ══════════════════════════════════════════════════════════════════════════════
#  Helpers
# ══════════════════════════════════════════════════════════════════════════════


def _pares_respuesta(df_posts: pd.DataFrame) -> list[tuple[str, str]]:
    """Pares (post padre, respuesta) con ambos extremos en el corpus."""
    registros = df_posts.to_dict(orient="records")
    ids = {str(r["post_id"]) for r in registros}
    pares: list[tuple[str, str]] = []
    for r in registros:
        padre = r.get("en_respuesta_a")
        if padre is None or (isinstance(padre, float) and pd.isna(padre)):
            continue
        padre = str(padre)
        if padre in ids:
            pares.append((padre, str(r["post_id"])))
    return pares


def _autor_por_post(df_posts: pd.DataFrame) -> dict[str, str]:
    """Handle del autor de cada post, sin distinguir mayúsculas."""
    return {
        str(r["post_id"]): str(r["autor_handle"]).lower()
        for r in df_posts.to_dict(orient="records")
    }


def _alcance(
    padre: str,
    hijo: str,
    autor: dict[str, str],
    comunidades: dict[str, int],
) -> str | None:
    """'intra', 'inter' o None si algún extremo no tiene comunidad."""
    c_padre = comunidades.get(autor.get(padre, ""))
    c_hijo = comunidades.get(autor.get(hijo, ""))
    if c_padre is None or c_hijo is None:
        return None
    return "intra" if c_padre == c_hijo else "inter"
