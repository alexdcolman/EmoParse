# ══════════════════════════════════════════════════════════════════════════════
#  emoparse.core.cache.keys
#
#  Generación de claves de cache LLM.
#
#  La clave es un hash determinístico de todos los factores que afectan la respuesta:
#  - model_alias
#  - system_hash
#  - user_hash
#  - schema_qualname
#  - seed
#  - knowledge_version
#  - prompt_version
#  - ontology_version
#  - schema_version
#  - images_digest (solo en llamadas con imágenes; hash del contenido visual)
#
#  Bumpear cualquier *_version invalida selectivamente los agentes afectados.
# ══════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

from emoparse.storage.models import Versions


def compute_images_digest(images: list[str] | None) -> str | None:
    """Digest estable del contenido visual de una llamada.

    Cada entrada de `images` puede ser un path local o una URL. Los paths
    locales se hashean por contenido (sha256 de los bytes del archivo); las
    URLs, por el string de la URL. Limitación documentada: si el contenido
    detrás de una URL cambia sin cambiar la URL, el cache devuelve un falso
    hit; para garantizar frescura hay que usar paths locales o bumpear una
    version.

    Args:
        images: Referencias a imágenes (paths locales o URLs), o None.

    Returns:
        Hash hexadecimal agregado (sensible al orden), o None si la llamada
        no lleva imágenes.
    """
    if not images:
        return None
    agg = hashlib.sha256()
    for ref in images:
        ref_str = str(ref)
        data: bytes | None = None
        try:
            p = Path(ref_str)
            if p.is_file():
                data = p.read_bytes()
        except (OSError, ValueError):
            data = None
        if data is not None:
            agg.update(hashlib.sha256(data).digest())
        else:
            # URL (o path ilegible, que fallará igual en el backend): se
            # hashea la referencia como string.
            agg.update(hashlib.sha256(ref_str.encode("utf-8")).digest())
    return agg.hexdigest()


@dataclass(frozen=True, slots=True)
class CacheKey:
    """Clave de cache y metadatos de auditoría.

    digest es el PK en llm_cache; otros campos sirven para debug, queries y cleanup.
    """
    digest: str
    model_alias: str
    schema_qualname: str | None
    knowledge_version: str | None
    prompt_version: str | None
    ontology_version: str | None
    schema_version: str | None


def make_cache_key(
    *,
    model_alias: str,
    system: str,
    user: str,
    schema_qualname: str | None,
    seed: int | None,
    versions: Versions,
    images_digest: str | None = None,
) -> CacheKey:
    """Genera una clave de cache determinística.

    Args:
        model_alias: Alias del modelo.
        system: Texto completo del system prompt.
        user: Texto completo del user prompt.
        schema_qualname: Qualified name del schema Pydantic o None
                         si la llamada es de texto libre.
        seed: Seed del sampler.
        versions: Las 4 versions del run.
        images_digest: Hash del contenido visual de la llamada (ver
                       `compute_images_digest`) o None si no hay imágenes.
                       Se incorpora a la clave solo cuando existe, así las
                       claves de llamadas de texto no cambian.

    Returns:
        CacheKey con digest + metadata para auditoría.
    """
    # Hash SHA-256 de system y user prompts.
    system_hash = hashlib.sha256(system.encode("utf-8")).hexdigest()
    user_hash = hashlib.sha256(user.encode("utf-8")).hexdigest()

    # Construir cadena para hash final; separador "|||"; None tratado como
    # vacío para estabilidad.
    parts = [
        f"model={model_alias}",
        f"system={system_hash}",
        f"user={user_hash}",
        f"schema={schema_qualname or ''}",
        f"seed={seed if seed is not None else ''}",
        f"kv={versions.knowledge or ''}",
        f"pv={versions.prompt or ''}",
        f"ov={versions.ontology or ''}",
        f"sv={versions.schema or ''}",
    ]
    if images_digest:
        # Componente condicional: preserva intactas las claves ya emitidas
        # para llamadas sin imágenes.
        parts.append(f"img={images_digest}")
    raw = "|||".join(parts)
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()

    return CacheKey(
        digest=digest,
        model_alias=model_alias,
        schema_qualname=schema_qualname,
        knowledge_version=versions.knowledge,
        prompt_version=versions.prompt,
        ontology_version=versions.ontology,
        schema_version=versions.schema,
    )
