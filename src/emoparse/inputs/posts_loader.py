# ══════════════════════════════════════════════════════════════════════════════
#  emoparse.inputs.posts_loader
#
#  Carga corpus de posts (tuits y afines) desde JSONL normalizado o CSV plano.
#
#  El formato JSONL normalizado tiene un post por línea:
#
#      {"id": "...", "plataforma": "bluesky", "autor_handle": "ana.bsky.social",
#       "autor_display": "Ana", "texto": "...", "fecha": "2026-05-01T12:00:00Z",
#       "lang": "es", "tipo": "reply", "conversacion_id": "...",
#       "en_respuesta_a": "...", "cita_a": null, "reposteo_a": null,
#       "metricas": {"likes": 3, ...}, "media": [{"tipo": "imagen", ...}],
#       "url": "...", "raw": {...}}
#
#  Obligatorios: `id`, `texto` (puede ser vacío solo en reposts puros) y
#  `autor_handle`. Todo lo demás es opcional y se normaliza con defaults.
#  Los adapters de `emoparse.acquisition` producen exactamente este formato.
# ══════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd
from loguru import logger

from emoparse.inputs.loader import InputError

#: Campos obligatorios por post.
REQUIRED_POST_FIELDS: tuple[str, ...] = ("id", "texto", "autor_handle")

#: Columnas del DataFrame de posts normalizado.
POST_COLUMNS: tuple[str, ...] = (
    "post_id", "plataforma", "autor_handle", "autor_display", "texto",
    "fecha", "lang", "tipo", "conversacion_id", "en_respuesta_a",
    "cita_a", "reposteo_a", "es_repost_puro", "url", "metricas", "media",
    "raw",
)


@dataclass
class PostsBundle:
    """Corpus de posts cargado y normalizado.

    `hilos` queda en None hasta que `pipeline.thread_builder.build_threads`
    reconstruye el árbol conversacional.
    """
    posts: pd.DataFrame
    autores: pd.DataFrame
    hilos: pd.DataFrame | None = None


def load_posts(path: Path | str) -> PostsBundle:
    """Carga posts desde JSONL normalizado o CSV y devuelve un bundle validado."""
    p = Path(path).expanduser().resolve()
    if not p.is_file():
        raise InputError(f"Archivo input no encontrado: {p}")

    ext = p.suffix.lower()
    if ext == ".jsonl":
        rows = _load_jsonl(p)
    elif ext == ".csv":
        rows = _load_csv(p)
    else:
        raise InputError(
            f"Extensión no soportada para posts: '{ext}'. Use .jsonl o .csv."
        )

    if not rows:
        raise InputError(f"{p} no contiene posts.")

    df = pd.DataFrame([_normalize_row(r, p) for r in rows], columns=list(POST_COLUMNS))
    _validate_unique_ids(df, p)
    _validate_texto(df, p)

    autores = _build_autores(df)

    logger.info(
        f"[Inputs] Cargados {len(df)} posts desde {p.name} "
        f"({int(df['es_repost_puro'].sum())} reposts puros, "
        f"{autores.shape[0]} autores)"
    )
    return PostsBundle(posts=df, autores=autores)


def posts_to_discursos(df_posts: pd.DataFrame) -> pd.DataFrame:
    """Deriva el DataFrame de discursos que consume el pipeline.

    Un post analizable = un discurso (codigo = post_id, contenido = texto).
    Los reposts puros no generan discurso: registran circulación, no
    enunciación propia del reposteador; su análisis emocional es el del
    post fuente.
    """
    df = df_posts[df_posts["es_repost_puro"] == 0].copy()
    if df.empty:
        raise InputError(
            "El corpus no contiene posts analizables: todos son reposts puros."
        )
    out = pd.DataFrame({
        "codigo": df["post_id"].astype(str),
        "contenido": df["texto"].astype(str),
        "titulo": df.apply(
            lambda r: f"@{r['autor_handle']}: {str(r['texto'])[:60]}", axis=1
        ),
        "fecha": df["fecha"],
        "fuente": df["plataforma"],
        "url": df["url"],
        "autor": df["autor_handle"],
        "tipo_post": df["tipo"],
        "conversacion_id": df["conversacion_id"],
        "lang": df["lang"],
    })
    return out.reset_index(drop=True)


# ══════════════════════════════════════════════════════════════════════════════
#  Lectores por formato
# ══════════════════════════════════════════════════════════════════════════════

def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    """Lee un JSONL: un objeto post por línea (líneas vacías se ignoran)."""
    rows: list[dict[str, Any]] = []
    try:
        with path.open(encoding="utf-8") as fh:
            for lineno, line in enumerate(fh, start=1):
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError as e:
                    raise InputError(
                        f"JSONL inválido en {path}:{lineno}: {e}"
                    ) from e
                if not isinstance(obj, dict):
                    raise InputError(
                        f"En {path}:{lineno}, la línea debe ser un objeto "
                        f"JSON, recibí: {type(obj).__name__}"
                    )
                rows.append(obj)
    except OSError as e:
        raise InputError(f"No pude leer {path}: {e}") from e
    return rows


def _load_csv(path: Path) -> list[dict[str, Any]]:
    """Lee un CSV plano de posts (una fila por post, sin campos anidados)."""
    try:
        df = pd.read_csv(path, encoding="utf-8", dtype={"id": str})
    except UnicodeDecodeError as e:
        raise InputError(
            f"Encoding inválido en {path} (esperaba UTF-8): {e}."
        ) from e
    except (pd.errors.EmptyDataError, pd.errors.ParserError) as e:
        raise InputError(f"CSV malformado en {path}: {e}") from e
    return df.to_dict(orient="records")


# ══════════════════════════════════════════════════════════════════════════════
#  Normalización y validaciones
# ══════════════════════════════════════════════════════════════════════════════

def _s(value: Any) -> str:
    """String seguro: None/NaN → ''."""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    return str(value).strip()


def _normalize_row(row: dict[str, Any], path: Path) -> dict[str, Any]:
    """Normaliza un post crudo a las columnas canónicas."""
    missing = [f for f in REQUIRED_POST_FIELDS if f not in row]
    if missing:
        raise InputError(
            f"En {path}, un post no trae los campos obligatorios {missing}. "
            f"Campos presentes: {sorted(row.keys())}"
        )

    post_id = _s(row["id"])
    if not post_id:
        raise InputError(f"En {path}, hay un post con `id` vacío.")

    texto = _s(row["texto"])
    en_respuesta_a = _s(row.get("en_respuesta_a")) or None
    cita_a = _s(row.get("cita_a")) or None
    reposteo_a = _s(row.get("reposteo_a")) or None

    tipo = _s(row.get("tipo")).lower() or _infer_tipo(
        en_respuesta_a, cita_a, reposteo_a
    )
    es_repost_puro = int(tipo == "repost" and not texto)

    metricas = row.get("metricas")
    media = row.get("media")
    raw = row.get("raw")

    return {
        "post_id": post_id,
        "plataforma": _s(row.get("plataforma")) or "desconocida",
        "autor_handle": _s(row["autor_handle"]).lstrip("@"),
        "autor_display": _s(row.get("autor_display")),
        "texto": texto,
        "fecha": _s(row.get("fecha")) or None,
        "lang": _s(row.get("lang")) or None,
        "tipo": tipo,
        "conversacion_id": _s(row.get("conversacion_id")) or None,
        "en_respuesta_a": en_respuesta_a,
        "cita_a": cita_a,
        "reposteo_a": reposteo_a,
        "es_repost_puro": es_repost_puro,
        "url": _s(row.get("url")) or None,
        "metricas": metricas if isinstance(metricas, dict) else {},
        "media": media if isinstance(media, list) else [],
        "raw": raw if isinstance(raw, dict) else None,
    }


def _infer_tipo(
    en_respuesta_a: str | None,
    cita_a: str | None,
    reposteo_a: str | None,
) -> str:
    """Infiere el tipo del post desde sus referencias cuando no viene dado."""
    if reposteo_a:
        return "repost"
    if cita_a:
        return "quote"
    if en_respuesta_a:
        return "reply"
    return "original"


def _validate_unique_ids(df: pd.DataFrame, path: Path) -> None:
    """Verifica que los post_id sean únicos."""
    duplicates = df["post_id"][df["post_id"].duplicated()].unique()
    if len(duplicates) > 0:
        raise InputError(
            f"En {path}, hay post_id duplicados: {list(duplicates[:5])}"
            + ("..." if len(duplicates) > 5 else "")
        )


def _validate_texto(df: pd.DataFrame, path: Path) -> None:
    """Verifica que `texto` no esté vacío salvo en reposts puros."""
    empty_mask = (df["texto"].fillna("").astype(str).str.strip() == "") & (
        df["es_repost_puro"] == 0
    )
    n_empty = int(empty_mask.sum())
    if n_empty > 0:
        ids = df.loc[empty_mask, "post_id"].tolist()
        raise InputError(
            f"En {path}, hay {n_empty} post(s) con `texto` vacío que no son "
            f"reposts puros. Ids: {ids[:5]}" + ("..." if n_empty > 5 else "")
        )


def _build_autores(df_posts: pd.DataFrame) -> pd.DataFrame:
    """Deriva el DataFrame de autores desde los posts (uno por handle)."""
    grouped = df_posts.groupby(["plataforma", "autor_handle"], sort=True)
    rows = []
    for (plataforma, handle), grp in grouped:
        displays = [d for d in grp["autor_display"].tolist() if d]
        rows.append({
            "plataforma": plataforma,
            "handle": handle,
            "display_name": displays[0] if displays else None,
            "n_posts": int(len(grp)),
        })
    return pd.DataFrame(rows)
