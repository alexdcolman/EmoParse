# ══════════════════════════════════════════════════════════════════════════════
#  tests.unit.test_explode_emociones_propagates_config
#
#  Verifica que ExplodeEmocionesStage propaga tipo_configuracion desde el
#  payload de la frase al upsert de la tabla emociones, y que el contrato
#  Pandera lo admite como nullable.
# ══════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

from typing import Any

import pandas as pd

from emoparse.pipeline.stages import ExplodeEmocionesStage


class _FakeDiscursosRepo:
    def __init__(self, codigos: list[str]) -> None:
        self._codigos = codigos

    def list_codigos(self) -> list[str]:
        return self._codigos


class _FakeFrasesRepo:
    def __init__(
        self,
        frases: dict[str, list[tuple[int, str]]],
        emociones: dict[tuple[str, int], list[dict[str, Any]]],
    ) -> None:
        self._frases = frases
        self._emociones = emociones

    def list_frases_of_discurso(self, codigo: str) -> list[tuple[int, str]]:
        return self._frases.get(codigo, [])

    def get_payload(self, codigo: str, frase_idx: int, key: str) -> Any:
        assert key in {"emociones", "emociones_pass2"}
        return self._emociones.get((codigo, frase_idx))


class _FakeEmocionesRepo:
    def __init__(self) -> None:
        self.upserts: list[dict[str, Any]] = []

    def upsert_emociones(self, rows) -> None:
        self.upserts.extend(rows)


def test_explode_propagates_tipo_configuracion() -> None:
    d_repo = _FakeDiscursosRepo(["A"])
    f_repo = _FakeFrasesRepo(
        frases={"A": [(0, "frase 0")]},
        emociones={
            ("A", 0): [
                {
                    "experienciador": "el pueblo",
                    "tipo_emocion": "indignacion",
                    "modo_existencia": "realizada",
                    "tipo_configuracion": "sostenido_en_sustantivos",
                    "justificacion": "se nombra la indignación",
                },
                {
                    "experienciador": "el orador",
                    "tipo_emocion": "esperanza",
                    "modo_existencia": "potencial",
                    "tipo_configuracion": "transposicion_situacion_reconocimiento_potencial",
                    "justificacion": "proyectado al lector",
                },
            ]
        },
    )
    e_repo = _FakeEmocionesRepo()
    stage = ExplodeEmocionesStage(d_repo, f_repo, e_repo)
    stage.validate_contracts = True

    n = stage.run_pending()
    assert n == 2
    assert len(e_repo.upserts) == 2

    by_tipo = {r["tipo_emocion"]: r for r in e_repo.upserts}
    assert by_tipo["indignacion"]["tipo_configuracion"] == "sostenido_en_sustantivos"
    assert by_tipo["esperanza"]["tipo_configuracion"] == (
        "transposicion_situacion_reconocimiento_potencial"
    )


def test_explode_tolerates_missing_tipo_configuracion() -> None:
    """Payload pre-T3 sin tipo_configuracion debe terminar en None, no crashear."""
    d_repo = _FakeDiscursosRepo(["A"])
    f_repo = _FakeFrasesRepo(
        frases={"A": [(0, "frase 0")]},
        emociones={
            ("A", 0): [
                {
                    "experienciador": "el pueblo",
                    "tipo_emocion": "indignacion",
                    "modo_existencia": "realizada",
                    "justificacion": "evidencia",
                },
            ]
        },
    )
    e_repo = _FakeEmocionesRepo()
    stage = ExplodeEmocionesStage(d_repo, f_repo, e_repo)
    stage.validate_contracts = True

    n = stage.run_pending()
    assert n == 1
    assert e_repo.upserts[0]["tipo_configuracion"] is None
