# ══════════════════════════════════════════════════════════════════════════════
#  emoparse.knowledge.kb_editor
#
#  Edita `actors_kb.json` de forma segura: validación + backup + escritura
#  atómica (write a temp + rename).
# ══════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

import json
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from loguru import logger


class KbEditorError(ValueError):
    """Error al editar la KB de actores."""


#: Regex de un canonical_id válido.
_CANONICAL_ID_RE = re.compile(r"^[a-z][a-z0-9_]{1,63}$")

#: Tipos válidos. Se mantienen abiertos pero documentados.
_DEFAULT_TIPO = "desconocido"


def _validate_canonical_id(canonical_id: str) -> None:
    """Valida que el canonical_id sea un slug aceptable."""
    if not _CANONICAL_ID_RE.match(canonical_id):
        raise KbEditorError(
            f"canonical_id inválido: '{canonical_id}'. Debe ser slug ASCII "
            f"(minúsculas, dígitos, guiones bajos), empezar por letra, "
            f"entre 2 y 64 caracteres."
        )


def load_kb(kb_path: Path) -> dict[str, Any]:
    """Carga la KB desde el archivo JSON."""
    if not kb_path.is_file():
        raise KbEditorError(f"KB no encontrada: {kb_path}")
    try:
        text = kb_path.read_text(encoding="utf-8")
    except OSError as e:
        raise KbEditorError(f"No pude leer {kb_path}: {e}") from e
    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        raise KbEditorError(f"JSON inválido en {kb_path}: {e}") from e
    if not isinstance(data, dict):
        raise KbEditorError(
            f"La raíz de {kb_path} debe ser un objeto, recibí: "
            f"{type(data).__name__}"
        )
    if "actors" not in data or not isinstance(data["actors"], dict):
        raise KbEditorError(
            f"La KB en {kb_path} debe tener una clave 'actors' (dict)."
        )
    return data


def _atomic_write(kb_path: Path, data: dict[str, Any]) -> None:
    """Escribe data al JSON de forma atómica (temp + rename).

    El rename es atómico en POSIX, garantizando que el archivo nunca queda
    en un estado parcialmente escrito si el proceso es interrumpido.
    """
    tmp = kb_path.with_suffix(kb_path.suffix + ".tmp")
    try:
        tmp.write_text(
            json.dumps(data, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        tmp.replace(kb_path)
    except OSError as e:
        if tmp.exists():
            try:
                tmp.unlink()
            except OSError:
                pass
        raise KbEditorError(f"No pude escribir {kb_path}: {e}") from e


def backup_kb(kb_path: Path) -> Path:
    """Crea un backup `.bak.<UTC timestamp>` y devuelve su path."""
    if not kb_path.is_file():
        return kb_path.with_suffix(".bak.NONE")
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    bak = kb_path.with_suffix(kb_path.suffix + f".bak.{ts}")
    shutil.copy2(kb_path, bak)
    logger.info(f"[kb_editor] Backup creado: {bak}")
    return bak


# ══════════════════════════════════════════════════════════════════════════════
#  Operaciones de mutación
# ══════════════════════════════════════════════════════════════════════════════

def promote(
    kb_path: Path,
    *,
    canonical_id: str,
    display_name: str,
    aliases_iniciales: list[str] | None = None,
    tipo: str = _DEFAULT_TIPO,
    rol: str | None = None,
    notas: str | None = None,
) -> None:
    """Crea un nuevo canónico en la KB.

    Idempotencia: si ya existe una entrada con el mismo `canonical_id`,
    se considera idempotente y se completan campos faltantes (aliases
    adicionales se mergean sin duplicar). Esto permite re-ejecutar
    `apply` sin temor.
    """
    _validate_canonical_id(canonical_id)
    data = load_kb(kb_path)
    actors = data["actors"]

    if canonical_id in actors:
        existing = actors[canonical_id]
        if not isinstance(existing, dict):
            raise KbEditorError(
                f"Entrada existente '{canonical_id}' está corrupta "
                f"(no es objeto)."
            )
        existing_name = existing.get("display_name")
        if existing_name and existing_name != display_name:
            raise KbEditorError(
                f"Conflicto en '{canonical_id}': display_name existente "
                f"'{existing_name}' != propuesto '{display_name}'. "
                f"Editá manualmente la KB si querés renombrar."
            )
        if aliases_iniciales:
            current = list(existing.get("aliases") or [])
            current_lower = {a.strip().lower() for a in current}
            for a in aliases_iniciales:
                a_stripped = a.strip()
                if a_stripped and a_stripped.lower() not in current_lower:
                    current.append(a_stripped)
                    current_lower.add(a_stripped.lower())
            existing["aliases"] = current
        # No se sobreescriben campos ya presentes; solo se rellenan vacíos.
        if "display_name" not in existing:
            existing["display_name"] = display_name
        if "tipo" not in existing:
            existing["tipo"] = tipo
        if rol and "rol" not in existing:
            existing["rol"] = rol
        if notas and "notas" not in existing:
            existing["notas"] = notas
        _atomic_write(kb_path, data)
        logger.info(
            f"[kb_editor] promote '{canonical_id}' (idempotente, ya existía)"
        )
        return

    entry: dict[str, Any] = {
        "display_name": display_name,
        "aliases": list(aliases_iniciales or []),
        "tipo": tipo,
    }
    if rol:
        entry["rol"] = rol
    if notas:
        entry["notas"] = notas
    actors[canonical_id] = entry
    _atomic_write(kb_path, data)
    logger.info(f"[kb_editor] promote '{canonical_id}' (nuevo)")


def merge(
    kb_path: Path,
    *,
    canonical_id: str,
    alias_to_add: str,
) -> None:
    """Agrega `alias_to_add` a la lista de aliases de `canonical_id`.

    Idempotencia: si el alias ya está presente (case-insensitive comparison),
    no se duplica.
    """
    alias_stripped = alias_to_add.strip()
    if not alias_stripped:
        raise KbEditorError("alias_to_add vacío.")

    data = load_kb(kb_path)
    actors = data["actors"]
    if canonical_id not in actors:
        raise KbEditorError(
            f"Canónico '{canonical_id}' no existe en la KB. "
            f"Para crearlo, usar 'promote' primero."
        )
    entry = actors[canonical_id]
    if not isinstance(entry, dict):
        raise KbEditorError(
            f"Entrada '{canonical_id}' corrupta (no es objeto)."
        )
    aliases = list(entry.get("aliases") or [])
    if alias_stripped.lower() in {a.strip().lower() for a in aliases}:
        logger.info(
            f"[kb_editor] merge '{alias_stripped}' → '{canonical_id}' "
            f"(idempotente, ya estaba)"
        )
        return
    aliases.append(alias_stripped)
    entry["aliases"] = aliases
    _atomic_write(kb_path, data)
    logger.info(f"[kb_editor] merge '{alias_stripped}' → '{canonical_id}'")


def discard(kb_path: Path, *, mencion: str) -> None:
    """No modifica la KB. Existe por simetría con `promote`/`merge`.

    El descarte es semánticamente "esta mención no entra a la KB": no hay
    nada que escribir en el JSON. La decisión queda registrada solo en
    `actors_kb_decisions`. El parámetro `mencion` se acepta por
    homogeneidad de la API y para que la firma sea legible al loggear.
    """
    if not kb_path.is_file():
        raise KbEditorError(f"KB no encontrada: {kb_path}")
    logger.debug(f"[kb_editor] discard '{mencion}' (no-op sobre JSON)")
