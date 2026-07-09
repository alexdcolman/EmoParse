# ══════════════════════════════════════════════════════════════════════════════
#  emoparse.app.revision_overlay
#
#  Capa de revisión humana: guarda las correcciones del analista en un archivo
#  aparte (overlay), sin tocar las bases del pipeline ni la KB.
#
#  El overlay es un parche que se aplica al leer: la vista efectiva es
#  merge(registro_DB, overlay). Los borrados son tombstones (reversibles); nada
#  se elimina físicamente. La escritura es atómica (tmp + os.replace) y con
#  backup .bak, de modo que un fallo a mitad de guardado no corrompe el archivo.
# ══════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

import json
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1


def default_overlay_path(db_path: Path) -> Path:
    """Ruta por defecto del overlay para un run.

    `<dir_del_sqlite>/<nombre_sqlite_sin_ext>/revision_overlay.json`.
    Agrupa las exportaciones por run y lleva el nombre del sqlite.
    """
    db_path = Path(db_path)
    return db_path.parent / db_path.stem / "revision_overlay.json"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _empty() -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "created_at": _now(),
        "updated_at": _now(),
        "discursos": {},
        "frases": {},
        "emociones": {},
        "emociones_nuevas": {},
        "actores_kb_propuestos": {},
    }


class OverlayCorruptError(RuntimeError):
    """El archivo de overlay existe pero no es JSON válido."""


class RevisionOverlay:
    """Almacén de correcciones del analista (write-through, atómico).

    Se instancia por render (carga fresca desde disco), se muta con un método,
    y cada método persiste. Como Streamlit recarga en cada rerun, no hay estado
    rancio que pueda pisar ediciones concurrentes de la propia UI.
    """

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self._data = self._load()

    # ── Carga / guardado ─────────────────────────────────────────────────────

    def _load(self) -> dict[str, Any]:
        if not self.path.exists():
            return _empty()
        try:
            with self.path.open(encoding="utf-8") as fh:
                data = json.load(fh)
        except (json.JSONDecodeError, OSError) as exc:
            # Nunca pisamos un archivo corrupto en silencio: avisamos.
            raise OverlayCorruptError(
                f"Overlay ilegible en {self.path}: {exc}"
            ) from exc
        if not isinstance(data, dict):
            raise OverlayCorruptError(f"Overlay con formato inesperado en {self.path}")
        # Garantizar todas las secciones (tolerante a versiones previas).
        base = _empty()
        for k, v in base.items():
            data.setdefault(k, v)
        return data

    def _save(self) -> None:
        """Escritura atómica con backup .bak."""
        self._data["updated_at"] = _now()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if self.path.exists():
            try:
                shutil.copy2(self.path, self.path.with_suffix(self.path.suffix + ".bak"))
            except OSError:
                pass
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        with tmp.open("w", encoding="utf-8") as fh:
            json.dump(self._data, fh, ensure_ascii=False, indent=2, default=str)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, self.path)

    # ── Helpers internos ─────────────────────────────────────────────────────

    @staticmethod
    def _si(idx: int | str) -> str:
        return str(int(idx))

    def _disc(self, codigo: str) -> dict[str, Any]:
        return self._data["discursos"].setdefault(
            codigo, {"overrides": {}, "confirmado": {}}
        )

    def _frase(self, codigo: str, unit_idx: int) -> dict[str, Any]:
        d = self._data["frases"].setdefault(codigo, {})
        return d.setdefault(
            self._si(unit_idx),
            {"actores_removidos": [], "actores_agregados": [],
             "confirmado_actores": False},
        )

    def _emo(self, codigo: str, frase_idx: int, emocion_idx: int) -> dict[str, Any]:
        c = self._data["emociones"].setdefault(codigo, {})
        f = c.setdefault(self._si(frase_idx), {})
        return f.setdefault(
            self._si(emocion_idx),
            {"deleted": False, "overrides": {}, "confirmado": {}},
        )

    # ── Discurso (header) ────────────────────────────────────────────────────

    def get_discurso(self, codigo: str) -> dict[str, Any]:
        return self._data["discursos"].get(codigo, {"overrides": {}, "confirmado": {}})

    def set_discurso_override(self, codigo: str, field: str, value: Any) -> None:
        self._disc(codigo)["overrides"][field] = value
        self._save()

    def clear_discurso_override(self, codigo: str, field: str) -> None:
        self._disc(codigo)["overrides"].pop(field, None)
        self._save()

    def confirm_discurso_field(self, codigo: str, field: str, value: bool = True) -> None:
        self._disc(codigo)["confirmado"][field] = bool(value)
        self._save()

    # ── Frase: correspondencia frase↔actor (NO toca la KB) ───────────────────

    def get_frase(self, codigo: str, unit_idx: int) -> dict[str, Any]:
        return self._data["frases"].get(codigo, {}).get(
            self._si(unit_idx),
            {"actores_removidos": [], "actores_agregados": [],
             "confirmado_actores": False},
        )

    def remove_actor(self, codigo: str, unit_idx: int, actor_key: str) -> None:
        fr = self._frase(codigo, unit_idx)
        if actor_key not in fr["actores_removidos"]:
            fr["actores_removidos"].append(actor_key)
        self._save()

    def restore_actor(self, codigo: str, unit_idx: int, actor_key: str) -> None:
        fr = self._frase(codigo, unit_idx)
        fr["actores_removidos"] = [a for a in fr["actores_removidos"] if a != actor_key]
        self._save()

    def add_actor(self, codigo: str, unit_idx: int, actor: dict[str, Any]) -> None:
        """Agrega una correspondencia frase↔actor (link a canónico o propuesto).

        `actor` lleva al menos {'actor_mencionado', 'actor_canonico'}. No escribe
        en la KB: si es un actor nuevo, su propuesta vive en el overlay.
        """
        self._frase(codigo, unit_idx)["actores_agregados"].append(actor)
        self._save()

    def remove_added_actor(self, codigo: str, unit_idx: int, pos: int) -> None:
        fr = self._frase(codigo, unit_idx)
        if 0 <= pos < len(fr["actores_agregados"]):
            fr["actores_agregados"].pop(pos)
            self._save()

    def confirm_frase_actores(self, codigo: str, unit_idx: int, value: bool = True) -> None:
        self._frase(codigo, unit_idx)["confirmado_actores"] = bool(value)
        self._save()

    # ── Emoción: edición / borrado / confirmación por campo ──────────────────

    def get_emocion(self, codigo: str, frase_idx: int, emocion_idx: int) -> dict[str, Any]:
        return (
            self._data["emociones"].get(codigo, {})
            .get(self._si(frase_idx), {})
            .get(self._si(emocion_idx),
                 {"deleted": False, "overrides": {}, "confirmado": {}})
        )

    def iter_emocion_overrides(self):
        """Itera (codigo, frase_idx, emocion_idx, overrides) de todas las emociones
        con ediciones en el overlay. Pensado para materializar (commit) las
        correcciones a la base sin acceder a la estructura interna."""
        for codigo, frases in self._data.get("emociones", {}).items():
            for fi, emos in frases.items():
                for ei, node in emos.items():
                    overrides = (node or {}).get("overrides", {})
                    if overrides:
                        yield codigo, int(fi), int(ei), dict(overrides)

    def is_emocion_deleted(self, codigo: str, frase_idx: int, emocion_idx: int) -> bool:
        return bool(self.get_emocion(codigo, frase_idx, emocion_idx).get("deleted"))

    def set_emocion_override(
        self, codigo: str, frase_idx: int, emocion_idx: int,
        field: str, value: Any,
    ) -> None:
        self._emo(codigo, frase_idx, emocion_idx)["overrides"][field] = value
        self._save()

    def set_emocion_override_path(
        self, codigo: str, frase_idx: int, emocion_idx: int,
        path: list[str], value: Any,
    ) -> None:
        """Setea un override anidado, p. ej. ['caracterizacion', 'foria']."""
        node = self._emo(codigo, frase_idx, emocion_idx)["overrides"]
        for p in path[:-1]:
            nxt = node.get(p)
            if not isinstance(nxt, dict):
                nxt = {}
                node[p] = nxt
            node = nxt
        node[path[-1]] = value
        self._save()

    def clear_emocion_override_path(
        self, codigo: str, frase_idx: int, emocion_idx: int, path: list[str],
    ) -> None:
        node = self._emo(codigo, frase_idx, emocion_idx)["overrides"]
        for p in path[:-1]:
            node = node.get(p)
            if not isinstance(node, dict):
                return
        node.pop(path[-1], None)
        self._save()

    def clear_emocion_override(
        self, codigo: str, frase_idx: int, emocion_idx: int, field: str,
    ) -> None:
        self._emo(codigo, frase_idx, emocion_idx)["overrides"].pop(field, None)
        self._save()

    def confirm_emocion_field(
        self, codigo: str, frase_idx: int, emocion_idx: int,
        field: str, value: bool = True,
    ) -> None:
        self._emo(codigo, frase_idx, emocion_idx)["confirmado"][field] = bool(value)
        self._save()

    # ── Sugerencias del juez (aceptar / rechazar por campo) ──────────────────

    def get_suggestion_states(
        self, codigo: str, frase_idx: int, emocion_idx: int,
    ) -> dict[str, str]:
        """Estado de cada sugerencia por `campo`: 'accepted' | 'rejected'."""
        return dict(
            self.get_emocion(codigo, frase_idx, emocion_idx).get("sugerencias", {})
        )

    def set_suggestion_state(
        self, codigo: str, frase_idx: int, emocion_idx: int,
        campo: str, state: str,
    ) -> None:
        """Registra el estado de una sugerencia ('accepted' | 'rejected').

        Aceptar/rechazar solo deja constancia; la aplicación del valor sugerido
        (cuando se acepta) se hace aparte vía `set_emocion_override_path`, de
        modo que el analista pueda luego editar libremente el override.
        """
        self._emo(codigo, frase_idx, emocion_idx).setdefault(
            "sugerencias", {}
        )[campo] = state
        self._save()

    def clear_suggestion_state(
        self, codigo: str, frase_idx: int, emocion_idx: int, campo: str,
    ) -> None:
        self._emo(codigo, frase_idx, emocion_idx).get("sugerencias", {}).pop(
            campo, None
        )
        self._save()

    def delete_emocion(self, codigo: str, frase_idx: int, emocion_idx: int) -> None:
        self._emo(codigo, frase_idx, emocion_idx)["deleted"] = True
        self._save()

    def restore_emocion(self, codigo: str, frase_idx: int, emocion_idx: int) -> None:
        self._emo(codigo, frase_idx, emocion_idx)["deleted"] = False
        self._save()

    # ── Emociones nuevas (agregadas a mano) ──────────────────────────────────

    def list_new_emociones(self, codigo: str, frase_idx: int) -> list[dict[str, Any]]:
        return list(
            self._data["emociones_nuevas"].get(codigo, {}).get(self._si(frase_idx), [])
        )

    def add_emocion(self, codigo: str, frase_idx: int, emocion: dict[str, Any]) -> None:
        c = self._data["emociones_nuevas"].setdefault(codigo, {})
        c.setdefault(self._si(frase_idx), []).append(emocion)
        self._save()

    def remove_new_emocion(self, codigo: str, frase_idx: int, pos: int) -> None:
        lst = self._data["emociones_nuevas"].get(codigo, {}).get(self._si(frase_idx), [])
        if 0 <= pos < len(lst):
            lst.pop(pos)
            self._save()

    # ── Actores nuevos propuestos (overlay, NO se escriben en la KB acá) ─────

    def list_proposed_actors(self) -> dict[str, Any]:
        return dict(self._data["actores_kb_propuestos"])

    def propose_actor(
        self, canonical_id: str, display_name: str, tipo: str,
        existing_kb_ids: set[str],
    ) -> None:
        """Registra un actor nuevo propuesto. Nunca pisa uno existente.

        Lanza ValueError si el `canonical_id` ya existe en la KB o ya fue
        propuesto: garantía de no-sobrescritura.
        """
        cid = (canonical_id or "").strip()
        if not cid:
            raise ValueError("canonical_id vacío.")
        if cid in existing_kb_ids:
            raise ValueError(f"Ya existe un actor '{cid}' en la KB.")
        if cid in self._data["actores_kb_propuestos"]:
            raise ValueError(f"El actor '{cid}' ya fue propuesto.")
        self._data["actores_kb_propuestos"][cid] = {
            "display_name": (display_name or cid).strip(),
            "tipo": tipo,
            "propuesto_at": _now(),
        }
        self._save()

    # ── Aplicación efectiva (lectura) ────────────────────────────────────────

    def effective_emocion(
        self, codigo: str, frase_idx: int, emocion_idx: int,
        db_record: dict[str, Any],
    ) -> dict[str, Any]:
        """Devuelve el registro de emoción con los overrides aplicados.

        Hace deep-merge de overrides anidados (p. ej. {'caracterizacion':
        {'foria': ...}}). No muta `db_record`.
        """
        ov = self.get_emocion(codigo, frase_idx, emocion_idx)
        eff = json.loads(json.dumps(db_record, default=str))
        eff = _deep_merge(eff, ov.get("overrides", {}))
        eff["_deleted"] = bool(ov.get("deleted"))
        eff["_confirmado"] = dict(ov.get("confirmado", {}))
        return eff


def _deep_merge(base: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
    """Merge recursivo: las claves de `patch` pisan las de `base`."""
    for k, v in patch.items():
        if isinstance(v, dict) and isinstance(base.get(k), dict):
            base[k] = _deep_merge(base[k], v)
        else:
            base[k] = v
    return base
