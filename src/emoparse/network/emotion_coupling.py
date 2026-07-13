# ══════════════════════════════════════════════════════════════════════════════
#  emoparse.network.emotion_coupling
#
#  Acoplamiento entre el análisis emocional y la estructura de red.
#
#  Funciones puras sobre DataFrames:
#  - foria_by_post: foria dominante por post, desde la caracterización de
#    sus emociones (payload del characterizer).
#  - foria_transition_matrix: matriz de transición fórica padre→hijo en los
#    árboles de respuesta (contagio, escalada, inversión).
#  - community_emotion_profile: distribución de tipos de emoción y forias
#    por comunidad de autores.
# ══════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

import json
from collections import Counter
from typing import Any

import pandas as pd

#: Orden canónico de forias en las matrices.
FORIAS: tuple[str, ...] = (
    "euforico", "disforico", "aforico", "ambiforico", "indeterminado",
)

#: Etiqueta para posts sin emociones caracterizadas.
SIN_EMOCION = "sin_emocion"


def foria_by_post(df_emociones: pd.DataFrame) -> dict[str, str]:
    """Foria dominante por post (codigo) desde `caracterizacion_payload`.

    La dominante es la moda de las forias de las emociones del post; ante
    empate gana la más marcada según el orden de `FORIAS`. Posts cuyas
    emociones no tienen caracterización quedan como 'indeterminado'.
    """
    forias_por_codigo: dict[str, list[str]] = {}
    for r in df_emociones.to_dict(orient="records"):
        codigo = str(r["codigo"])
        foria = _extract_foria(r.get("caracterizacion_payload"))
        forias_por_codigo.setdefault(codigo, []).append(foria)

    out: dict[str, str] = {}
    for codigo, forias in forias_por_codigo.items():
        counts = Counter(forias)
        out[codigo] = max(
            counts,
            key=lambda f: (counts[f], -FORIAS.index(f) if f in FORIAS else -99),
        )
    return out


def foria_transition_matrix(
    df_posts: pd.DataFrame,
    foria_map: dict[str, str],
    include_sin_emocion: bool = False,
) -> pd.DataFrame:
    """Matriz de transición fórica padre→hijo sobre las aristas de reply.

    Filas: foria del post padre; columnas: foria de la respuesta; celdas:
    conteos. Con `include_sin_emocion`, los posts sin emociones entran como
    categoría propia (útil para medir des-escalada hacia lo no emocional).
    """
    labels = list(FORIAS) + ([SIN_EMOCION] if include_sin_emocion else [])
    matrix = pd.DataFrame(0, index=labels, columns=labels, dtype=int)

    posts_ids = {str(r["post_id"]) for r in df_posts.to_dict(orient="records")}
    for r in df_posts.to_dict(orient="records"):
        parent = r.get("en_respuesta_a")
        if parent is None or (isinstance(parent, float) and pd.isna(parent)):
            continue
        parent = str(parent)
        if parent not in posts_ids:
            continue
        f_padre = foria_map.get(parent, SIN_EMOCION)
        f_hijo = foria_map.get(str(r["post_id"]), SIN_EMOCION)
        if not include_sin_emocion and SIN_EMOCION in (f_padre, f_hijo):
            continue
        if f_padre in matrix.index and f_hijo in matrix.columns:
            matrix.loc[f_padre, f_hijo] += 1
    return matrix


def community_emotion_profile(
    df_posts: pd.DataFrame,
    communities: dict[str, int],
    df_emociones: pd.DataFrame,
) -> pd.DataFrame:
    """Perfil emocional por comunidad de autores.

    Una fila por (comunidad, tipo de emoción) con conteos y la distribución
    fórica. El tipo usa `tipo_emocion_canonico` si existe; si no,
    `tipo_emocion`.
    """
    autor_por_post = {
        str(r["post_id"]): str(r["autor_handle"]).lower()
        for r in df_posts.to_dict(orient="records")
    }
    rows: list[dict[str, Any]] = []
    for r in df_emociones.to_dict(orient="records"):
        autor = autor_por_post.get(str(r["codigo"]))
        if autor is None:
            continue
        comunidad = communities.get(autor)
        if comunidad is None:
            continue
        tipo = (
            _clean(r.get("tipo_emocion_canonico"))
            or _clean(r.get("tipo_emocion"))
            or "?"
        )
        rows.append({
            "comunidad": int(comunidad),
            "tipo_emocion": str(tipo),
            "foria": _extract_foria(r.get("caracterizacion_payload")),
        })
    if not rows:
        return pd.DataFrame(
            columns=["comunidad", "tipo_emocion", "n", *FORIAS]
        )
    df = pd.DataFrame(rows)
    out = []
    for (comunidad, tipo), grp in df.groupby(["comunidad", "tipo_emocion"]):
        counts = Counter(grp["foria"])
        out.append({
            "comunidad": comunidad,
            "tipo_emocion": tipo,
            "n": int(len(grp)),
            **{f: int(counts.get(f, 0)) for f in FORIAS},
        })
    return pd.DataFrame(out).sort_values(
        ["comunidad", "n"], ascending=[True, False]
    ).reset_index(drop=True)


def _clean(value: Any) -> str | None:
    """String limpio de una celda: None/NaN/'' → None (NaN es truthy en pandas)."""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    s = str(value).strip()
    return s or None


def _extract_foria(payload_raw: Any) -> str:
    """Extrae la foria del payload de caracterización (o 'indeterminado')."""
    if payload_raw is None or (
        isinstance(payload_raw, float) and pd.isna(payload_raw)
    ):
        return "indeterminado"
    payload = payload_raw
    if isinstance(payload_raw, str):
        try:
            payload = json.loads(payload_raw)
        except json.JSONDecodeError:
            return "indeterminado"
    if not isinstance(payload, dict):
        return "indeterminado"
    foria = str(payload.get("foria") or "indeterminado")
    return foria if foria in FORIAS else "indeterminado"
