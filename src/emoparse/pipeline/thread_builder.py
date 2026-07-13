# ══════════════════════════════════════════════════════════════════════════════
#  emoparse.pipeline.thread_builder
#
#  Reconstrucción del árbol conversacional de un corpus de posts.
#
#  Funciones puras sobre DataFrames: no tocan DB ni filesystem. A partir de
#  `en_respuesta_a` (y `conversacion_id` cuando la fuente lo trae), asigna a
#  cada post su conversación, su profundidad en el árbol y su condición de
#  huérfano (reply cuyo padre no fue capturado, situación normal en corpus
#  scrapeados), y agrega la tabla de hilos.
# ══════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

import json

import pandas as pd

#: Tope de saltos al remontar padres: corta ante ciclos o cadenas anómalas.
_MAX_DEPTH = 500


def build_threads(df_posts: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Enriquece los posts con estructura conversacional y agrega los hilos.

    Devuelve `(df_posts, df_hilos)`:

    - `df_posts`: copia del input con `conversacion_id` completado,
      `profundidad` (0 = raíz; None si no es calculable) y `huerfano`
      (1 si es reply y su padre no está en el corpus).
    - `df_hilos`: una fila por conversación con `conversacion_id`,
      `post_raiz`, `n_posts`, `profundidad_max`, `participantes` (JSON),
      `fecha_inicio` y `fecha_fin`.

    Reglas de resolución:
    - La raíz de la conversación se remonta por la cadena `en_respuesta_a`
      dentro del corpus. Si la cadena sale del corpus, el post es huérfano y
      su conversación es el `conversacion_id` provisto por la fuente o, en
      su defecto, el último ancestro conocido.
    - `conversacion_id` provisto por la fuente tiene prioridad sobre el
      derivado (las plataformas lo calculan con el árbol completo).
    """
    df = df_posts.copy().reset_index(drop=True)
    by_id: dict[str, dict] = {
        str(r["post_id"]): r for r in df.to_dict(orient="records")
    }

    conv_ids: list[str] = []
    profundidades: list[int | None] = []
    huerfanos: list[int] = []

    for row in df.to_dict(orient="records"):
        conv, depth, orphan = _resolve(row, by_id)
        conv_ids.append(conv)
        profundidades.append(depth)
        huerfanos.append(orphan)

    df["conversacion_id"] = conv_ids
    df["profundidad"] = pd.array(profundidades, dtype="Int64")
    df["huerfano"] = huerfanos

    df_hilos = _aggregate_hilos(df)
    return df, df_hilos


# ══════════════════════════════════════════════════════════════════════════════
#  Resolución por post
# ══════════════════════════════════════════════════════════════════════════════

def _resolve(
    row: dict,
    by_id: dict[str, dict],
) -> tuple[str, int | None, int]:
    """Resuelve (conversacion_id, profundidad, huerfano) para un post."""
    post_id = str(row["post_id"])
    parent = _clean(row.get("en_respuesta_a"))
    provided_conv = _clean(row.get("conversacion_id"))

    if not parent:
        # Raíz (original, quote o repost): conversación propia salvo dato de fuente.
        return provided_conv or post_id, 0, 0

    # Reply: remontar la cadena de padres dentro del corpus.
    depth = 0
    current = post_id
    seen: set[str] = {current}
    while True:
        current_parent = _clean(by_id[current].get("en_respuesta_a")) if current in by_id else None
        if not current_parent:
            # `current` es la raíz capturada.
            return provided_conv or current, depth, 0
        depth += 1
        if current_parent not in by_id:
            # La cadena sale del corpus: huérfano. La profundidad real es
            # desconocida (falta el tramo superior del árbol).
            return provided_conv or current_parent, None, 1
        if current_parent in seen or depth > _MAX_DEPTH:
            # Ciclo o cadena anómala: cortar sin romper la carga.
            return provided_conv or current_parent, None, 1
        seen.add(current_parent)
        current = current_parent


def _clean(value: object) -> str | None:
    """Normaliza referencias: None/NaN/'' → None."""
    if value is None:
        return None
    if isinstance(value, float) and pd.isna(value):
        return None
    s = str(value).strip()
    return s or None


# ══════════════════════════════════════════════════════════════════════════════
#  Agregación de hilos
# ══════════════════════════════════════════════════════════════════════════════

def _aggregate_hilos(df: pd.DataFrame) -> pd.DataFrame:
    """Agrega una fila por conversación."""
    rows = []
    for conv_id, grp in df.groupby("conversacion_id", sort=True):
        fechas = sorted(f for f in grp["fecha"].tolist() if f)
        profundidades = [int(p) for p in grp["profundidad"].dropna().tolist()]
        participantes = sorted(set(grp["autor_handle"].astype(str).tolist()))
        # La raíz es el post cuyo id coincide con la conversación; si no fue
        # capturada, el id de conversación sigue apuntándola.
        rows.append({
            "conversacion_id": str(conv_id),
            "post_raiz": str(conv_id),
            "n_posts": int(len(grp)),
            "profundidad_max": max(profundidades) if profundidades else 0,
            "participantes": json.dumps(participantes, ensure_ascii=False),
            "fecha_inicio": fechas[0] if fechas else None,
            "fecha_fin": fechas[-1] if fechas else None,
        })
    return pd.DataFrame(rows)
