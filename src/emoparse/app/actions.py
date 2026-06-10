# ══════════════════════════════════════════════════════════════════════════════
#  emoparse.app.actions
#
#  Capa de escritura de la UI Streamlit.
#
#  Este módulo expone funciones puras para registrar decisiones de triage sobre
#  discoveries de actores: promote / merge / discard.
# ══════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

from pathlib import Path

from loguru import logger

from emoparse.storage.actors_kb_discoveries import ActorsKbDiscoveriesRepository
from emoparse.storage.db import Database
from emoparse.storage.experiencer_equivalences import (
    ExperiencerEquivalencesRepository,
)


def register_promote(
    db_path: Path,
    discovery_id: int,
    *,
    canonical_id: str,
    display_name: str,
    tipo: str = "desconocido",
    rol: str | None = None,
) -> None:
    """Registra desde el dashboard una decisión de promover un discovery.

    La decisión queda pending hasta que se corra `emoparse discoveries apply`.
    """
    repo = _open_repo(db_path)
    repo.upsert_decision(
        discovery_id=discovery_id,
        decision="promote",
        canonical_id=canonical_id,
        display_name=display_name,
        tipo=tipo,
        rol=rol,
        origin="dashboard",
    )
    logger.info(
        f"[app.actions] Registrada promote desde dashboard: "
        f"discovery={discovery_id} → '{canonical_id}'"
    )


def register_merge(
    db_path: Path,
    discovery_id: int,
    *,
    into_canonical_id: str,
) -> None:
    """Registra desde el dashboard una decisión de merge."""
    repo = _open_repo(db_path)
    repo.upsert_decision(
        discovery_id=discovery_id,
        decision="merge",
        canonical_id=into_canonical_id,
        origin="dashboard",
    )
    logger.info(
        f"[app.actions] Registrada merge desde dashboard: "
        f"discovery={discovery_id} → '{into_canonical_id}'"
    )


def register_discard(
    db_path: Path,
    discovery_id: int,
) -> None:
    """Registra desde el dashboard una decisión de descarte."""
    repo = _open_repo(db_path)
    repo.upsert_decision(
        discovery_id=discovery_id,
        decision="discard",
        origin="dashboard",
    )
    logger.info(
        f"[app.actions] Registrada discard desde dashboard: "
        f"discovery={discovery_id}"
    )


def undo_decision(db_path: Path, discovery_id: int) -> None:
    """Borra una decisión `pending` previamente registrada."""
    repo = _open_repo(db_path)
    existing = repo.find_decision(discovery_id)
    if existing is None:
        return
    if existing["status"] == "applied":
        raise ValueError(
            f"Decisión sobre discovery {discovery_id} ya aplicada. "
            f"No se puede deshacer desde la UI."
        )
    repo.delete_decision(discovery_id)
    logger.info(
        f"[app.actions] Deshecha decisión: discovery={discovery_id}"
    )


def _open_repo(db_path: Path) -> ActorsKbDiscoveriesRepository:
    """Abre el repo en modo read-write."""
    if not db_path.is_file():
        raise FileNotFoundError(f"DB no encontrada: {db_path}")
    db = Database(db_path)
    if not db.table_exists("actors_kb_discoveries"):
        raise RuntimeError(
            f"DB sin tabla actors_kb_discoveries."
        )
    return ActorsKbDiscoveriesRepository(db)


# ══════════════════════════════════════════════════════════════════════════════
#  Equivalencias de experienciador
# ══════════════════════════════════════════════════════════════════════════════

def register_experiencer_accept(
    db_path: Path,
    equivalence_id: int,
    *,
    canonical: str | None = None,
) -> None:
    """Acepta desde el dashboard una equivalencia de experienciador.

    Queda accepted hasta correr `emoparse experiencers apply`. Si `canonical`
    es None se usa el sugerido (o el crudo si la clase es 'literal').
    """
    repo = _open_equiv_repo(db_path)
    repo.accept(equivalence_id, canonical=canonical, origin="dashboard")
    logger.info(
        f"[app.actions] Aceptada equivalencia desde dashboard: "
        f"id={equivalence_id} canonical={canonical!r}"
    )


def register_experiencer_reject(db_path: Path, equivalence_id: int) -> None:
    """Rechaza desde el dashboard una equivalencia de experienciador."""
    repo = _open_equiv_repo(db_path)
    repo.reject(equivalence_id, origin="dashboard")
    logger.info(
        f"[app.actions] Rechazada equivalencia desde dashboard: "
        f"id={equivalence_id}"
    )


def undo_experiencer_decision(db_path: Path, equivalence_id: int) -> None:
    """Vuelve a pending una equivalencia decidida (no aplicada)."""
    repo = _open_equiv_repo(db_path)
    repo.reset_to_pending(equivalence_id)
    logger.info(
        f"[app.actions] Equivalencia vuelta a pending: id={equivalence_id}"
    )


def _open_equiv_repo(db_path: Path) -> ExperiencerEquivalencesRepository:
    """Abre el repo de equivalencias de experienciador en modo read-write."""
    if not db_path.is_file():
        raise FileNotFoundError(f"DB no encontrada: {db_path}")
    db = Database(db_path)
    if not db.table_exists("experiencer_equivalences"):
        raise RuntimeError("DB sin tabla experiencer_equivalences.")
    return ExperiencerEquivalencesRepository(db)
