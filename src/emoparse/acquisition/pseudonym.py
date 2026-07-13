# ══════════════════════════════════════════════════════════════════════════════
#  emoparse.acquisition.pseudonym
#
#  Seudonimización de handles en corpus de posts.
#
#  Reemplaza cada handle por un alias estable (`u_<hash>`) derivado de una sal
#  local, de modo que el corpus exportable no exponga cuentas identificables
#  pero conserve la estructura (mismo autor → mismo alias, hilos y redes
#  intactos). La sal vive en un archivo aparte junto al corpus: quien tenga la
#  sal puede re-derivar los alias; quien no, no puede revertirlos.
#
#  Límites (documentados también en el README del paquete): la seudonimización
#  cubre los handles conocidos por el registro (autor y menciones textuales a
#  handles ya vistos); nombres propios dentro del texto libre, fotos de perfil
#  o datos citados en el contenido NO se alteran. Para publicación de corpus,
#  esto es una capa necesaria pero no suficiente.
# ══════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

import hashlib
import re
import secrets
from dataclasses import replace
from pathlib import Path

from emoparse.acquisition.post_record import PostRecord

#: Longitud del alias (dígitos hex del hash).
_ALIAS_LEN = 12


class Pseudonymizer:
    """Seudonimiza handles con una sal persistida.

    La sal se crea la primera vez y se guarda en `salt_path` (con permisos
    restringidos). Corridas posteriores sobre el mismo corpus producen los
    mismos alias, lo que mantiene consistente un corpus construido en varias
    sesiones.
    """

    def __init__(self, salt_path: Path | str) -> None:
        self._salt_path = Path(salt_path).expanduser().resolve()
        self._salt = self._load_or_create_salt()
        #: Handles vistos hasta ahora (para reescribir menciones en el texto).
        self._known_handles: set[str] = set()

    def _load_or_create_salt(self) -> str:
        if self._salt_path.is_file():
            return self._salt_path.read_text(encoding="utf-8").strip()
        salt = secrets.token_hex(16)
        self._salt_path.parent.mkdir(parents=True, exist_ok=True)
        self._salt_path.write_text(salt + "\n", encoding="utf-8")
        try:
            self._salt_path.chmod(0o600)
        except OSError:
            pass  # filesystems sin permisos POSIX (p. ej. algunos mounts)
        return salt

    def alias(self, handle: str) -> str:
        """Alias estable para un handle (insensible a mayúsculas y '@')."""
        norm = handle.lstrip("@").strip().lower()
        digest = hashlib.sha256(
            (self._salt + ":" + norm).encode("utf-8")
        ).hexdigest()
        return f"u_{digest[:_ALIAS_LEN]}"

    def apply(self, record: PostRecord) -> PostRecord:
        """Devuelve una copia del post con handles seudonimizados.

        Reemplaza el handle del autor, borra el display name y la bio, y
        reescribe en el texto las @menciones a handles conocidos (el autor y
        todo handle visto en posts previos de la sesión).
        """
        self._known_handles.add(record.autor_handle.lstrip("@").lower())
        texto = self._rewrite_text(record.texto)
        return replace(
            record,
            autor_handle=self.alias(record.autor_handle),
            autor_display=None,
            autor_bio=None,
            url=None,
            texto=texto,
            raw=None,
        )

    def _rewrite_text(self, texto: str) -> str:
        """Reescribe @menciones a handles conocidos dentro del texto."""
        def _sub(match: re.Match[str]) -> str:
            handle = match.group(1)
            if handle.lower() in self._known_handles:
                return "@" + self.alias(handle)
            return match.group(0)

        return re.sub(r"@([A-Za-z0-9_](?:[A-Za-z0-9_.\-]*[A-Za-z0-9_])?)", _sub, texto)
