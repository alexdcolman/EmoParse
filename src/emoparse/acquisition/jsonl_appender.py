# ══════════════════════════════════════════════════════════════════════════════
#  emoparse.acquisition.jsonl_appender
#
#  Persistencia incremental de posts a JSONL, con dedupe por id.
# ══════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

import json
from pathlib import Path

from emoparse.acquisition.post_record import PostRecord


class JsonlAppender:
    """Append idempotente de `PostRecord` a un archivo JSONL.

    Al abrir, indexa los ids ya presentes en el archivo; `has_id` permite
    saltear posts ya capturados, de modo que una adquisición interrumpida se
    reanuda donde quedó. Cada `append` escribe una línea y hace flush, así
    un Ctrl-C no pierde lo extraído.
    """

    def __init__(self, path: Path | str) -> None:
        self._path = Path(path).expanduser().resolve()
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._ids: set[str] = self._load_existing_ids()
        self._fh = self._path.open("a", encoding="utf-8")

    @property
    def path(self) -> Path:
        """Path del JSONL de salida."""
        return self._path

    def _load_existing_ids(self) -> set[str]:
        """Indexa los ids del archivo existente (líneas ilegibles se ignoran)."""
        if not self._path.is_file():
            return set()
        ids: set[str] = set()
        with self._path.open(encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(obj, dict) and obj.get("id"):
                    ids.add(str(obj["id"]))
        return ids

    def has_id(self, post_id: str) -> bool:
        """True si el post ya está en el archivo (o fue appendeado en sesión)."""
        return post_id in self._ids

    def append(self, record: PostRecord) -> bool:
        """Escribe el post si no estaba; devuelve True si escribió."""
        if record.id in self._ids:
            return False
        self._fh.write(
            json.dumps(record.to_json_dict(), ensure_ascii=False, default=str)
            + "\n"
        )
        self._fh.flush()
        self._ids.add(record.id)
        return True

    def __len__(self) -> int:
        return len(self._ids)

    def close(self) -> None:
        """Cierra el archivo."""
        self._fh.close()

    def __enter__(self) -> "JsonlAppender":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()
