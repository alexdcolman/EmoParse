# ══════════════════════════════════════════════════════════════════════════════
#  emoparse.acquisition.normalize
#
#  Funciones de normalización para campos extraídos por adapters.
# ══════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

import re
import unicodedata
from datetime import date, datetime
from typing import Optional


# Boilerplates comunes.
_BOILERPLATE_LINES: tuple[str, ...] = (
    "compartir",
    "compartir en facebook",
    "compartir en twitter",
    "imprimir",
    "descargar pdf",
)


#: Mapeo de meses en español a número.
_MESES_ES: dict[str, int] = {
    "enero": 1, "febrero": 2, "marzo": 3, "abril": 4,
    "mayo": 5, "junio": 6, "julio": 7, "agosto": 8,
    "septiembre": 9, "setiembre": 9, "octubre": 10,
    "noviembre": 11, "diciembre": 12,
}


def clean_whitespace(text: str) -> str:
    """Colapsa whitespace consecutivo, preserva saltos de párrafo dobles."""
    if not text:
        return ""
    text = text.replace("\u00a0", " ")
    lines = []
    blank_run = False
    for ln in text.splitlines():
        stripped = ln.strip()
        if stripped == "":
            if not blank_run and lines:
                lines.append("")
                blank_run = True
        else:
            lines.append(re.sub(r"[ \t]+", " ", stripped))
            blank_run = False
    while lines and lines[0] == "":
        lines.pop(0)
    while lines and lines[-1] == "":
        lines.pop()
    return "\n".join(lines)


def strip_boilerplate(text: str) -> str:
    """Quita líneas que coinciden con boilerplate conocido."""
    if not text:
        return text
    cleaned = []
    for ln in text.split("\n"):
        if ln.strip().lower() in _BOILERPLATE_LINES:
            continue
        cleaned.append(ln)
    return "\n".join(cleaned).strip()


def normalize_date(raw: str) -> str:
    """Normaliza fecha a 'YYYY-MM-DD' o devuelve '' si falla."""
    if not raw:
        return ""
    raw = raw.strip()

    iso = _try_parse_iso(raw)
    if iso:
        return iso

    m = re.search(r"(\d{1,2})[-/](\d{1,2})[-/](\d{4})", raw)
    if m:
        d, mo, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
        try:
            return date(y, mo, d).isoformat()
        except ValueError:
            pass

    raw_low = _strip_accents(raw.lower())
    m = re.search(
        r"(\d{1,2})\s+de\s+([a-z]+)[\s,]+(?:de\s+)?(\d{4})",
        raw_low,
    )
    if m:
        d, mes_nombre, y = int(m.group(1)), m.group(2), int(m.group(3))
        mo = _MESES_ES.get(mes_nombre)
        if mo:
            try:
                return date(y, mo, d).isoformat()
            except ValueError:
                pass

    return ""


def _try_parse_iso(raw: str) -> Optional[str]:
    """Parsea ISO y devuelve 'YYYY-MM-DD' o None."""
    try:
        dt = datetime.fromisoformat(raw)
        return dt.date().isoformat()
    except ValueError:
        pass
    try:
        return date.fromisoformat(raw[:10]).isoformat()
    except ValueError:
        return None


def _strip_accents(s: str) -> str:
    """Quita tildes para matching de meses."""
    return "".join(
        c for c in unicodedata.normalize("NFD", s)
        if unicodedata.category(c) != "Mn"
    )


def normalize_url(url: str, base: str = "") -> str:
    """Resuelve URL relativa a absoluta; preserva absoluta."""
    if not url:
        return ""
    url = url.strip()
    if url.startswith(("http://", "https://")):
        return url
    if not base:
        return url
    base = base.rstrip("/")
    if url.startswith("/"):
        return f"{base}{url}"
    return f"{base}/{url}"
