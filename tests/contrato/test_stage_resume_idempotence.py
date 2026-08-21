from __future__ import annotations

from unittest.mock import MagicMock

import pandas as pd

from emoparse.pipeline import stages as stages_module
from emoparse.pipeline.stages import DeixisStage, ExplodeEmotionsStage


class _MemoryCheckpoints:
    def __init__(self) -> None:
        self.rows: dict[tuple[str, str], tuple[str, str | None]] = {}

    def is_current(
        self,
        stage_name: str,
        scope_key: str,
        input_fingerprint: str,
        *,
        stage_version: str | None = None,
    ) -> bool:
        return self.rows.get((stage_name, scope_key)) == (input_fingerprint, stage_version)

    def mark_completed(
        self,
        stage_name: str,
        scope_key: str,
        input_fingerprint: str,
        *,
        stage_version: str | None = None,
    ) -> None:
        self.rows[(stage_name, scope_key)] = (input_fingerprint, stage_version)


def test_explode_resume_does_not_rebuild_unchanged_mentions() -> None:
    d_repo = MagicMock()
    f_repo = MagicMock()
    e_repo = MagicMock()
    m_repo = MagicMock()
    checkpoints = _MemoryCheckpoints()

    d_repo.list_codigos.return_value = ["D1"]
    d_repo.get_payload.return_value = {"enunciador": "Diario", "auditorio": "[]"}
    f_repo.list_frases_of_discurso.return_value = [(0, "Texto")]

    def payload(_codigo: str, _idx: int, stage: str):
        if stage == "actores":
            return [{"actor": "Persona", "marca": "Persona"}]
        if stage == "emociones_pass2":
            return None
        if stage == "emociones":
            return [
                {
                    "experienciador": "Persona",
                    "experienciador_marca": "Persona",
                    "tipo_emocion": "preocupación",
                    "modo_existencia": "actualizado",
                    "fuente_marca": "hecho",
                    "fuente_inferencia": "hecho",
                }
            ]
        raise AssertionError(stage)

    f_repo.get_payload.side_effect = payload
    stage = ExplodeEmotionsStage(
        d_repo,
        f_repo,
        e_repo,
        m_repo,
        referentes_kb={},
        checkpoints_repo=checkpoints,  # type: ignore[arg-type]
    )
    stage.validate_contracts = False

    assert stage.run_pending() == 1
    assert stage.run_pending() == 0
    assert e_repo.upsert_emociones.call_count == 1
    assert m_repo.rebuild_for_codigo.call_count == 1

    # Si cambia una entrada gobernante, el checkpoint deja de ser válido.
    f_repo.list_frases_of_discurso.return_value = [(0, "Texto cambiado")]
    assert stage.run_pending() == 1
    assert e_repo.upsert_emociones.call_count == 2
    assert m_repo.rebuild_for_codigo.call_count == 2


def test_deixis_resume_remembers_valid_empty_result(monkeypatch) -> None:
    d_repo = MagicMock()
    m_repo = MagicMock()
    backend = MagicMock()
    checkpoints = _MemoryCheckpoints()
    calls = {"n": 0}

    d_repo.list_codigos.return_value = ["D1"]

    def discurso_payload(_codigo: str, stage: str):
        if stage == "enunciation":
            return {"enunciador": "Diario", "auditorio": "[]", "colectivos_identificacion": "[]"}
        if stage == "summarizer":
            return {"resumen_global": "Resumen"}
        raise AssertionError(stage)

    d_repo.get_payload.side_effect = discurso_payload
    m_repo.list_marcas_for_deixis.return_value = [{"id": 7, "unit_idx": 0, "marca": "nosotros"}]

    class _FakeDeixisAgent:
        def __init__(self, *args, **kwargs) -> None:
            pass

        def run(self, df: pd.DataFrame) -> pd.DataFrame:
            calls["n"] += 1
            out = df.copy()
            out["deixis"] = ["[]"] * len(out)
            return out

    monkeypatch.setattr(stages_module, "DeixisAgent", _FakeDeixisAgent)

    stage = DeixisStage(
        backend,
        d_repo,
        m_repo,
        agent_version="v76",
        checkpoints_repo=checkpoints,  # type: ignore[arg-type]
    )

    assert stage.run_pending() == 0
    assert calls["n"] == 1
    assert stage.run_pending() == 0
    assert calls["n"] == 1

    # Un cambio en las marcas vuelve a habilitar la resolución.
    m_repo.list_marcas_for_deixis.return_value = [
        {"id": 7, "unit_idx": 0, "marca": "nosotros"},
        {"id": 8, "unit_idx": 1, "marca": "nuestro"},
    ]
    assert stage.run_pending() == 0
    assert calls["n"] == 2
