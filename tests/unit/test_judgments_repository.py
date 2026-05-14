# ══════════════════════════════════════════════════════════════════════════════
#  tests.unit.test_judgments_repository
#
#  Tests del JudgmentsRepository.
# ══════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

import json
from pathlib import Path

import pytest

from emoparse.storage.db import Database
from emoparse.storage.discursos import DiscursosRepository
from emoparse.storage.emociones import EmocionesRepository
from emoparse.storage.frases import FrasesRepository
from emoparse.storage.judgments import JudgmentsRepository
from emoparse.storage.models import RunContext, Versions
from emoparse.storage.runs import RunsRepository


@pytest.fixture
def db(tmp_path: Path) -> Database:
    """DB con schema completo + datos mínimos: un discurso, una frase,
    una emoción ya caracterizada (lista para judge)."""
    db = Database(tmp_path / "test.sqlite")
    runs_repo = RunsRepository(db)
    runs_repo.bootstrap(RunContext(run_id="r1", versions=Versions()))

    d_repo = DiscursosRepository(db)
    f_repo = FrasesRepository(db)
    e_repo = EmocionesRepository(db)

    d_repo.upsert_input("D1", {"titulo": "T", "contenido": "C"})
    f_repo.upsert_frases([("D1", 0, "frase de prueba")])
    e_repo.upsert_emociones([{
        "codigo": "D1", "frase_idx": 0, "emocion_idx": 0,
        "experienciador": "X", "tipo_emocion": "miedo",
        "modo_existencia": "realizada",
        "deteccion_justificacion": "j",
    }])
    # Caracterización completa (necesaria para que sea pending de judge).
    e_repo.set_caracterizacion(
        "D1", 0, 0,
        payload={
            "foria": "disforico", "foria_justificacion": "j",
            "dominancia": "cognoscitiva", "dominancia_justificacion": "j",
            "intensidad": "alta", "intensidad_justificacion": "j",
            "fuente": "X", "tipo_fuente": "actor",
            "fuente_justificacion": "j",
        },
    )
    return db


class TestSetAndGet:

    def test_set_and_get_coherent(self, db: Database) -> None:
        repo = JudgmentsRepository(db)
        repo.set_judgment(
            "D1", 0, 0,
            coherente=True, issues="no identificado", confianza="alta",
            version="v1",
        )
        j = repo.get_judgment("D1", 0, 0)
        assert j is not None
        assert j["coherente"] is True
        assert j["issues"] == "no identificado"
        assert j["confianza"] == "alta"
        assert j["judge_version"] == "v1"
        assert j["judge_error"] is None

    def test_set_and_get_incoherent(self, db: Database) -> None:
        repo = JudgmentsRepository(db)
        repo.set_judgment(
            "D1", 0, 0,
            coherente=False, issues="foria no encaja", confianza="media",
        )
        j = repo.get_judgment("D1", 0, 0)
        assert j["coherente"] is False
        assert j["issues"] == "foria no encaja"

    def test_get_missing_returns_none(self, db: Database) -> None:
        repo = JudgmentsRepository(db)
        assert repo.get_judgment("D1", 0, 0) is None

    def test_set_error_clears_verdict(self, db: Database) -> None:
        repo = JudgmentsRepository(db)
        repo.set_judgment("D1", 0, 0,
                          coherente=True, issues="x", confianza="alta")
        repo.set_error("D1", 0, 0, "boom")
        j = repo.get_judgment("D1", 0, 0)
        assert j["coherente"] is None
        assert j["judge_error"] == "boom"

    def test_upsert_overwrites(self, db: Database) -> None:
        repo = JudgmentsRepository(db)
        repo.set_judgment("D1", 0, 0,
                          coherente=False, issues="a", confianza="baja")
        repo.set_judgment("D1", 0, 0,
                          coherente=True, issues="no identificado", confianza="alta")
        j = repo.get_judgment("D1", 0, 0)
        assert j["coherente"] is True
        assert j["confianza"] == "alta"


class TestListPending:

    def test_pending_includes_characterized_without_judgment(
        self, db: Database
    ) -> None:
        """Una emoción caracterizada pero sin row en `judgments` → pending."""
        repo = JudgmentsRepository(db)
        pending = repo.list_pending()
        assert ("D1", 0, 0) in pending

    def test_pending_excludes_judged(self, db: Database) -> None:
        repo = JudgmentsRepository(db)
        repo.set_judgment("D1", 0, 0,
                          coherente=True, issues="x", confianza="alta")
        assert ("D1", 0, 0) not in repo.list_pending()

    def test_pending_excludes_failed(self, db: Database) -> None:
        """Errores no se reintentan automáticamente (consistente con el
        resto del proyecto)."""
        repo = JudgmentsRepository(db)
        repo.set_error("D1", 0, 0, "boom")
        assert ("D1", 0, 0) not in repo.list_pending()

    def test_pending_filter_by_codigo(self, db: Database) -> None:
        repo = JudgmentsRepository(db)
        # Otro discurso con su emoción.
        d_repo = DiscursosRepository(db)
        f_repo = FrasesRepository(db)
        e_repo = EmocionesRepository(db)
        d_repo.upsert_input("D2", {"titulo": "T2", "contenido": "C2"})
        f_repo.upsert_frases([("D2", 0, "otra")])
        e_repo.upsert_emociones([{
            "codigo": "D2", "frase_idx": 0, "emocion_idx": 0,
            "experienciador": "Y", "tipo_emocion": "alegria",
            "modo_existencia": "realizada",
        }])
        e_repo.set_caracterizacion(
            "D2", 0, 0,
            payload={
                "foria": "euforico", "foria_justificacion": "j",
                "dominancia": "mixta", "dominancia_justificacion": "j",
                "intensidad": "alta", "intensidad_justificacion": "j",
                "fuente": "Y", "tipo_fuente": "actor",
                "fuente_justificacion": "j",
            },
        )

        only_d2 = repo.list_pending(codigo="D2")
        assert ("D2", 0, 0) in only_d2
        assert ("D1", 0, 0) not in only_d2

    def test_pending_excludes_uncharacterized(self, tmp_path: Path) -> None:
        """Una emoción SIN caracterización no está pending de judge."""
        db = Database(tmp_path / "test.sqlite")
        RunsRepository(db).bootstrap(
            RunContext(run_id="r1", versions=Versions())
        )
        d_repo = DiscursosRepository(db)
        f_repo = FrasesRepository(db)
        e_repo = EmocionesRepository(db)

        d_repo.upsert_input("D1", {"titulo": "T", "contenido": "C"})
        f_repo.upsert_frases([("D1", 0, "frase")])
        e_repo.upsert_emociones([{
            "codigo": "D1", "frase_idx": 0, "emocion_idx": 0,
            "experienciador": "X", "tipo_emocion": "miedo",
            "modo_existencia": "realizada",
        }])
        # No setear caracterización.

        repo = JudgmentsRepository(db)
        assert repo.list_pending() == []


class TestClearErrors:

    def test_clear_errors_makes_pending_again(self, db: Database) -> None:
        repo = JudgmentsRepository(db)
        repo.set_error("D1", 0, 0, "boom")
        assert repo.clear_errors() == 1
        # Ahora list_pending debe verlo otra vez.
        assert ("D1", 0, 0) in repo.list_pending()


class TestCounts:

    def test_count_by_coherence(self, db: Database) -> None:
        repo = JudgmentsRepository(db)
        repo.set_judgment("D1", 0, 0,
                          coherente=True, issues="x", confianza="alta")
        c = repo.count_by_coherence()
        assert c == {"coherent": 1, "incoherent": 0, "errors": 0, "total": 1}

    def test_count_filters_by_codigo(self, db: Database) -> None:
        repo = JudgmentsRepository(db)
        repo.set_judgment("D1", 0, 0,
                          coherente=False, issues="x", confianza="baja")
        # Codigo inexistente → 0.
        c = repo.count_by_coherence(codigo="OTRO")
        assert c["total"] == 0
