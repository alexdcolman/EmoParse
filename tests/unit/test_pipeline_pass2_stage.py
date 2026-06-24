# ══════════════════════════════════════════════════════════════════════════════
#  tests.unit.test_pipeline_pass2_stage
#
#  Tests del EmotionsPass2Stage:
#  - Skip si no hay pase 1 hecho.
#  - Persiste a `emociones_pass2_payload`, no a `emociones_payload`.
#  - Construye el rolling correctamente desde la DB.
#  - Idempotente (solo re-procesa pending).
# ══════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

import json
from pathlib import Path
from typing import TypeVar

import pytest
from pydantic import BaseModel

from emoparse.core.backend.base import LLMBackend, LLMResponse, TokenUsage
from emoparse.core.schemas import (
    EmocionesBatchItemSchema,
    EmocionSchema,
    ListaEmocionesBatchSchema,
)
from emoparse.pipeline.stages import EmotionsPass2Stage
from emoparse.storage.db import Database
from emoparse.storage.discursos import DiscursosRepository
from emoparse.storage.frases import FrasesRepository
from emoparse.storage.models import RunContext
from emoparse.storage.runs import RunsRepository

T = TypeVar("T", bound=BaseModel)


class _MockBackend(LLMBackend):
    def __init__(self) -> None:
        self.alias = "mock"
        self.last_user: str = ""

    def generate(
        self,
        system: str,
        user: str,
        *,
        schema: type[T] | None = None,
        max_tokens: int | None = None,
        temperature: float | None = None,
        seed: int | None = None,
        stop: list[str] | None = None,
        reset_before: bool = False,
    ) -> LLMResponse:
        self.last_user = user
        n = user.count("UNIDAD [")
        items = [
            EmocionesBatchItemSchema(unit_idx=i, emociones=[
                EmocionSchema(experienciador="orador",
                              experienciador_marca="yo",
                              tipo_emocion="esperanza_refinada",
                              tipo_configuracion="sostenido_en_sustantivos",
                              modo_existencia="realizada",
                              fuente_marca="la riqueza",
                              fuente_inferencia="riqueza",
                )
            ]) for i in range(n)
        ]
        return LLMResponse(
            parsed=ListaEmocionesBatchSchema(root=items),
            raw="(mock)",
            usage=TokenUsage(10, 5),
            latency_ms=1.0,
            model_alias=self.alias,
            cache_hit=False,
            finish_reason="stop",
        )

    def healthcheck(self) -> bool:
        return True


@pytest.fixture
def setup(tmp_path: Path) -> tuple[Database, DiscursosRepository, FrasesRepository]:
    """DB con un discurso, 3 frases. Pase 1 ya completado en las 3."""
    db = Database(tmp_path / "test.sqlite")
    runs = RunsRepository(db)
    runs.bootstrap(RunContext(run_id="t"))

    d_repo = DiscursosRepository(db)
    f_repo = FrasesRepository(db)
    d_repo.upsert_input("D1", {"titulo": "T", "contenido": "x"})
    f_repo.upsert_frases([
        ("D1", 0, "Frase cero."),
        ("D1", 1, "Frase uno."),
        ("D1", 2, "Frase dos."),
    ])
    # Pase 1 completado en todas.
    for idx, tipo in enumerate(["miedo", "esperanza", "alegria"]):
        f_repo.set_payload("D1", idx, "emociones", [{
            "experienciador": "orador",
            "experienciador_marca": "yo",
            "tipo_emocion": tipo,
            "tipo_configuracion": "sostenido_en_sustantivos",
            "modo_existencia": "realizada",
            "fuente_marca": "la riqueza",
            "fuente_inferencia": "riqueza",
        }], version="v1")
    return db, d_repo, f_repo


# ══════════════════════════════════════════════════════════════════════════════
#  Skip si no hay pase 1
# ══════════════════════════════════════════════════════════════════════════════


class TestRequiresPass1:

    def test_skips_discurso_without_pass1(self, tmp_path: Path) -> None:
        """Si ninguna frase del discurso tiene pase 1, skipea."""
        db = Database(tmp_path / "test.sqlite")
        RunsRepository(db).bootstrap(RunContext(run_id="t"))
        d_repo = DiscursosRepository(db)
        f_repo = FrasesRepository(db)
        d_repo.upsert_input("D1", {})
        f_repo.upsert_frases([("D1", 0, "x"), ("D1", 1, "y")])

        stage = EmotionsPass2Stage(
            _MockBackend(), d_repo, f_repo,
            ontologia="o", heuristicas="h",
        )
        n = stage.run_pending()
        assert n == 0
        # No marcaron nada.
        assert f_repo.list_pending("emociones_pass2", "D1") == [
            ("D1", 0), ("D1", 1)
        ]


# ══════════════════════════════════════════════════════════════════════════════
#  Persiste a la columna correcta
# ══════════════════════════════════════════════════════════════════════════════


class TestPersistence:

    def test_writes_to_pass2_column(
        self,
        setup: tuple[Database, DiscursosRepository, FrasesRepository],
    ) -> None:
        db, d_repo, f_repo = setup
        stage = EmotionsPass2Stage(
            _MockBackend(), d_repo, f_repo,
            ontologia="o", heuristicas="h",
        )
        stage.run_pending()

        # Pase 1 no se modificó.
        emos_pass1 = f_repo.get_payload("D1", 0, "emociones")
        assert emos_pass1[0]["tipo_emocion"] == "miedo"

        # Pase 2 sí tiene contenido.
        emos_pass2 = f_repo.get_payload("D1", 0, "emociones_pass2")
        assert isinstance(emos_pass2, list)
        assert emos_pass2[0]["tipo_emocion"] == "esperanza_refinada"

    def test_processes_all_3_frases(
        self,
        setup: tuple[Database, DiscursosRepository, FrasesRepository],
    ) -> None:
        db, d_repo, f_repo = setup
        stage = EmotionsPass2Stage(
            _MockBackend(), d_repo, f_repo,
            ontologia="o", heuristicas="h",
        )
        n = stage.run_pending()
        assert n == 3


# ══════════════════════════════════════════════════════════════════════════════
#  Rolling se construye correctamente
# ══════════════════════════════════════════════════════════════════════════════


class TestRolling:

    def test_user_prompt_includes_pass1_emotions_as_context(
        self,
        setup: tuple[Database, DiscursosRepository, FrasesRepository],
    ) -> None:
        """El user prompt enviado al modelo debe contener referencias a
        las emociones del pase 1 como contexto anterior."""
        db, d_repo, f_repo = setup
        backend = _MockBackend()
        stage = EmotionsPass2Stage(
            backend, d_repo, f_repo,
            ontologia="o", heuristicas="h",
        )
        stage.run_pending()

        user = backend.last_user
        # Nuestras emociones de pase 1 fueron: miedo, esperanza, alegria.
        # El rolling de las frases >0 debería mencionar las anteriores.
        assert "miedo" in user or "esperanza" in user, (
            "El rolling no incluyó las emociones del pase 1."
        )


# ══════════════════════════════════════════════════════════════════════════════
#  Idempotencia
# ══════════════════════════════════════════════════════════════════════════════


class TestIdempotence:

    def test_rerun_skips_completed(
        self,
        setup: tuple[Database, DiscursosRepository, FrasesRepository],
    ) -> None:
        db, d_repo, f_repo = setup
        stage = EmotionsPass2Stage(
            _MockBackend(), d_repo, f_repo,
            ontologia="o", heuristicas="h",
        )
        n_first = stage.run_pending()
        n_second = stage.run_pending()
        assert n_first == 3
        assert n_second == 0  # nada para hacer
