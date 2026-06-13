# ══════════════════════════════════════════════════════════════════════════════
#  emoparse.triage.discovery_grouping
#
#  Agrupamiento (sin LLM) de discoveries de actores por canónico sugerido.
#
#  Agrupa las menciones que parecen referirse al mismo actor nuevo, para
#  facilitar la revisión por parte del analista.
# ══════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

_KB_TIPOS = ("individuo", "institucion", "colectivo", "desconocido")

_TIPO_SINONIMOS = {
    "humano_individual": "individuo",
    "individual": "individuo",
    "persona": "individuo",
    "humano": "individuo",
    "institucional": "institucion",
    "institucion": "institucion",
    "organizacion": "institucion",
    "grupo": "colectivo",
    "colectivo": "colectivo",
}


@dataclass
class DiscoveryGroup:
    """Un grupo de discoveries que refieren al mismo actor nuevo.

    `members[0]` es el representante (va como promote); el resto van como
    merge hacia `canonical_id`.
    """

    canonical_id: str
    display_name: str
    tipo: str
    members: list[dict] = field(default_factory=list)

    @property
    def member_ids(self) -> list[int]:
        return [int(m["id"]) for m in self.members]

    @property
    def n_members(self) -> int:
        return len(self.members)


def _strip_accents(s: str) -> str:
    return "".join(
        c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c)
    )


def slugify(s: str) -> str:
    """Slug ASCII apto para canonical_id (minúsculas, dígitos, guiones bajos)."""
    s = _strip_accents(str(s or "")).lower()
    s = re.sub(r"[^a-z0-9]+", "_", s).strip("_")
    s = re.sub(r"_+", "_", s)
    if not s:
        return ""
    if not s[0].isalpha():
        s = "a_" + s
    return s[:64]


def _kb_tipo(s: str | None) -> str:
    """Mapea un tipo sugerido al vocabulario de la KB, o '' si está vacío."""
    if not s:
        return ""
    key = _strip_accents(str(s)).lower().strip()
    if key in _KB_TIPOS:
        return key
    return _TIPO_SINONIMOS.get(key, "desconocido")


def _most_common(seq: list[str]) -> str:
    """Valor más frecuente; en empate, el que aparece primero. '' si vacío."""
    counts: dict[str, int] = {}
    for x in seq:
        counts[x] = counts.get(x, 0) + 1
    best, best_n = "", -1
    for x in seq:  # recorrido en orden: el primer máximo gana
        if counts[x] > best_n:
            best, best_n = x, counts[x]
    return best


def _group_key(d: dict) -> str:
    """Clave de agrupamiento: slug del canónico sugerido, con fallbacks."""
    raw = (d.get("canonical_id_sugerido") or "").strip()
    if raw:
        return slugify(raw)
    dn = (d.get("display_name_sugerido") or "").strip()
    if dn:
        return slugify(dn)
    return slugify(d.get("actor_mencionado") or "")


def _pick_display_name(members: list[dict]) -> str:
    names = [
        str(m.get("display_name_sugerido")).strip()
        for m in members
        if (m.get("display_name_sugerido") or "").strip()
    ]
    if names:
        return _most_common(names)
    mentions = [str(m.get("actor_mencionado") or "") for m in members]
    mentions = [m for m in mentions if m]
    # Sin sugerencia, la mención más larga suele ser la forma más completa.
    return max(mentions, key=len) if mentions else ""


def _pick_tipo(members: list[dict]) -> str:
    tipos = [_kb_tipo(m.get("tipo_sugerido")) for m in members]
    tipos = [t for t in tipos if t]
    return _most_common(tipos) if tipos else "desconocido"


def group_discoveries(discoveries: list[dict]) -> list[DiscoveryGroup]:
    """Agrupa discoveries por canónico sugerido (puro, determinista).

    Preserva el orden de primera aparición de cada grupo y de los miembros.
    """
    groups: dict[str, DiscoveryGroup] = {}
    order: list[str] = []
    for d in discoveries:
        key = _group_key(d)
        if not key:
            continue
        if key not in groups:
            groups[key] = DiscoveryGroup(canonical_id=key, display_name="", tipo="")
            order.append(key)
        groups[key].members.append(d)

    result: list[DiscoveryGroup] = []
    for key in order:
        g = groups[key]
        g.display_name = _pick_display_name(g.members)
        g.tipo = _pick_tipo(g.members)
        result.append(g)
    return result


def group_pending_discoveries(
    db_path: Path,
    *,
    exclude_ids: set[int] | None = None,
    only_alias_candidates: bool = True,
) -> list[DiscoveryGroup]:
    """Lee los discoveries pendientes y los agrupa.

    `exclude_ids` permite omitir discoveries que ya tienen una decisión
    registrada (para no re-proponerlos en la vista de grupos).
    `only_alias_candidates` excluye los deícticos/rol (alias_candidato=false);
    los `NULL` (runs viejos, sin la marca) se tratan como candidatos.
    """
    from emoparse.storage.actors_kb_discoveries import (
        ActorsKbDiscoveriesRepository,
    )
    from emoparse.storage.db import Database

    repo = ActorsKbDiscoveriesRepository(Database(Path(db_path)))
    pending: list[dict[str, Any]] = repo.list_pending_review()
    if exclude_ids:
        pending = [d for d in pending if int(d["id"]) not in exclude_ids]
    if only_alias_candidates:
        pending = [d for d in pending if _is_alias_candidate(d)]
    return group_discoveries(pending)


def _is_alias_candidate(d: dict) -> bool:
    """True salvo que esté marcado explícitamente como no-candidato (0/False)."""
    val = d.get("alias_candidato")
    return val is None or bool(val)
