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
#
#  Bumpear cualquier *_version invalida selectivamente los agentes afectados.
# ══════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

import hashlib
from dataclasses import dataclass

from emoparse.storage.models import Versions


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
