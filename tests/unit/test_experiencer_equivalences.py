# ══════════════════════════════════════════════════════════════════════════════
#  tests.unit.test_experiencer_equivalences
#
#  Garantías del repository de equivalencias de experienciadores.
# ══════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

import pytest

from emoparse.storage import schema
from emoparse.storage.db import Database
from emoparse.storage.emociones import EmocionesRepository
from emoparse.storage.experiencer_equivalences import (
    ExperiencerEquivalencesRepository,
)


@pytest.fixture
def db(tmp_path):
    d = Database(tmp_path / "run.sqlite")
    # Las FKs (emociones → frases) no son el objeto de estos tests.
    d.execute("PRAGMA foreign_keys=OFF")
    for ddl in schema.ALL_TABLES_DDL:
        d.execute(ddl)
    return d


@pytest.fixture
def repo(db):
    return ExperiencerEquivalencesRepository(db)


@pytest.fixture
def emo(db):
    return EmocionesRepository(db)


def _propose(repo, raw="yo", *, sugerido="Milei", clase="enunciador",
             conf="alta", just="1a pers", n=3, codigo="d1"):
    repo.upsert_proposal(
        codigo, raw,
        canonical_sugerido=sugerido, clase=clase, confianza=conf,
        justificacion=just, ocurrencias=n,
    )


# ── Propuestas ────────────────────────────────────────────────────────────────

def test_upsert_inserts_pending(repo):
    _propose(repo)
    rows = repo.list_pending_review("d1")
    assert len(rows) == 1
    r = rows[0]
    assert r["raw_experienciador"] == "yo"
    assert r["canonical_sugerido"] == "Milei"
    assert r["status"] == "pending"
    assert r["ocurrencias"] == 3


def test_list_existing_raw(repo):
    _propose(repo, "yo")
    _propose(repo, "la casta", sugerido=None, clase="otro", conf="baja", n=1)
    assert repo.list_existing_raw("d1") == {"yo", "la casta"}
    assert repo.list_existing_raw("otro") == set()


def test_upsert_refreshes_pending(repo):
    _propose(repo, sugerido="Milei", n=3)
    _propose(repo, sugerido="Javier Milei", n=7)  # re-corrida de la stage
    r = repo.find(_only_id(repo))
    assert r["canonical_sugerido"] == "Javier Milei"
    assert r["ocurrencias"] == 7
    assert r["status"] == "pending"


def test_upsert_preserves_decided(repo):
    _propose(repo, sugerido="Milei")
    eid = _only_id(repo)
    repo.accept(eid, canonical="Javier Milei")
    # La stage vuelve a correr y propone otra cosa: no debe pisar la decisión.
    _propose(repo, sugerido="OTRO", clase="otro", conf="baja", n=99)
    r = repo.find(eid)
    assert r["status"] == "accepted"
    assert r["canonical_final"] == "Javier Milei"
    assert r["canonical_sugerido"] == "Milei"
    assert r["ocurrencias"] == 3


# ── Decisiones ──────────────────────────────────────────────────────────────

def test_accept_uses_suggested_by_default(repo):
    _propose(repo, sugerido="Milei")
    eid = _only_id(repo)
    repo.accept(eid)
    assert repo.find(eid)["canonical_final"] == "Milei"


def test_accept_explicit_canonical_overrides(repo):
    _propose(repo, sugerido="Milei")
    eid = _only_id(repo)
    repo.accept(eid, canonical="Javier Milei")
    assert repo.find(eid)["canonical_final"] == "Javier Milei"


def test_accept_literal_defaults_to_raw(repo):
    _propose(repo, "Milei", sugerido=None, clase="literal", conf="alta", n=2)
    eid = _only_id(repo)
    repo.accept(eid)
    assert repo.find(eid)["canonical_final"] == "Milei"


def test_accept_without_target_raises(repo):
    _propose(repo, "no se sabe", sugerido=None, clase="otro", conf="baja", n=1)
    eid = _only_id(repo)
    with pytest.raises(ValueError):
        repo.accept(eid)
    # Sigue pendiente tras el error.
    assert repo.find(eid)["status"] == "pending"


def test_reject_clears_canonical(repo):
    _propose(repo)
    eid = _only_id(repo)
    repo.reject(eid)
    r = repo.find(eid)
    assert r["status"] == "rejected"
    assert r["canonical_final"] is None


def test_reset_to_pending(repo):
    _propose(repo)
    eid = _only_id(repo)
    repo.accept(eid)
    repo.reset_to_pending(eid)
    r = repo.find(eid)
    assert r["status"] == "pending"
    assert r["canonical_final"] is None


def test_cannot_redecide_applied(repo):
    _propose(repo)
    eid = _only_id(repo)
    repo.accept(eid)
    repo.mark_applied(eid)
    with pytest.raises(ValueError):
        repo.accept(eid)
    with pytest.raises(ValueError):
        repo.reject(eid)
    with pytest.raises(ValueError):
        repo.reset_to_pending(eid)


def test_counts_by_status(repo):
    _propose(repo, "yo")
    _propose(repo, "Milei", sugerido="Milei", clase="literal")
    _propose(repo, "la casta", sugerido=None, clase="otro", conf="baja", n=1)
    repo.accept(_id_of(repo, "yo"), canonical="Javier Milei")
    repo.reject(_id_of(repo, "la casta"))
    assert repo.count_by_status("pending") == 1
    assert repo.count_by_status("accepted") == 1
    assert repo.count_by_status("rejected") == 1
    assert repo.count_by_status("applied") == 0


# ── Apply (equivalences repo + emociones repo) ────────────────────────────────

def test_apply_writes_canonico_and_is_idempotent(repo, emo):
    _propose(repo, "yo", sugerido="Milei")
    _propose(repo, "Milei", sugerido="Milei", clase="literal", n=2)
    _propose(repo, "la casta", sugerido=None, clase="otro", conf="baja", n=1)
    repo.accept(_id_of(repo, "yo"), canonical="Javier Milei")
    repo.accept(_id_of(repo, "Milei"))
    repo.reject(_id_of(repo, "la casta"))

    for fi, (raw, tipo) in enumerate([
        ("yo", "orgullo"), ("yo", "determinacion"),
        ("Milei", "ironia"), ("la casta", "desprecio"),
    ]):
        emo.upsert_emocion("d1", fi, 0, raw, tipo, "realizada")

    # Emula `emoparse experiencers apply`.
    total = 0
    for r in repo.list_accepted_unapplied():
        total += emo.set_experienciador_canonico(
            r["codigo"], r["raw_experienciador"], r["canonical_final"],
            version="v8",
        )
        repo.mark_applied(r["id"])

    assert total == 3  # 2x "yo" + 1x "Milei"
    canon = {
        e["experienciador"]: e["experienciador_canonico"]
        for e in emo.list_emociones_of_discurso("d1")
    }
    assert canon["yo"] == "Javier Milei"
    assert canon["Milei"] == "Milei"
    assert canon["la casta"] is None  # rechazado → sin canónico

    # Versión estampada.
    versions = {
        e["experienciador"]: e["normalize_experiencers_version"]
        for e in emo.list_emociones_of_discurso("d1")
    }
    assert versions["yo"] == "v8"

    # Idempotente: re-aplicar no deja nada pendiente ni rompe.
    assert repo.list_accepted_unapplied() == []
    assert repo.count_by_status("applied") == 2


def test_set_experienciador_canonico_scoped_by_codigo(emo):
    emo.upsert_emocion("d1", 0, 0, "yo", "alegria", "realizada")
    emo.upsert_emocion("d2", 0, 0, "yo", "alegria", "realizada")
    n = emo.set_experienciador_canonico("d1", "yo", "Milei", version=None)
    assert n == 1
    by_codigo = {
        (e_codigo, e_canon)
        for e_codigo in ("d1", "d2")
        for e_canon in [
            emo.list_emociones_of_discurso(e_codigo)[0]["experienciador_canonico"]
        ]
    }
    assert ("d1", "Milei") in by_codigo
    assert ("d2", None) in by_codigo


def test_list_distinct_experiencers_counts(emo):
    for fi in range(3):
        emo.upsert_emocion("d1", fi, 0, "yo", "alegria", "realizada")
    emo.upsert_emocion("d1", 3, 0, "la casta", "desprecio", "realizada")
    distinct = dict(emo.list_distinct_experiencers("d1"))
    assert distinct == {"yo": 3, "la casta": 1}


# ── Helpers de test ───────────────────────────────────────────────────────────

def _only_id(repo, codigo="d1"):
    rows = repo.list_by_status(status=None, codigo=codigo)
    assert len(rows) == 1
    return rows[0]["id"]


def _id_of(repo, raw, codigo="d1"):
    for r in repo.list_by_status(status=None, codigo=codigo):
        if r["raw_experienciador"] == raw:
            return r["id"]
    raise AssertionError(f"no encontré la equivalencia {raw!r}")
