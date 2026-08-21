"""Contratos de la candidata de semas intrínsecos y persistencia dimensionada."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pandas as pd
import pytest
from pydantic import ValidationError

from emoparse.agents.semas import SemasAgent
from emoparse.core.grammar import schema_to_gbnf
from emoparse.core.schemas import (
    ListaSemasBatchSchema,
    SemasActorBatchItemSchema,
    SemasCircunstanteBatchItemSchema,
)
from emoparse.storage.db import Database
from emoparse.storage.menciones import MencionesRepository
from emoparse.storage.runs import RunsRepository

CONTEXTUALES = {
    "enunciador",
    "enunciatario",
    "nombrado",
    "inferido",
    "victima",
    "victimario",
    "testigo",
    "beneficiario",
    "adversario",
    "aliado",
    "agente",
    "paciente",
    "discurso_ajeno",
}


def test_schema_is_class_specific_and_excludes_contextual_dimensions() -> None:
    schema = ListaSemasBatchSchema.model_json_schema()
    dumped = json.dumps(schema, ensure_ascii=False)
    for forbidden in ("rol_enunciativo", "rol_narrativo", "tipo_fuente", "modo_actancial"):
        assert forbidden not in dumped
    for value in CONTEXTUALES:
        assert f'"{value}"' not in dumped

    grammar = schema_to_gbnf(ListaSemasBatchSchema, max_items=2)
    assert "SemasActorBatchItemSchema" in grammar
    assert "SemasCircunstanteBatchItemSchema" in grammar
    assert "SemasCualidadBatchItemSchema" in grammar


def test_actor_accepts_atemporal_and_scoped_no_aplica() -> None:
    item = SemasActorBatchItemSchema(
        unit_idx=0,
        clase="actor",
        naturaleza_actor="concepto",
        individuacion="no_aplica",
        temporalidad="atemporal",
        opcionales=["abstracto", "no_figurativo"],
    )
    assert item.temporalidad == "atemporal"

    with pytest.raises(ValidationError):
        SemasActorBatchItemSchema(
            unit_idx=0,
            clase="actor",
            naturaleza_actor="humano",
            individuacion="no_aplica",
            temporalidad="contemporaneidad",
            opcionales=["animado"],
        )


def test_optional_dimensions_reject_internal_contradictions() -> None:
    with pytest.raises(ValidationError):
        SemasActorBatchItemSchema(
            unit_idx=0,
            clase="actor",
            naturaleza_actor="animal",
            individuacion="individual",
            temporalidad="contemporaneidad",
            opcionales=["animado", "inanimado"],
        )


def test_class_specific_schema_rejects_irrelevant_fields() -> None:
    with pytest.raises(ValidationError):
        SemasCircunstanteBatchItemSchema.model_validate(
            {
                "unit_idx": 0,
                "clase": "circunstante",
                "naturaleza_circunstante": "situacion",
                "temporalidad": "indefinido",
                "opcionales": [],
            }
        )


def test_agent_materializes_dimension_and_drops_no_aplica() -> None:
    agent = object.__new__(SemasAgent)
    item = SemasActorBatchItemSchema(
        unit_idx=0,
        clase="actor",
        naturaleza_actor="proceso",
        individuacion="no_aplica",
        temporalidad="contemporaneidad",
        opcionales=["abstracto", "figurativo"],
    )
    out = agent._map_item_to_columns(item, pd.Series(dtype=object))
    semas = json.loads(out["semas"])
    assert {tuple(x.values()) for x in semas} == {
        ("clase", "actor"),
        ("naturaleza_actor", "proceso"),
        ("temporalidad", "contemporaneidad"),
        ("concrecion", "abstracto"),
        ("figuratividad", "figurativo"),
    }
    assert all(x["sema"] != "no_aplica" for x in semas)


def _create_legacy_table(path: Path) -> None:
    conn = sqlite3.connect(path)
    try:
        conn.executescript(
            """
            CREATE TABLE canonico_semas (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                canonical_id TEXT NOT NULL,
                sema TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'proposed',
                origin TEXT NOT NULL DEFAULT 'llm',
                created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                UNIQUE (canonical_id, sema)
            );
            CREATE INDEX idx_canonico_semas_canonical ON canonico_semas(canonical_id);
            CREATE INDEX idx_canonico_semas_sema ON canonico_semas(sema);
            INSERT INTO canonico_semas (canonical_id, sema, status, origin)
            VALUES ('x', 'proceso', 'accepted', 'human');
            """
        )
        conn.commit()
    finally:
        conn.close()


def test_legacy_migration_is_lossless_and_idempotent(tmp_path: Path) -> None:
    path = tmp_path / "legacy.sqlite"
    _create_legacy_table(path)
    db = Database(path)
    repo = RunsRepository(db)
    repo.ensure_migrations()
    repo.ensure_migrations()

    cols = {r["name"] for r in db.execute("PRAGMA table_info(canonico_semas)").fetchall()}
    assert "dimension" in cols
    rows = db.execute(
        "SELECT canonical_id, dimension, sema, status, origin FROM canonico_semas"
    ).fetchall()
    assert [tuple(r) for r in rows] == [("x", "legacy", "proceso", "accepted", "human")]

    ddl = db.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='canonico_semas'"
    ).fetchone()["sql"]
    assert "UNIQUE (canonical_id, dimension, sema)" in ddl


def test_same_sema_can_coexist_in_distinct_dimensions(tmp_path: Path) -> None:
    path = tmp_path / "new.sqlite"
    db = Database(path)
    RunsRepository(db).ensure_migrations()
    repo = MencionesRepository(db)
    added = repo.propose_semas(
        "x",
        [("naturaleza_actor", "proceso"), ("naturaleza_circunstante", "proceso")],
        allowed={
            "naturaleza_actor": {"proceso"},
            "naturaleza_circunstante": {"proceso"},
        },
    )
    assert added == 2
    rows = db.execute(
        "SELECT dimension, sema FROM canonico_semas WHERE canonical_id='x' ORDER BY dimension"
    ).fetchall()
    assert [tuple(r) for r in rows] == [
        ("naturaleza_actor", "proceso"),
        ("naturaleza_circunstante", "proceso"),
    ]


def test_actor_allows_no_aplica_for_non_individuable_object_and_other() -> None:
    for naturaleza in ("objeto", "otro"):
        item = SemasActorBatchItemSchema(
            unit_idx=0,
            clase="actor",
            naturaleza_actor=naturaleza,
            individuacion="no_aplica",
            temporalidad="atemporal",
            opcionales=["inanimado"],
        )
        assert item.individuacion == "no_aplica"

    for naturaleza in ("humano", "animal", "institucional", "sobrenatural"):
        with pytest.raises(ValidationError):
            SemasActorBatchItemSchema(
                unit_idx=0,
                clase="actor",
                naturaleza_actor=naturaleza,
                individuacion="no_aplica",
                temporalidad="indefinido",
                opcionales=[],
            )


def test_semas_errors_remain_retryable(tmp_path: Path) -> None:
    path = tmp_path / "retryable.sqlite"
    db = Database(path)
    RunsRepository(db).ensure_migrations()
    db.execute("INSERT INTO discursos (codigo, input) VALUES (?, ?)", ("d1", "{}"))
    db.execute(
        "INSERT INTO menciones (codigo, unit_idx, marca) VALUES (?, ?, ?)",
        ("d1", 0, "marca"),
    )
    mid = db.execute("SELECT id FROM menciones WHERE codigo='d1'").fetchone()["id"]
    db.execute(
        "INSERT INTO mencion_canonico (mencion_id, canonical_id, status, semas_version, semas_error) "
        "VALUES (?, ?, 'accepted', 'v76', 'fallo')",
        (mid, "x"),
    )
    repo = MencionesRepository(db)
    assert "x" not in repo.canonicos_semas_procesados()
    db.execute("UPDATE mencion_canonico SET semas_error=NULL WHERE canonical_id='x'")
    assert "x" in repo.canonicos_semas_procesados()


def test_semas_stage_recovers_failed_batch_as_singletons(monkeypatch) -> None:
    from emoparse.pipeline import stages as stages_mod

    class FakeRepo:
        def __init__(self) -> None:
            self.marks: dict[str, str | None] = {}
            self.proposed: dict[str, list[tuple[str, str]]] = {}

        def canonicos_semas_procesados(self):
            return set()

        def list_canonicos(self, codigos=None):
            return [
                {"canonical_id": "recuperable", "marcas": ["recuperable"]},
                {"canonical_id": "persistente", "marcas": ["persistente"]},
            ]

        def propose_semas(self, canonical_id, semas, *, allowed, origin):
            self.proposed[canonical_id] = list(semas)
            return len(semas)

        def mark_semas_processed(self, canonical_id, *, version, error=None):
            self.marks[canonical_id] = error

    class FakeSemasAgent:
        ERROR_COLUMN = "_agente_error"
        calls: list[list[str]] = []

        def __init__(self, *args, **kwargs) -> None:
            self.on_progress = None

        def run(self, df):
            ids = [str(x) for x in df["canonical_id"].tolist()]
            type(self).calls.append(ids)
            out = df.copy().reset_index(drop=True)
            if len(out) > 1:
                out["semas"] = None
                return out
            cid = ids[0]
            if cid == "recuperable":
                out["semas"] = [
                    json.dumps(
                        [
                            {"dimension": "clase", "sema": "actor"},
                            {"dimension": "naturaleza_actor", "sema": "objeto"},
                            {"dimension": "temporalidad", "sema": "atemporal"},
                        ]
                    )
                ]
                return out
            out["semas"] = None
            out[self.ERROR_COLUMN] = "schema sigue inválido"
            return out

    monkeypatch.setattr(stages_mod, "SemasAgent", FakeSemasAgent)
    repo = FakeRepo()
    vocab = {
        "dimensiones": {
            "clase": {"valores": ["actor"]},
            "naturaleza_actor": {"valores": ["objeto"]},
            "temporalidad": {"valores": ["atemporal"]},
        }
    }
    stage = stages_mod.SemasStage(
        backend=object(),
        menciones_repo=repo,
        semas_vocab=vocab,
        agent_version="v76",
    )
    total = stage.run_pending()

    assert FakeSemasAgent.calls == [
        ["recuperable", "persistente"],
        ["recuperable"],
        ["persistente"],
    ]
    assert total == 3
    assert repo.marks["recuperable"] is None
    assert repo.marks["persistente"] == "schema sigue inválido"
    assert repo.proposed["recuperable"] == [
        ("clase", "actor"),
        ("naturaleza_actor", "objeto"),
        ("temporalidad", "atemporal"),
    ]


def test_semas_stage_treats_nan_error_cell_as_no_error(monkeypatch) -> None:
    from emoparse.pipeline import stages as stages_mod

    class FakeRepo:
        def __init__(self) -> None:
            self.marks: dict[str, str | None] = {}
            self.proposed: dict[str, list[tuple[str, str]]] = {}

        def canonicos_semas_procesados(self):
            return set()

        def list_canonicos(self, codigos=None):
            return [
                {"canonical_id": "a", "marcas": ["a"]},
                {"canonical_id": "b", "marcas": ["b"]},
            ]

        def propose_semas(self, canonical_id, semas, *, allowed, origin):
            self.proposed[canonical_id] = list(semas)
            return len(semas)

        def mark_semas_processed(self, canonical_id, *, version, error=None):
            self.marks[canonical_id] = error

    class FakeSemasAgent:
        ERROR_COLUMN = "_agente_error"

        def __init__(self, *args, **kwargs) -> None:
            self.on_progress = None

        def run(self, df):
            out = df.copy().reset_index(drop=True)
            payload = json.dumps(
                [
                    {"dimension": "clase", "sema": "actor"},
                    {"dimension": "naturaleza_actor", "sema": "objeto"},
                    {"dimension": "temporalidad", "sema": "atemporal"},
                ]
            )
            out["semas"] = [payload for _ in range(len(out))]
            # Reproduce exactamente la representación que pandas generó en el full v76:
            # una columna de errores existente con celdas válidas materializadas como NaN.
            out[self.ERROR_COLUMN] = [float("nan"), None]
            return out

    monkeypatch.setattr(stages_mod, "SemasAgent", FakeSemasAgent)
    repo = FakeRepo()
    vocab = {
        "dimensiones": {
            "clase": {"valores": ["actor"]},
            "naturaleza_actor": {"valores": ["objeto"]},
            "temporalidad": {"valores": ["atemporal"]},
        }
    }
    stage = stages_mod.SemasStage(
        backend=object(),
        menciones_repo=repo,
        semas_vocab=vocab,
        agent_version="v76",
    )
    total = stage.run_pending()

    assert total == 6
    assert repo.marks == {"a": None, "b": None}
    assert set(repo.proposed) == {"a", "b"}
