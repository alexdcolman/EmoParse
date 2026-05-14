# ══════════════════════════════════════════════════════════════════════════════
#  emoparse.scraping.base
#
#  Tipos base de scraping.
# ══════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import date
from typing import Any


@dataclass(frozen=True, slots=True)
class DiscursoRecord:
    """Discurso scrapeado normalizado.

    Campos:
        codigo: ID único.
        url: URL canónica.
        titulo: Título.
        fecha: ISO 'YYYY-MM-DD' o vacío.
        contenido: Texto limpio.
        fuente: source_id del adapter.
        extras: metadata adicional como tupla de pares.

    `frozen=True` para que sean hashables y comparables: dedupe trivial
    con `set(records)`.
    """
    codigo: str
    url: str
    titulo: str
    fecha: str
    contenido: str
    fuente: str
    extras: tuple[tuple[str, Any], ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, Any]:
        """Convierte el record a dict, expandiendo `extras` al top-level.

        Claves en conflicto se guardan con prefijo `extra__`.
        """
        d: dict[str, Any] = {
            "codigo":    self.codigo,
            "url":       self.url,
            "titulo":    self.titulo,
            "fecha":     self.fecha,
            "contenido": self.contenido,
            "fuente":    self.fuente,
        }
        nativos = set(d.keys())
        for k, v in self.extras:
            if k in nativos:
                d[f"extra__{k}"] = v
            else:
                d[k] = v
        return d


class SourceAdapter(ABC):
    """Interfaz abstracta de un adapter de fuente."""

    source_id: str = ""
    requires_selenium: bool = False

    @abstractmethod
    def list_discursos(
        self,
        *,
        max_items: int | None = None,
        from_date: date | None = None,
        to_date: date | None = None,
    ) -> Iterator[str]:
        """Itera URLs de discursos de la fuente."""

    @abstractmethod
    def fetch_discurso(self, url: str) -> DiscursoRecord | None:
        """Extrae el contenido de un discurso individual."""

    def close(self) -> None:
        """Libera recursos (sesiones HTTP, drivers, etc.). Default no-op."""

    def __enter__(self) -> SourceAdapter:
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()
