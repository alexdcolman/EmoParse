# ══════════════════════════════════════════════════════════════════════════════
#  tests.unit.test_storage_repos
#
#  Tests de los repositorios de payload: discursos, frases, emociones.
# ══════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

from pathlib import Path

import pytest

from emoparse.storage.db import Database
from emoparse.storage.discursos import DiscursosRepository
from emoparse.storage.emociones import EmocionesRepository
from emoparse.storage.frases import FrasesRepository
from emoparse.storage.models import RunContext
from emoparse.storage.runs import RunsRepository


@pytest.fixture
def db(tmp_path: Path) -> Database:
    """Database con bootstrap completo. Lista para usar."""
    db = Database(tmp_path / "test.sqlite")
    runs = RunsRepository(db)
    runs.bootstrap(RunContext(run_id="test"))
    return db


# ══════════════════════════════════════════════════════════════════════════════
#  DiscursosRepository
# ══════════════════════════════════════════════════════════════════════════════


class TestDiscursosUpsert:

    def test_upsert_input_creates_row(self, db: Database) -> None:
        repo = DiscursosRepository(db)
        repo.upsert_input("DISC_A", {"titulo": "Asunción", "contenido": "texto"})

        loaded = repo.get_input("DISC_A")
        assert loaded["titulo"] == "Asunción"

    def test_upsert_input_updates_existing(self, db: Database) -> None:
        repo = DiscursosRepository(db)
        repo.upsert_input("DISC_A", {"titulo": "v1"})
        repo.upsert_input("DISC_A", {"titulo": "v2"})

        loaded = repo.get_input("DISC_A")
        assert loaded["titulo"] == "v2"

    def test_upsert_inputs_bulk(self, db: Database) -> None:
        repo = DiscursosRepository(db)
        repo.upsert_inputs([
            ("DISC_A", {"x": 1}),
            ("DISC_B", {"x": 2}),
            ("DISC_C", {"x": 3}),
        ])
        assert sorted(repo.list_codigos()) == ["DISC_A", "DISC_B", "DISC_C"]


class TestDiscursosStages:

    def test_set_payload_marks_completed(self, db: Database) -> None:
        repo = DiscursosRepository(db)
        repo.upsert_input("A", {"x": 1})
        assert repo.list_pending("metadata") == ["A"]

        repo.set_payload("A", "metadata", {"tipo": "asuncion"}, version="v1")
        assert repo.list_pending("metadata") == []
        assert repo.list_completed("metadata") == ["A"]

    def test_get_payload_round_trip(self, db: Database) -> None:
        repo = DiscursosRepository(db)
        repo.upsert_input("A", {"x": 1})
        payload = {"tipo_discurso": "asuncion", "ciudad": "Buenos Aires"}
        repo.set_payload("A", "metadata", payload, version="v1")

        loaded = repo.get_payload("A", "metadata")
        assert loaded == payload

    def test_get_payload_returns_none_if_pending(self, db: Database) -> None:
        repo = DiscursosRepository(db)
        repo.upsert_input("A", {"x": 1})
        assert repo.get_payload("A", "metadata") is None

    def test_set_error(self, db: Database) -> None:
        """set_error marca como falla terminal: no aparece en list_pending,
        sí en list_failed. Para reintentar hay que clear_errors() explícito.
        """
        repo = DiscursosRepository(db)
        repo.upsert_input("A", {"x": 1})
        repo.set_error("A", "metadata", "BackendTimeout")

        assert repo.list_pending("metadata") == []
        assert repo.list_failed("metadata") == ["A"]
        assert repo.get_payload("A", "metadata") is None

    def test_clear_errors_restores_pending(self, db: Database) -> None:
        """clear_errors() vuelve a poner los failed como pending."""
        repo = DiscursosRepository(db)
        repo.upsert_input("A", {"x": 1})
        repo.set_error("A", "metadata", "Timeout")
        assert repo.list_pending("metadata") == []  # no es pending

        n = repo.clear_errors("metadata")
        assert n == 1
        # Ahora sí es pending.
        assert repo.list_pending("metadata") == ["A"]
        assert repo.list_failed("metadata") == []

    def test_set_error_then_set_payload_clears_error(self, db: Database) -> None:
        """Reintento exitoso: error se limpia, payload se setea."""
        repo = DiscursosRepository(db)
        repo.upsert_input("A", {"x": 1})
        repo.set_error("A", "metadata", "Timeout")
        repo.set_payload("A", "metadata", {"x": "ok"}, version="v1")

        loaded = repo.get_payload("A", "metadata")
        assert loaded == {"x": "ok"}

    def test_invalid_stage_raises(self, db: Database) -> None:
        repo = DiscursosRepository(db)
        with pytest.raises(ValueError, match="inválida"):
            repo.set_payload("A", "metadta", {}, version="v1")  # type: ignore[arg-type]


class TestDiscursosResumability:

    def test_partial_completion(self, db: Database) -> None:
        """5 discursos, 2 procesados, 3 pendientes."""
        repo = DiscursosRepository(db)
        for code in ["A", "B", "C", "D", "E"]:
            repo.upsert_input(code, {})
        repo.set_payload("A", "metadata", {}, version="v1")
        repo.set_payload("C", "metadata", {}, version="v1")

        assert sorted(repo.list_completed("metadata")) == ["A", "C"]
        assert sorted(repo.list_pending("metadata")) == ["B", "D", "E"]


# ══════════════════════════════════════════════════════════════════════════════
#  FrasesRepository
# ══════════════════════════════════════════════════════════════════════════════


class TestFrases:

    def test_upsert_and_get(self, db: Database) -> None:
        DiscursosRepository(db).upsert_input("A", {})
        repo = FrasesRepository(db)
        repo.upsert_frase("A", 0, "primera frase")

        assert repo.get_frase("A", 0) == "primera frase"

    def test_bulk_insert(self, db: Database) -> None:
        DiscursosRepository(db).upsert_input("A", {})
        repo = FrasesRepository(db)
        repo.upsert_frases([
            ("A", 0, "frase 0"),
            ("A", 1, "frase 1"),
            ("A", 2, "frase 2"),
        ])
        frases = repo.list_frases_of_discurso("A")
        assert frases == [(0, "frase 0"), (1, "frase 1"), (2, "frase 2")]

    def test_payload_per_unit_idx(self, db: Database) -> None:
        DiscursosRepository(db).upsert_input("A", {})
        repo = FrasesRepository(db)
        repo.upsert_frase("A", 0, "x")
        repo.upsert_frase("A", 1, "y")

        repo.set_payload("A", 0, "actores", [{"actor": "X"}], version="v1")
        # unit_idx=1 sigue pending.
        assert repo.list_pending("actores", codigo="A") == [("A", 1)]

        loaded = repo.get_payload("A", 0, "actores")
        assert loaded == [{"actor": "X"}]

    def test_pending_across_discursos(self, db: Database) -> None:
        d_repo = DiscursosRepository(db)
        f_repo = FrasesRepository(db)
        d_repo.upsert_input("A", {})
        d_repo.upsert_input("B", {})
        f_repo.upsert_frases([
            ("A", 0, "a0"), ("A", 1, "a1"),
            ("B", 0, "b0"),
        ])
        f_repo.set_payload("A", 0, "actores", [], version="v1")

        # Sin filtro: 2 pending (A:1, B:0).
        all_pending = sorted(f_repo.list_pending("actores"))
        assert all_pending == [("A", 1), ("B", 0)]
        # Con filtro: solo de A.
        a_pending = f_repo.list_pending("actores", codigo="A")
        assert a_pending == [("A", 1)]

    def test_fk_cascade_delete(self, db: Database) -> None:
        """Borrar un discurso borra sus frases (ON DELETE CASCADE)."""
        d_repo = DiscursosRepository(db)
        f_repo = FrasesRepository(db)
        d_repo.upsert_input("A", {})
        f_repo.upsert_frases([("A", 0, "x"), ("A", 1, "y")])

        db.execute("DELETE FROM discursos WHERE codigo = 'A'")
        assert f_repo.list_frases_of_discurso("A") == []


# ══════════════════════════════════════════════════════════════════════════════
#  EmocionesRepository
# ══════════════════════════════════════════════════════════════════════════════


class TestEmociones:

    @pytest.fixture
    def emos_setup(self, db: Database) -> Database:
        """Setup con un discurso, una frase, dos emociones explotadas."""
        d_repo = DiscursosRepository(db)
        f_repo = FrasesRepository(db)
        d_repo.upsert_input("A", {})
        f_repo.upsert_frase("A", 0, "frase con dos emociones")
        return db

    def test_explode_emociones(self, emos_setup: Database) -> None:
        repo = EmocionesRepository(emos_setup)
        repo.upsert_emociones([
            {
                "codigo": "A", "frase_idx": 0, "emocion_idx": 0,
                "experienciador": "orador", "tipo_emocion": "miedo",
                "modo_existencia": "realizada",
                "deteccion_justificacion": "tiembla",
            },
            {
                "codigo": "A", "frase_idx": 0, "emocion_idx": 1,
                "experienciador": "pueblo", "tipo_emocion": "esperanza",
                "modo_existencia": "potencial",
            },
        ])
        emos = repo.list_emociones_of_discurso("A")
        assert len(emos) == 2
        assert emos[0]["tipo_emocion"] == "miedo"
        assert emos[1]["tipo_emocion"] == "esperanza"

    def test_caracterizacion_pending(self, emos_setup: Database) -> None:
        repo = EmocionesRepository(emos_setup)
        repo.upsert_emociones([
            {"codigo": "A", "frase_idx": 0, "emocion_idx": 0,
             "experienciador": "x", "tipo_emocion": "miedo",
             "modo_existencia": "realizada"},
        ])
        pending = repo.list_pending_caracterizacion("A")
        assert pending == [("A", 0, 0)]

        repo.set_caracterizacion(
            "A", 0, 0,
            payload={"foria": "disforico"},
            version="v1",
        )
        assert repo.list_pending_caracterizacion("A") == []

    def test_set_caracterizacion_round_trip(self, emos_setup: Database) -> None:
        repo = EmocionesRepository(emos_setup)
        repo.upsert_emociones([
            {"codigo": "A", "frase_idx": 0, "emocion_idx": 0,
             "experienciador": "x", "tipo_emocion": "miedo",
             "modo_existencia": "realizada"},
        ])
        payload = {"foria": "disforico", "intensidad": "alta"}
        repo.set_caracterizacion("A", 0, 0, payload=payload, version="v1")

        emos = repo.list_emociones_of_discurso("A")
        import json
        loaded = json.loads(emos[0]["caracterizacion_payload"])
        assert loaded == payload
