# ══════════════════════════════════════════════════════════════════════════════
#  emoparse.acquisition.base
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
        extras: metadata normalizada adicional como tupla de pares.
        raw: snapshot estructurado de la fuente para auditoría y reprocesamiento.

    `frozen=True` conserva el contrato hashable/comparable. `raw` queda fuera
    de igualdad y hash porque puede contener dicts/listas y no debe alterar la
    identidad normalizada del registro.
    """

    codigo: str
    url: str
    titulo: str
    fecha: str
    contenido: str
    fuente: str
    extras: tuple[tuple[str, Any], ...] = field(default_factory=tuple)
    raw: dict[str, Any] | None = field(default=None, compare=False, hash=False, repr=False)

    def to_dict(self) -> dict[str, Any]:
        """Convierte el record a dict, expandiendo `extras` al top-level.

        Claves en conflicto se guardan con prefijo `extra__`.
        """
        d: dict[str, Any] = {
            "codigo": self.codigo,
            "url": self.url,
            "titulo": self.titulo,
            "fecha": self.fecha,
            "contenido": self.contenido,
            "fuente": self.fuente,
        }
        if self.raw is not None:
            d["raw"] = self.raw
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

    def accepts_record(self, record: DiscursoRecord) -> bool:
        """Indica si un registro extraído debe persistirse en la corrida actual.

        El default conserva el contrato histórico: todo registro válido se
        persiste. Una fuente puede sobrescribirlo cuando expone filtros
        semánticos que sólo pueden resolverse después de identificar el
        documento (por ejemplo, subtipos editoriales).
        """
        return True

    def counts_toward_max(self, record: DiscursoRecord) -> bool:
        """Indica si un registro escrito consume el tope de ``scrape --max``.

        El default conserva el contrato histórico: todo registro válido cuenta.
        Una fuente puede sobrescribirlo cuando preserva documentos auxiliares
        que deben escribirse pero no representan el tipo principal solicitado.
        """
        return True

    def close(self) -> None:  # noqa: B027
        """Libera recursos (sesiones HTTP, drivers, etc.). Default no-op."""

    def __enter__(self) -> SourceAdapter:
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()
