# ══════════════════════════════════════════════════════════════════════════════
#  emoparse.acquisition.post_record
#
#  Registro normalizado de un post de red social.
#
#  Todos los adapters de posts producen `PostRecord`, independientemente de la
#  plataforma. Su serialización JSON (una línea por post) es el formato que
#  consume `emoparse.inputs.posts_loader`.
# ══════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

#: Tipos de post reconocidos.
PostTipo = str  # 'original' | 'reply' | 'quote' | 'repost'


@dataclass(frozen=True)
class PostRecord:
    """Post normalizado, independiente de la plataforma de origen.

    Campos obligatorios: `id`, `plataforma`, `autor_handle` y `texto`
    (vacío solo en reposts puros). Las referencias (`en_respuesta_a`,
    `cita_a`, `reposteo_a`) usan ids de la misma plataforma y pueden apuntar
    a posts no capturados. `raw` conserva el objeto crudo de la fuente para
    auditoría y reprocesamiento.
    """

    id: str
    plataforma: str
    autor_handle: str
    texto: str
    fecha: str | None = None          # ISO-8601
    lang: str | None = None
    tipo: PostTipo = "original"
    conversacion_id: str | None = None
    en_respuesta_a: str | None = None
    cita_a: str | None = None
    reposteo_a: str | None = None
    url: str | None = None
    autor_display: str | None = None
    autor_bio: str | None = None
    autor_seguidores: int | None = None
    autor_siguiendo: int | None = None
    autor_verificado: bool | None = None
    metricas: dict[str, Any] = field(default_factory=dict)
    media: tuple[dict[str, Any], ...] = ()
    raw: dict[str, Any] | None = None

    def to_json_dict(self) -> dict[str, Any]:
        """Dict serializable a JSON, con las claves del formato normalizado."""
        return {
            "id": self.id,
            "plataforma": self.plataforma,
            "autor_handle": self.autor_handle,
            "autor_display": self.autor_display,
            "texto": self.texto,
            "fecha": self.fecha,
            "lang": self.lang,
            "tipo": self.tipo,
            "conversacion_id": self.conversacion_id,
            "en_respuesta_a": self.en_respuesta_a,
            "cita_a": self.cita_a,
            "reposteo_a": self.reposteo_a,
            "url": self.url,
            "autor_bio": self.autor_bio,
            "autor_seguidores": self.autor_seguidores,
            "autor_siguiendo": self.autor_siguiendo,
            "autor_verificado": self.autor_verificado,
            "metricas": dict(self.metricas),
            "media": [dict(m) for m in self.media],
            "raw": self.raw,
        }

    @property
    def es_repost_puro(self) -> bool:
        """True si es un repost sin texto propio (circulación, no enunciación)."""
        return self.tipo == "repost" and not self.texto.strip()
