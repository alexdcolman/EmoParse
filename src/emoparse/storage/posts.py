# ══════════════════════════════════════════════════════════════════════════════
#  emoparse.storage.posts
#
#  Repositorio de las tablas `posts`, `autores` y `media`.
# ══════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

import json
from typing import Any

from emoparse.storage.db import Database


def _j(value: Any) -> str | None:
    """Serializa a JSON, None si el valor es vacío/None."""
    if value in (None, "", [], {}):
        return None
    return json.dumps(value, ensure_ascii=False, default=str)


class PostsRepository:
    """Repositorio de `posts`, `autores` y `media`."""

    def __init__(self, db: Database) -> None:
        self._db = db

    # ── Escritura ────────────────────────────────────────────────────────────

    def upsert_posts(self, rows: list[dict[str, Any]]) -> int:
        """Upsertea posts por `post_id`, preservando `created_at`.

        Cada row usa las claves canónicas del loader de posts (`post_id`,
        `plataforma`, `autor_handle`, `texto`, ...). `metricas` y `raw`
        pueden venir como dict: se serializan a JSON.
        """
        n = 0
        with self._db.transaction() as cur:
            for r in rows:
                cur.execute(
                    """
                    INSERT INTO posts (
                        post_id, plataforma, autor_handle, texto, fecha, lang,
                        tipo, conversacion_id, en_respuesta_a, cita_a,
                        reposteo_a, es_repost_puro, huerfano, profundidad,
                        url, metricas, raw
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(post_id) DO UPDATE SET
                        plataforma      = excluded.plataforma,
                        autor_handle    = excluded.autor_handle,
                        texto           = excluded.texto,
                        fecha           = excluded.fecha,
                        lang            = excluded.lang,
                        tipo            = excluded.tipo,
                        conversacion_id = excluded.conversacion_id,
                        en_respuesta_a  = excluded.en_respuesta_a,
                        cita_a          = excluded.cita_a,
                        reposteo_a      = excluded.reposteo_a,
                        es_repost_puro  = excluded.es_repost_puro,
                        huerfano        = excluded.huerfano,
                        profundidad     = excluded.profundidad,
                        url             = excluded.url,
                        metricas        = excluded.metricas,
                        raw             = excluded.raw,
                        updated_at      = CURRENT_TIMESTAMP
                    """,
                    (
                        r["post_id"], r["plataforma"], r["autor_handle"],
                        r["texto"], r.get("fecha"), r.get("lang"),
                        r.get("tipo", "original"), r.get("conversacion_id"),
                        r.get("en_respuesta_a"), r.get("cita_a"),
                        r.get("reposteo_a"), int(r.get("es_repost_puro", 0)),
                        int(r.get("huerfano", 0)), _int_or_none(r.get("profundidad")),
                        r.get("url"), _j(r.get("metricas")), _j(r.get("raw")),
                    ),
                )
                n += 1
        return n

    def upsert_autores(self, rows: list[dict[str, Any]]) -> int:
        """Upsertea autores por (plataforma, handle)."""
        n = 0
        with self._db.transaction() as cur:
            for r in rows:
                cur.execute(
                    """
                    INSERT INTO autores (
                        plataforma, handle, display_name, bio, verificado,
                        seguidores, siguiendo, url, extras
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(plataforma, handle) DO UPDATE SET
                        display_name = COALESCE(excluded.display_name,
                                                autores.display_name),
                        bio          = COALESCE(excluded.bio, autores.bio),
                        verificado   = COALESCE(excluded.verificado,
                                                autores.verificado),
                        seguidores   = COALESCE(excluded.seguidores,
                                                autores.seguidores),
                        siguiendo    = COALESCE(excluded.siguiendo,
                                                autores.siguiendo),
                        url          = COALESCE(excluded.url, autores.url),
                        extras       = COALESCE(excluded.extras, autores.extras),
                        updated_at   = CURRENT_TIMESTAMP
                    """,
                    (
                        r["plataforma"], r["handle"], r.get("display_name"),
                        r.get("bio"), _int_or_none(r.get("verificado")),
                        _int_or_none(r.get("seguidores")),
                        _int_or_none(r.get("siguiendo")),
                        r.get("url"), _j(r.get("extras")),
                    ),
                )
                n += 1
        return n

    def replace_media(self, post_id: str, items: list[dict[str, Any]]) -> int:
        """Reemplaza los adjuntos de un post (idempotente).

        Preserva las filas ya enriquecidas por análisis multimodal solo si el
        adjunto reaparece con la misma URL; el reemplazo total mantiene la
        carga simple y la descripción se recalcula si hiciera falta.
        """
        with self._db.transaction() as cur:
            cur.execute("DELETE FROM media WHERE post_id = ?", (post_id,))
            for m in items:
                cur.execute(
                    """
                    INSERT INTO media (post_id, tipo, url, path_local, alt_text)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        post_id, m.get("tipo", "otro"), m.get("url"),
                        m.get("path_local"), m.get("alt") or m.get("alt_text"),
                    ),
                )
        return len(items)



    # ── Descripción multimodal de media ──────────────────────────────────────

    def list_media_pending_descripcion(self) -> list[dict[str, Any]]:
        """Adjuntos de imagen sin descripción generada (ni error), con el
        texto del post que acompañan."""
        rows = self._db.execute(
            "SELECT m.*, p.texto AS post_texto FROM media m "
            "JOIN posts p ON p.post_id = m.post_id "
            "WHERE m.tipo = 'imagen' "
            "AND (m.url IS NOT NULL OR m.path_local IS NOT NULL) "
            "AND m.descripcion_payload IS NULL AND m.descripcion_error IS NULL "
            "ORDER BY m.post_id, m.id"
        ).fetchall()
        return [dict(r) for r in rows]

    def set_media_descripcion(
        self,
        media_id: int,
        payload: dict[str, Any],
        version: str | None = None,
    ) -> None:
        """Registra la descripción generada de un adjunto."""
        with self._db.transaction() as cur:
            cur.execute(
                "UPDATE media SET descripcion_payload = ?, "
                "descripcion_version = ?, descripcion_error = NULL, "
                "ocr_text = ? WHERE id = ?",
                (
                    json.dumps(payload, ensure_ascii=False), version,
                    payload.get("texto_en_imagen") or None, media_id,
                ),
            )

    def set_media_descripcion_error(self, media_id: int, error: str) -> None:
        """Registra un error de descripción para reintento posterior."""
        with self._db.transaction() as cur:
            cur.execute(
                "UPDATE media SET descripcion_error = ? WHERE id = ?",
                (error[:500], media_id),
            )

    def media_descripciones_of_post(self, post_id: str) -> list[dict[str, Any]]:
        """Descripciones generadas de los adjuntos de un post."""
        rows = self._db.execute(
            "SELECT * FROM media WHERE post_id = ? "
            "AND descripcion_payload IS NOT NULL ORDER BY id",
            (post_id,),
        ).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            try:
                d["descripcion_payload"] = json.loads(d["descripcion_payload"])
            except (json.JSONDecodeError, TypeError):
                pass
            out.append(d)
        return out

    # ── Reframing ────────────────────────────────────────────────────────────

    def list_pending_reframing(self) -> list[dict[str, Any]]:
        """Posts que citan (o repostean con comentario) sin reframing aún."""
        rows = self._db.execute(
            "SELECT * FROM posts "
            "WHERE (cita_a IS NOT NULL "
            "       OR (reposteo_a IS NOT NULL AND TRIM(texto) != '')) "
            "AND es_repost_puro = 0 "
            "AND reframing_payload IS NULL AND reframing_error IS NULL "
            "ORDER BY post_id"
        ).fetchall()
        return [_row_to_post(r) for r in rows]

    def set_reframing(
        self,
        post_id: str,
        payload: dict[str, Any],
        version: str | None = None,
    ) -> None:
        """Marca un post como clasificado por reframing."""
        with self._db.transaction() as cur:
            cur.execute(
                "UPDATE posts SET reframing_payload = ?, "
                "reframing_version = ?, reframing_error = NULL, "
                "updated_at = CURRENT_TIMESTAMP WHERE post_id = ?",
                (json.dumps(payload, ensure_ascii=False), version, post_id),
            )

    def set_reframing_error(self, post_id: str, error: str) -> None:
        """Registra un error de reframing para reintento posterior."""
        with self._db.transaction() as cur:
            cur.execute(
                "UPDATE posts SET reframing_error = ?, "
                "updated_at = CURRENT_TIMESTAMP WHERE post_id = ?",
                (error[:500], post_id),
            )

    def clear_reframing_errors(self) -> int:
        """Limpia errores de reframing (para reintentar). Devuelve afectados."""
        with self._db.transaction() as cur:
            cur.execute(
                "UPDATE posts SET reframing_error = NULL "
                "WHERE reframing_error IS NOT NULL"
            )
            return cur.rowcount

    # ── Lectura ──────────────────────────────────────────────────────────────

    def get_post(self, post_id: str) -> dict[str, Any] | None:
        """Devuelve un post por id, con `metricas`/`raw` parseados."""
        row = self._db.execute(
            "SELECT * FROM posts WHERE post_id = ?", (post_id,)
        ).fetchone()
        return _row_to_post(row) if row is not None else None

    def list_by_conversacion(self, conversacion_id: str) -> list[dict[str, Any]]:
        """Posts de una conversación, ordenados por fecha y luego por id."""
        rows = self._db.execute(
            "SELECT * FROM posts WHERE conversacion_id = ? "
            "ORDER BY fecha, post_id",
            (conversacion_id,),
        ).fetchall()
        return [_row_to_post(r) for r in rows]

    def list_media(self, post_id: str) -> list[dict[str, Any]]:
        """Adjuntos de un post."""
        rows = self._db.execute(
            "SELECT * FROM media WHERE post_id = ? ORDER BY id", (post_id,)
        ).fetchall()
        return [dict(r) for r in rows]

    def naturaleza_by_handle(self) -> dict[str, str]:
        """Mapa handle → naturaleza del referente derivada de la cuenta.

        Heurística mínima: toda cuenta es al menos 'persona' salvo señal en
        contrario; el refinamiento (colectivo/institución) es materia de la
        revisión de referentes.
        """
        rows = self._db.execute("SELECT handle FROM autores").fetchall()
        return {str(r["handle"]): "persona" for r in rows}

    def counts(self) -> dict[str, int]:
        """Conteos básicos del corpus de posts."""
        row = self._db.execute(
            "SELECT COUNT(*) AS total, "
            "SUM(es_repost_puro) AS reposts_puros, "
            "SUM(huerfano) AS huerfanos FROM posts"
        ).fetchone()
        return {
            "total": int(row["total"] or 0),
            "reposts_puros": int(row["reposts_puros"] or 0),
            "huerfanos": int(row["huerfanos"] or 0),
        }


def _int_or_none(value: Any) -> int | None:
    """Castea a int tolerando None/NaN/pd.NA."""
    if value is None:
        return None
    try:
        import pandas as pd
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _row_to_post(row: Any) -> dict[str, Any]:
    """Convierte una fila SQLite a dict con JSON parseado."""
    d = dict(row)
    for field in ("metricas", "raw"):
        raw = d.get(field)
        if isinstance(raw, str) and raw:
            try:
                d[field] = json.loads(raw)
            except json.JSONDecodeError:
                pass
    return d
