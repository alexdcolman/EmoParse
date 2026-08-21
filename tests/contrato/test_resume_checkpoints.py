from __future__ import annotations

import json
from pathlib import Path

from emoparse.domain.validators.runner import ValidationRunner
from emoparse.storage.checkpoints import StageCheckpointsRepository
from emoparse.storage.db import Database
from emoparse.storage.emociones import EmocionesRepository
from emoparse.storage.models import RunContext
from emoparse.storage.runs import RunsRepository


def _db(tmp_path: Path) -> Database:
    db = Database(tmp_path / "resume.sqlite")
    RunsRepository(db).bootstrap(RunContext(run_id="test-resume"))
    return db


def test_stage_checkpoint_roundtrip(tmp_path: Path) -> None:
    db = _db(tmp_path)
    repo = StageCheckpointsRepository(db)

    assert not repo.is_current("explode_emotions", "D1", "abc", stage_version="v1")
    repo.mark_completed("explode_emotions", "D1", "abc", stage_version="v1")
    assert repo.is_current("explode_emotions", "D1", "abc", stage_version="v1")
    assert not repo.is_current("explode_emotions", "D1", "def", stage_version="v1")
    assert not repo.is_current("explode_emotions", "D1", "abc", stage_version="v2")

    repo.invalidate("explode_emotions", "D1")
    assert not repo.is_current("explode_emotions", "D1", "abc", stage_version="v1")


def test_normalization_null_canonical_is_completed_when_versioned(tmp_path: Path) -> None:
    db = _db(tmp_path)
    db.execute(
        "INSERT INTO discursos (codigo, input) VALUES (?, ?)",
        ("D1", json.dumps({"contenido": "Texto"})),
    )
    db.execute(
        "INSERT INTO frases (codigo, unit_idx, frase) VALUES (?, ?, ?)",
        ("D1", 0, "Texto"),
    )
    db.execute(
        """
        INSERT INTO emociones (
            codigo, frase_idx, emocion_idx, experienciador, experienciador_marca,
            tipo_emocion, fuente_marca, fuente_inferencia, modo_existencia
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        ("D1", 0, 0, "X", "X", "etiqueta_fuera_catalogo", "Y", "Y", "actualizado"),
    )
    repo = EmocionesRepository(db)
    assert repo.list_pending_normalization() == [("D1", 0, 0)]

    repo.set_normalized_emotion("D1", 0, 0, tipo_emocion_canonico=None, version="v30")
    assert repo.list_pending_normalization() == []


def test_validation_runner_parses_nested_enunciatarios_json(tmp_path: Path) -> None:
    db = _db(tmp_path)
    payload = {
        "enunciador": "Página/12",
        "enunciatarios": json.dumps(
            [{"actor": "lectores de Página/12", "rol": "auditorio"}],
            ensure_ascii=False,
        ),
    }
    db.execute(
        "INSERT INTO discursos (codigo, input, enunciation_payload) VALUES (?, ?, ?)",
        ("D1", json.dumps({"contenido": "Texto"}), json.dumps(payload, ensure_ascii=False)),
    )

    runner = ValidationRunner(db, row_validators=[], discurso_validators=[])
    enunciador, enunciatarios = runner._load_enunciacion("D1")

    assert enunciador == "Página/12"
    assert enunciatarios == [{"actor": "lectores de Página/12", "rol": "auditorio"}]
