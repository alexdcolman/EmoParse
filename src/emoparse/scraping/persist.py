# ══════════════════════════════════════════════════════════════════════════════
#  emoparse.scraping.persist
#
#  Persistencia incremental a CSV de DiscursoRecord.
# ══════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

import csv
from pathlib import Path

from loguru import logger

from emoparse.scraping.base import DiscursoRecord


#: Columnas obligatorias en orden.
_REQUIRED_COLUMNS: tuple[str, ...] = (
    "codigo", "url", "titulo", "fecha", "contenido", "fuente",
)


class CsvAppender:
    """Append-only CSV writer con dedupe por URL."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._existing_urls: set[str] = set()
        self._existing_columns: list[str] = []
        self._load_existing()

    def _load_existing(self) -> None:
        """Carga URLs y header si el CSV existe."""
        if not self.path.exists():
            return
        try:
            with self.path.open("r", encoding="utf-8-sig", newline="") as f:
                reader = csv.DictReader(f)
                self._existing_columns = list(reader.fieldnames or [])
                for row in reader:
                    url = row.get("url", "").strip()
                    if url:
                        self._existing_urls.add(url)
            logger.info(
                f"[CsvAppender] {self.path.name}: {len(self._existing_urls)} URLs ya presentes"
            )
        except Exception as e:
            logger.warning(f"[CsvAppender] No se pudo leer CSV existente: {e}")

    def has_url(self, url: str) -> bool:
        return url in self._existing_urls

    def append(self, record: DiscursoRecord) -> None:
        """Agrega un record al CSV. Idempotente por URL."""
        if record.url in self._existing_urls:
            return

        d = record.to_dict()

        is_new = not self.path.exists() or self.path.stat().st_size == 0
        if is_new:
            self._existing_columns = list(_REQUIRED_COLUMNS) + [
                k for k in d.keys() if k not in _REQUIRED_COLUMNS
            ]

        new_cols = [k for k in d.keys() if k not in self._existing_columns]
        if new_cols and not is_new:
            self._extend_header(new_cols)

        with self.path.open("a", encoding="utf-8-sig", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=self._existing_columns)
            if is_new:
                writer.writeheader()
            writer.writerow({k: d.get(k, "") for k in self._existing_columns})

        self._existing_urls.add(record.url)

    def _extend_header(self, new_cols: list[str]) -> None:
        """Reescribe el CSV agregando columnas nuevas al header."""
        rows = []
        with self.path.open("r", encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                rows.append(row)

        self._existing_columns = list(self._existing_columns) + new_cols

        with self.path.open("w", encoding="utf-8-sig", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=self._existing_columns)
            writer.writeheader()
            for row in rows:
                writer.writerow({k: row.get(k, "") for k in self._existing_columns})

        logger.debug(f"[CsvAppender] Header extendido con {new_cols}")

    def __enter__(self) -> CsvAppender:
        return self

    def __exit__(self, *exc: object) -> None:
        pass
