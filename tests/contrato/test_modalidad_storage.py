from __future__ import annotations

from pathlib import Path

from emoparse.storage.db import Database
from emoparse.storage.menciones import MencionesRepository
from emoparse.storage.models import RunContext
from emoparse.storage.runs import RunsRepository


def _db(tmp_path: Path) -> Database:
    db = Database(tmp_path / "modalidad.sqlite")
    RunsRepository(db).bootstrap(RunContext(run_id="modalidad-test"))
    with db.transaction() as cur:
        cur.execute(
            "INSERT INTO discursos (codigo, input) VALUES (?, ?)",
            ("D001", "{}"),
        )
        cur.execute(
            "INSERT INTO frases (codigo, unit_idx, frase) VALUES (?, ?, ?)",
            ("D001", 0, "nuestros productores"),
        )
        cur.execute(
            "INSERT INTO menciones (id, codigo, unit_idx, marca, llm_inferencia) "
            "VALUES (?, ?, ?, ?, ?)",
            (1, "D001", 0, "nuestros productores", "productores"),
        )
        cur.execute(
            "INSERT INTO mencion_funcion (mencion_id, funcion) VALUES (?, ?)",
            (1, "actor"),
        )
        cur.execute(
            "INSERT INTO mencion_canonico "
            "(mencion_id, canonical_id, status, origin, naturaleza) "
            "VALUES (?, ?, 'accepted', 'llm', 'colectivo')",
            (1, "productores"),
        )
    return db


def test_schema_incluye_proveniencia_y_revision(tmp_path: Path) -> None:
    db = _db(tmp_path)
    cols = {r["name"] for r in db.execute("PRAGMA table_info(mencion_canonico)").fetchall()}
    assert {"modalidad_version", "modalidad_review_reason"} <= cols


def test_modalidad_automatica_no_reescribe_naturaleza_legacy(tmp_path: Path) -> None:
    db = _db(tmp_path)
    repo = MencionesRepository(db)
    repo.set_modalidad(
        1,
        "productores",
        "designacion",
        None,
        "nlp",
        version="v62",
    )
    row = db.execute(
        "SELECT modalidad, naturaleza, modalidad_origin, modalidad_version, "
        "modalidad_review_reason FROM mencion_canonico"
    ).fetchone()
    assert row["modalidad"] == "designacion"
    assert row["naturaleza"] == "colectivo"
    assert row["modalidad_origin"] == "nlp"
    assert row["modalidad_version"] == "v62"
    assert row["modalidad_review_reason"] is None


def test_revision_upstream_queda_fuera_de_pendientes(tmp_path: Path) -> None:
    db = _db(tmp_path)
    repo = MencionesRepository(db)
    repo.set_modalidad(
        1,
        "productores",
        None,
        None,
        "llm",
        version="v62",
        review_reason="La arista no está sostenida.",
    )
    assert repo.list_links_for_modalidad("D001") == []


def test_edicion_humana_preserva_version_automatica(tmp_path: Path) -> None:
    db = _db(tmp_path)
    repo = MencionesRepository(db)
    repo.set_modalidad(
        1,
        "productores",
        "designacion",
        None,
        "llm",
        version="v62",
    )
    repo.set_modalidad(
        1,
        "productores",
        "identificacion_inferencial",
        "colectivo",
        "human",
    )
    row = db.execute(
        "SELECT modalidad, naturaleza, modalidad_origin, modalidad_version FROM mencion_canonico"
    ).fetchone()
    assert row["modalidad"] == "identificacion_inferencial"
    assert row["naturaleza"] == "colectivo"
    assert row["modalidad_origin"] == "human"
    assert row["modalidad_version"] == "v62"

    repo.set_modalidad(
        1,
        "productores",
        "designacion",
        None,
        "nlp",
        version="v62",
    )
    row2 = db.execute(
        "SELECT modalidad, modalidad_origin, modalidad_version FROM mencion_canonico"
    ).fetchone()
    assert row2["modalidad"] == "identificacion_inferencial"
    assert row2["modalidad_origin"] == "human"
    assert row2["modalidad_version"] == "v62"


def test_menciones_repository_se_importa_sin_ciclo_pipeline() -> None:
    from emoparse.storage.menciones import MencionesRepository as ImportedRepository

    assert ImportedRepository is MencionesRepository


def test_deixis_reexporta_la_misma_logica_compartida() -> None:
    from emoparse.pipeline.deixis import is_deictic as pipeline_is_deictic
    from emoparse.pipeline.deixis import (
        is_first_person_deictic as pipeline_is_first_person_deictic,
    )
    from emoparse.storage.referencia import is_deictic as shared_is_deictic
    from emoparse.storage.referencia import (
        is_first_person_deictic as shared_is_first_person_deictic,
    )

    casos = ("yo", "nuestros productores", "gobierno", "tenemos")
    for caso in casos:
        assert pipeline_is_deictic(caso) == shared_is_deictic(caso)
        assert pipeline_is_first_person_deictic(caso) == shared_is_first_person_deictic(caso)
