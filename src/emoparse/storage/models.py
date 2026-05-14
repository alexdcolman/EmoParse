# ══════════════════════════════════════════════════════════════════════════════
#  emoparse.storage.models
#
#  Objetos de valor compartidos entre storage, cache, runner.
# ══════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Any


@dataclass(frozen=True, slots=True)
class Versions:
    """Versions activas durante un run. Cada una invalida selectivamente."""
    knowledge: str | None = None
    prompt: str | None = None
    ontology: str | None = None
    schema: str | None = None

    def to_dict(self) -> dict[str, str | None]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, str | None]) -> Versions:
        return cls(
            knowledge=d.get("knowledge"),
            prompt=d.get("prompt"),
            ontology=d.get("ontology"),
            schema=d.get("schema"),
        )


@dataclass(frozen=True, slots=True)
class RunContext:
    """Contexto completo de un run del pipeline.

    Pasa a:
        - El Runner (orquesta las etapas).
        - Cada agente (sabe su versión).
        - El cache (decide hit/miss).
        - Los repositorios (saben qué run_id escribir).
    """
    run_id: str
    versions: Versions = field(default_factory=Versions)
    started_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    config: dict[str, Any] = field(default_factory=dict)
    notes: str = ""
