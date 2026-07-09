# ══════════════════════════════════════════════════════════════════════════════
#  emoparse.app.actions
#
#  Capa de escritura de la UI Streamlit.
#
#  Expone funciones puras para la revisión: commit del overlay de
#  experienciadores a la base, gestión de vínculos marca↔referente y promoción
#  de referentes aceptados a la KB.
# ══════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

from pathlib import Path
from typing import Any

from loguru import logger

from emoparse.app.revision_overlay import (
    OverlayCorruptError,
    RevisionOverlay,
    default_overlay_path,
)
from emoparse.storage.db import Database
from emoparse.storage.discursos import DiscursosRepository
from emoparse.storage.emociones import EmocionesRepository
from emoparse.storage.judgments import JudgmentsRepository
from emoparse.storage.menciones import MencionesRepository
from emoparse.storage.runs import RunsRepository


def _commit_canon_value(value: object) -> str | None:
    """Normaliza el valor del overlay (str o lista) a un único string para la
    columna `experienciador_canonico`. Lista → unida por '; '. Vacío → None."""
    if isinstance(value, (list, tuple)):
        joined = "; ".join(str(x).strip() for x in value if str(x).strip())
        return joined or None
    s = str(value).strip() if value is not None else ""
    return s or None


def commit_experiencers_overlay(
    db_path: Path,
    *,
    only_codigo: str | None = None,
) -> dict:
    """Materializa el experienciador revisado (overlay) a `emociones` y fuerza
    el recálculo downstream de lo que cambió.

    Para cada emoción con override de ``experienciador_canonico`` en el overlay
    de revisión, escribe el valor por (codigo, frase, emoción) en la base; si el
    valor cambió respecto del que había, anula sus payloads de characterizer y
    actants para que se recalculen. Idempotente. Devuelve
    {emociones, changed, invalidated}.

    Es el puente que hace que la revisión humana tenga efectos downstream:
    characterizer/actants/judge prefieren `experienciador_canonico` cuando existe.
    El overlay sigue siendo la fuente durable; se puede re-commitear tras un
    re-run de upstream.
    """
    if not db_path.is_file():
        raise FileNotFoundError(f"DB no encontrada: {db_path}")
    db = Database(db_path)
    if not db.table_exists("emociones"):
        raise RuntimeError("DB sin tabla emociones.")
    try:
        ov = RevisionOverlay(default_overlay_path(db_path))
    except OverlayCorruptError as e:
        raise RuntimeError(f"Overlay ilegible: {e}") from e

    emo = EmocionesRepository(db)
    judg = JudgmentsRepository(db) if db.table_exists("judgments") else None
    version = _run_prompt_version(db)
    n_emos = n_changed = n_invalidated = n_judge = 0
    for codigo, frase_idx, emocion_idx, overrides in ov.iter_emocion_overrides():
        if only_codigo is not None and codigo != only_codigo:
            continue
        if "experienciador_canonico" not in overrides:
            continue
        n_emos += 1
        value = _commit_canon_value(overrides.get("experienciador_canonico"))
        changed = emo.set_experienciador_canonico_at(
            codigo, frase_idx, emocion_idx, value, version=version
        )
        if changed:
            n_changed += 1
            emo.invalidate_downstream(codigo, frase_idx, emocion_idx)
            n_invalidated += 1
            if judg is not None and judg.invalidate(codigo, frase_idx, emocion_idx):
                n_judge += 1
    logger.info(
        f"[app.actions] commit experienciadores (overlay→base): "
        f"{n_emos} emociones, {n_changed} cambiadas, "
        f"{n_invalidated} invalidadas (characterizer/actants), "
        f"{n_judge} juicios invalidados."
    )
    return {
        "emociones": n_emos,
        "changed": n_changed,
        "invalidated": n_invalidated,
        "judge_invalidated": n_judge,
    }


def _run_prompt_version(db: Database) -> str | None:
    """Versión de prompt del run (provenance del canónico)."""
    try:
        ctx = RunsRepository(db).get_run()
    except Exception:
        return None
    return ctx.versions.prompt if ctx is not None else None


def emocion_set_experiencer_at(
    db_path: Path,
    codigo: str,
    frase_idx: int,
    emocion_idx: int,
    canonical_id: str | None,
) -> bool:
    """Fija (o limpia) el experienciador canónico de UNA emoción puntual.

    Permite desarticular frases con varias emociones que comparten la marca de
    experienciador: se atribuye el canónico solo a la emoción elegida, sin tocar
    el vínculo compartido de la mención. `canonical_id` vacío/None limpia la
    atribución (vuelve a resolverse por marca). Devuelve True si cambió.

    Al cambiar, invalida characterizer/actants (y el juicio) de esa emoción para
    que se recalculen con el experienciador correcto.
    """
    db = Database(Path(db_path))
    if not db.table_exists("emociones"):
        raise RuntimeError("DB sin tabla emociones.")
    RunsRepository(db).ensure_migrations()
    emo = EmocionesRepository(db)
    judg = JudgmentsRepository(db) if db.table_exists("judgments") else None
    version = _run_prompt_version(db)
    value = (canonical_id or "").strip() or None
    changed = emo.set_experienciador_canonico_at(
        codigo, frase_idx, emocion_idx, value, version=version
    )
    if changed:
        emo.invalidate_downstream(codigo, frase_idx, emocion_idx)
        if judg is not None:
            judg.invalidate(codigo, frase_idx, emocion_idx)
    return changed


def emocion_set_fuente_at(
    db_path: Path,
    codigo: str,
    frase_idx: int,
    emocion_idx: int,
    canonical_id: str | None,
) -> bool:
    """Fija (o limpia) la fuente canónica de UNA emoción puntual.

    Permite desarticular frases con varias emociones que comparten la marca de
    fuente: se atribuye el canónico solo a la emoción elegida, sin tocar el
    vínculo compartido de la mención. `canonical_id` vacío/None limpia la
    atribución (vuelve a resolverse por marca). Devuelve True si cambió.

    La fuente canónica es una etiqueta de referente (no la consume ningún stage
    LLM), por lo que no dispara recálculo downstream."""
    db = Database(Path(db_path))
    if not db.table_exists("emociones"):
        raise RuntimeError("DB sin tabla emociones.")
    RunsRepository(db).ensure_migrations()
    emo = EmocionesRepository(db)
    version = _run_prompt_version(db)
    value = (canonical_id or "").strip() or None
    return emo.set_fuente_canonico_at(
        codigo, frase_idx, emocion_idx, value, version=version
    )


# ══════════════════════════════════════════════════════════════════════════════
#  Edición directa de la KB de actores (revisión manual desde el dashboard)
# ══════════════════════════════════════════════════════════════════════════════

def _cleanup_kb_if_orphan(db_path: Path, canonical_id: str) -> None:
    """Si el canónico ya no tiene vínculos aceptados en la DB, lo elimina de la KB."""
    db = Database(Path(db_path))
    row = db.execute(
        "SELECT COUNT(*) AS n FROM mencion_canonico "
        "WHERE canonical_id = ? AND status = 'accepted'",
        (canonical_id,),
    ).fetchone()
    if row and int(row["n"]) == 0:
        remove_referente_from_kb(canonical_id)


def mencion_accept(db_path: Path, mencion_id: int, canonical_id: str) -> None:
    """Acepta un vínculo marca↔canónico."""
    MencionesRepository(Database(Path(db_path))).set_link_status(
        mencion_id, canonical_id, "accepted"
    )


def mencion_reject(db_path: Path, mencion_id: int, canonical_id: str) -> None:
    """Rechaza un vínculo marca↔canónico y limpia la KB si el canónico queda huérfano."""
    MencionesRepository(Database(Path(db_path))).set_link_status(
        mencion_id, canonical_id, "rejected"
    )
    _cleanup_kb_if_orphan(db_path, canonical_id)


def mencion_add_link(db_path: Path, mencion_id: int, canonical_id: str) -> None:
    """Agrega un vínculo marca↔canónico creado por el analista (aceptado)."""
    MencionesRepository(Database(Path(db_path))).add_human_link(
        mencion_id, canonical_id
    )


def mencion_remove_link(db_path: Path, mencion_id: int, canonical_id: str) -> None:
    """Elimina un vínculo marca↔canónico y limpia la KB si el canónico queda huérfano."""
    MencionesRepository(Database(Path(db_path))).remove_link(
        mencion_id, canonical_id
    )
    _cleanup_kb_if_orphan(db_path, canonical_id)


def bulk_set_link_status(
    db_path: Path, pairs: list[tuple[int, str]], status: str
) -> int:
    """Acepta/rechaza en lote (status='accepted'|'rejected'). Limpia KB huérfana
    solo en rechazos masivos. Devuelve cuántos vínculos se afectaron."""
    repo = MencionesRepository(Database(Path(db_path)))
    n = repo.bulk_set_status(pairs, status)
    if status == "rejected":
        for cid in {c for _, c in pairs}:
            _cleanup_kb_if_orphan(db_path, cid)
    return n


def mencion_set_modalidad(
    db_path: Path,
    mencion_id: int,
    canonical_id: str,
    modalidad: str | None,
    naturaleza: str | None,
) -> None:
    """Corrige a mano la modalidad/naturaleza de un vínculo (origin='human')."""
    MencionesRepository(Database(Path(db_path))).set_modalidad(
        mencion_id, canonical_id, modalidad or None, naturaleza or None, "human"
    )


# ══════════════════════════════════════════════════════════════════════════════
#  Promoción de referentes aceptados → referentes_kb.json
# ══════════════════════════════════════════════════════════════════════════════

import json
import os


def _default_referentes_kb_path() -> Path:
    """Ruta por defecto del referentes_kb (configurable por entorno)."""
    base = os.environ.get("EMOPARSE_KNOWLEDGE_DIR", "knowledge")
    return Path(base) / "referentes_kb.json"


def _atomic_write_json(path: Path, data: dict) -> None:
    """Escribe JSON de forma atómica, con backup .bak del archivo previo."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_file():
        path.with_suffix(path.suffix + ".bak").write_text(
            path.read_text(encoding="utf-8"), encoding="utf-8"
        )
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    tmp.replace(path)


def promote_referentes(
    db_path: Path, kb_path: Path | None = None
) -> dict[str, int]:
    """Materializa los referentes aceptados del run en `referentes_kb.json`.

    Agrega los canónicos nuevos, completa `display_name` si estaba vacío, y
    elimina de la KB los canónicos que ya no tienen ningún vínculo aceptado
    en este run (sincronización completa: altas y bajas).
    Los campos editados a mano (tipo, notas) se respetan en los canónicos
    que permanecen.
    Devuelve conteos {referentes_total, added, updated, removed}.
    """
    repo = MencionesRepository(Database(Path(db_path)))
    refs = repo.accepted_referentes()
    accepted_ids = {r["canonical_id"] for r in refs}
    kb_path = Path(kb_path) if kb_path else _default_referentes_kb_path()

    data: dict = {"version": "v1", "referentes": {}}
    if kb_path.is_file():
        try:
            loaded = json.loads(kb_path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                data = loaded
        except json.JSONDecodeError:
            logger.warning("[promote_referentes] referentes_kb ilegible; se recrea.")
    referentes = data.setdefault("referentes", {})

    added = updated = removed = 0

    # Bajas: eliminar canónicos que ya no tienen vínculos aceptados
    for cid in list(referentes.keys()):
        if cid not in accepted_ids:
            del referentes[cid]
            removed += 1
            logger.info(f"[promote_referentes] eliminado de KB: {cid!r}")

    # Altas y actualizaciones
    for r in refs:
        cid = r["canonical_id"]
        entry = referentes.get(cid)
        if entry is None:
            referentes[cid] = {
                "display_name": r["display_name"],
                "clase": r["clase"],
                "tipo": "",
                "notas": "",
            }
            added += 1
        else:
            # Actualizar clase siempre (se recalcula desde vínculos)
            entry["clase"] = r["clase"]
            # Completar display_name solo si estaba vacío
            if not entry.get("display_name"):
                entry["display_name"] = r["display_name"]
                updated += 1

    _atomic_write_json(kb_path, data)
    return {
        "referentes_total": len(referentes),
        "added": added,
        "updated": updated,
        "removed": removed,
    }


def remove_referente_from_kb(
    canonical_id: str, kb_path: Path | None = None
) -> bool:
    """Elimina un referente canónico de `referentes_kb.json`.

    No toca la DB del run: solo elimina la entrada de la KB.
    Devuelve True si existía y fue eliminado, False si no estaba.
    """
    kb_path = Path(kb_path) if kb_path else _default_referentes_kb_path()
    if not kb_path.is_file():
        return False
    try:
        data = json.loads(kb_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return False
    referentes = data.get("referentes", {})
    if canonical_id not in referentes:
        return False
    del referentes[canonical_id]
    _atomic_write_json(kb_path, data)
    logger.info(f"[remove_referente_from_kb] eliminado: {canonical_id!r}")
    return True


def rename_canonical(
    db_path: Path,
    old_id: str,
    new_id: str,
    kb_path: Path | None = None,
) -> dict[str, int]:
    """Renombra un canónico: actualiza `mencion_canonico` en la DB y la KB.

    En la DB: reemplaza `canonical_id = old_id` por `new_id` en todas las
    filas de `mencion_canonico`. Si `new_id` ya existe, las filas se fusionan
    (ON CONFLICT IGNORE para no duplicar; las que colisionan se eliminan).
    En la KB: mueve la entrada preservando tipo/notas; si `new_id` ya existía
    en KB, solo elimina `old_id` (respeta la entrada existente de `new_id`).
    Devuelve {rows_updated, kb_renamed}.
    """
    from emoparse.core.text import slugify

    new_id = slugify(new_id)
    old_id = slugify(old_id)
    if not new_id or not old_id or new_id == old_id:
        return {"rows_updated": 0, "kb_renamed": 0}

    db = Database(Path(db_path))
    rows_updated = 0
    with db.transaction() as cur:
        # Filas que colisionarían (old→new ya existe): eliminarlas primero
        cur.execute(
            "DELETE FROM mencion_canonico "
            "WHERE canonical_id = ? AND mencion_id IN ("
            "  SELECT mencion_id FROM mencion_canonico WHERE canonical_id = ?"
            ")",
            (old_id, new_id),
        )
        # Renombrar el resto
        cur.execute(
            "UPDATE mencion_canonico SET canonical_id = ? WHERE canonical_id = ?",
            (new_id, old_id),
        )
        rows_updated = cur.rowcount

    # Actualizar KB
    kb_path = Path(kb_path) if kb_path else _default_referentes_kb_path()
    kb_renamed = 0
    if kb_path.is_file():
        try:
            data = json.loads(kb_path.read_text(encoding="utf-8"))
            referentes = data.get("referentes", {})
            if old_id in referentes:
                old_entry = referentes.pop(old_id)
                if new_id not in referentes:
                    referentes[new_id] = old_entry
                    kb_renamed = 1
                # Si new_id ya existía, simplemente descartamos old_entry
                _atomic_write_json(kb_path, data)
        except (json.JSONDecodeError, OSError):
            pass

    logger.info(
        f"[rename_canonical] {old_id!r} → {new_id!r}: "
        f"{rows_updated} filas DB, KB={'renombrado' if kb_renamed else 'fusionado'}"
    )
    return {"rows_updated": rows_updated, "kb_renamed": kb_renamed}


# ══════════════════════════════════════════════════════════════════════════════
#  Lectura y edición directa de entradas de la KB
# ══════════════════════════════════════════════════════════════════════════════

def get_kb_entry(
    canonical_id: str, kb_path: Path | None = None
) -> dict | None:
    """Devuelve la entrada de un canónico en la KB, o None si no existe."""
    kb_path = Path(kb_path) if kb_path else _default_referentes_kb_path()
    if not kb_path.is_file():
        return None
    try:
        data = json.loads(kb_path.read_text(encoding="utf-8"))
        return data.get("referentes", {}).get(canonical_id)
    except (json.JSONDecodeError, OSError):
        return None


def update_kb_entry(
    canonical_id: str,
    *,
    display_name: str | None = None,
    tipo: str | None = None,
    notas: str | None = None,
    kb_path: Path | None = None,
) -> bool:
    """Actualiza campos editables de un canónico en la KB.

    Solo escribe los campos que se pasen explícitamente (None = no tocar).
    Si el canónico no existe en la KB, lo crea con valores vacíos.
    Devuelve True si escribió algo.
    """
    kb_path = Path(kb_path) if kb_path else _default_referentes_kb_path()
    data: dict = {"version": "v1", "referentes": {}}
    if kb_path.is_file():
        try:
            loaded = json.loads(kb_path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                data = loaded
        except (json.JSONDecodeError, OSError):
            pass
    referentes = data.setdefault("referentes", {})
    entry = referentes.setdefault(canonical_id, {
        "display_name": "", "clase": "", "tipo": "", "notas": ""
    })
    changed = False
    if display_name is not None and entry.get("display_name") != display_name:
        entry["display_name"] = display_name
        changed = True
    if tipo is not None and entry.get("tipo") != tipo:
        entry["tipo"] = tipo
        changed = True
    if notas is not None and entry.get("notas") != notas:
        entry["notas"] = notas
        changed = True
    if changed:
        _atomic_write_json(kb_path, data)
        logger.info(f"[update_kb_entry] {canonical_id!r} actualizado.")
    return changed


def delete_canonical(
    db_path: Path,
    canonical_id: str,
    kb_path: Path | None = None,
) -> dict[str, int]:
    """Elimina un canónico completamente: borra todos sus vínculos en la DB y
    su entrada en la KB.

    NO elimina las menciones en sí (la marca discursiva queda, sin vínculo).
    Devuelve {rows_deleted, kb_removed}.
    """
    db = Database(Path(db_path))
    with db.transaction() as cur:
        cur.execute(
            "DELETE FROM mencion_canonico WHERE canonical_id = ?",
            (canonical_id,),
        )
        rows_deleted = cur.rowcount

    kb_removed = 1 if remove_referente_from_kb(canonical_id, kb_path) else 0
    logger.info(
        f"[delete_canonical] {canonical_id!r}: "
        f"{rows_deleted} vínculos eliminados, KB={'sí' if kb_removed else 'no estaba'}."
    )
    return {"rows_deleted": rows_deleted, "kb_removed": kb_removed}


# ══════════════════════════════════════════════════════════════════════════════
#  Merge de canónicos
# ══════════════════════════════════════════════════════════════════════════════

def merge_canonicals(
    db_path: Path,
    src_id: str,
    dst_id: str,
    kb_path: Path | None = None,
) -> dict[str, int]:
    """Fusiona el canónico `src_id` dentro de `dst_id` (queda `dst_id`).

    Repunta en la DB todos los vínculos marca↔`src_id` a `dst_id`, **preservando
    el estado de cada vínculo** (un `rejected` sigue `rejected`, un `proposed`
    sigue `proposed`): la fusión no acepta nada por su cuenta. Si la marca ya
    estaba ligada a `dst_id`, descarta el vínculo duplicado de `src`. Mueve sus
    semas. Elimina `src_id` de la KB. Devuelve {links_merged, semas_merged}.
    """
    from emoparse.core.text import canonical_slug

    src_id = canonical_slug(src_id)
    dst_id = canonical_slug(dst_id)
    if not src_id or not dst_id or src_id == dst_id:
        return {"links_merged": 0, "semas_merged": 0}

    db = Database(Path(db_path))
    with db.transaction() as cur:
        # Vínculos que colisionarían (marca ya ligada a dst): eliminar el de src.
        cur.execute(
            "DELETE FROM mencion_canonico "
            "WHERE canonical_id = ? AND mencion_id IN ("
            "  SELECT mencion_id FROM mencion_canonico WHERE canonical_id = ?"
            ")",
            (src_id, dst_id),
        )
        # Repuntar el resto a dst SIN tocar el status (se conserva tal cual).
        cur.execute(
            "UPDATE mencion_canonico "
            "SET canonical_id = ?, origin = 'human' "
            "WHERE canonical_id = ?",
            (dst_id, src_id),
        )
        links_merged = cur.rowcount
        # Mover semas de src a dst (sin pisar los ya presentes en dst).
        cur.execute(
            "INSERT OR IGNORE INTO canonico_semas "
            "(canonical_id, sema, status, origin) "
            "SELECT ?, sema, status, origin FROM canonico_semas WHERE canonical_id = ?",
            (dst_id, src_id),
        )
        semas_merged = cur.rowcount
        cur.execute(
            "DELETE FROM canonico_semas WHERE canonical_id = ?", (src_id,)
        )

    remove_referente_from_kb(src_id, kb_path)
    logger.info(
        f"[merge_canonicals] {src_id!r} → {dst_id!r}: "
        f"{links_merged} vínculos, {semas_merged} semas."
    )
    return {"links_merged": links_merged, "semas_merged": semas_merged}


# ══════════════════════════════════════════════════════════════════════════════
#  Semas de referentes (tab Referentes)
# ══════════════════════════════════════════════════════════════════════════════

def referente_set_sema(
    db_path: Path, canonical_id: str, sema: str, status: str = "accepted"
) -> None:
    """Agrega/acepta/rechaza un sema de un referente (decisión humana)."""
    MencionesRepository(Database(Path(db_path))).set_sema(
        canonical_id, sema, status
    )


def referente_remove_sema(db_path: Path, canonical_id: str, sema: str) -> None:
    """Elimina un sema de un referente."""
    MencionesRepository(Database(Path(db_path))).remove_sema(canonical_id, sema)


# ══════════════════════════════════════════════════════════════════════════════
#  Deixis (tab Deixis)
# ══════════════════════════════════════════════════════════════════════════════

def deixis_accept(db_path: Path, mencion_id: int, canonical_id: str) -> None:
    """Acepta un referente deíctico para una marca (sobreescribe el automático)."""
    MencionesRepository(Database(Path(db_path))).accept_deixis_link(
        mencion_id, canonical_id
    )


def deixis_reject(db_path: Path, mencion_id: int, canonical_id: str) -> None:
    """Rechaza un referente deíctico propuesto para una marca."""
    MencionesRepository(Database(Path(db_path))).reject_deixis_link(
        mencion_id, canonical_id
    )


def deixis_add(
    db_path: Path, mencion_id: int, canonical_id: str, deixis_tipo: str
) -> None:
    """Agrega a mano un referente deíctico (del discurso) a una marca."""
    MencionesRepository(Database(Path(db_path))).add_deixis_referente(
        mencion_id, canonical_id, deixis_tipo
    )


# ══════════════════════════════════════════════════════════════════════════════
#  Enunciación (tab Enunciación)
# ══════════════════════════════════════════════════════════════════════════════

def _names_from_json(value: Any, key: str) -> list[str]:
    """Nombres de una sublista del payload (JSON string) por clave."""
    try:
        items = json.loads(value) if isinstance(value, str) else value
    except (json.JSONDecodeError, TypeError):
        return []
    if not isinstance(items, list):
        return []
    out = []
    for it in items:
        if isinstance(it, dict):
            nom = str(it.get(key, "") or "").strip()
            if nom:
                out.append(nom)
    return out


def save_enunciation(db_path: Path, codigo: str, payload: dict) -> int:
    """Guarda la estructura enunciativa editada y propaga a la deixis.

    `payload` es el enunciation_payload completo (con enunciatarios/auditorio/
    colectivos serializados como JSON, igual que el stage). Tras guardar, ajusta
    los vínculos deícticos del discurso para que apunten a los referentes
    concretos vigentes:
      - enunciador (siempre único): todos los vínculos de tipo `enunciador` del
        discurso pasan a ese referente.
      - auditorio / colectivo: si hay exactamente uno, todos los vínculos de ese
        tipo pasan a él; si hay varios, solo se aplica el renombre inequívoco
        (uno desaparece y uno aparece) comparando contra el payload anterior.
    Devuelve cuántos vínculos deícticos se repuntaron.
    """
    from emoparse.core.text import canonical_slug

    db = Database(Path(db_path))
    d_repo = DiscursosRepository(db)
    old_payload = d_repo.get_payload(codigo, "enunciation") or {}
    d_repo.set_payload(codigo, "enunciation", payload)

    m = MencionesRepository(db)
    moved = 0

    enunciador = str(payload.get("enunciador") or "").strip()
    if enunciador:
        moved += m.repoint_deixis_in_discurso(codigo, "enunciador", enunciador)

    for tipo, key in (("auditorio", "actor"),
                      ("colectivo_identificacion", "nombre")):
        new_key = "colectivos_identificacion" if tipo == "colectivo_identificacion" else tipo
        new_names = _names_from_json(payload.get(new_key), key)
        new_slugs = {canonical_slug(n) for n in new_names if canonical_slug(n)}
        if len(new_slugs) == 1:
            moved += m.repoint_deixis_in_discurso(codigo, tipo, next(iter(new_slugs)))
        elif len(new_slugs) > 1:
            old_names = _names_from_json(old_payload.get(new_key), key)
            old_slugs = {canonical_slug(n) for n in old_names if canonical_slug(n)}
            gone, added = old_slugs - new_slugs, new_slugs - old_slugs
            if len(gone) == 1 and len(added) == 1:
                moved += m.repoint_deixis_in_discurso(
                    codigo, tipo, next(iter(added)), next(iter(gone))
                )

    logger.info(f"[save_enunciation] {codigo}: {moved} vínculos deícticos repuntados.")
    return moved
