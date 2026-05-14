# ══════════════════════════════════════════════════════════════════════════════
#  tests.unit.test_domain_validators
#
#  Tests de los domain validators de coherencia semiótica.
# ══════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Any

import pytest

from emoparse.domain.validators.base import ValidationIssue
from emoparse.domain.validators.rules import (
    V01_ModoPotencialVirtualExperienciador,
    V02_FuenteNoIdentificadaConIntensidadAlta,
    V04_AforicoConIntensidadAlta,
    V05_AmbiforicaConIntensidadBaja,
    V06_VirtualConForiaAforica,
    V07_TipoFuenteActorSinFuenteNombrada,
    V08_ActorCoincideConEnunciador,
    V09_EmocionDuplicadaMismoActorMismaFrase,
    V10_ModoPotencialConExperienciadorNoEnunciatario,
)
from emoparse.domain.validators.runner import ValidationRunner
from emoparse.storage.db import Database
from emoparse.storage.validation import ValidationRepository


# ══════════════════════════════════════════════════════════════════════════════
#  Helpers
# ══════════════════════════════════════════════════════════════════════════════

def _base_kwargs(**overrides) -> dict[str, Any]:
    """Kwargs base para RowValidator.validate. Override lo que necesites."""
    defaults = dict(
        codigo="D001",
        frase_idx=0,
        emocion_idx=0,
        experienciador="el pueblo",
        tipo_emocion="alegria",
        modo_existencia="realizada",
        foria="euforico",
        dominancia="cognoscitiva",
        intensidad="alta",
        tipo_fuente="situacion",
        fuente="la victoria electoral",
        enunciador="Javier Milei",
        enunciatarios=[],
    )
    defaults.update(overrides)
    return defaults


def _make_db() -> Database:
    """DB en archivo temporal para tests del runner."""
    tmp = tempfile.mktemp(suffix=".sqlite")
    return Database(Path(tmp))


def _bootstrap_db(db: Database) -> None:
    """Crea las tablas mínimas necesarias para los tests del runner."""
    with db.transaction() as cur:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS runs (
                run_id TEXT PRIMARY KEY,
                started_at TIMESTAMP,
                finished_at TIMESTAMP,
                status TEXT DEFAULT 'running',
                knowledge_version TEXT,
                prompt_version TEXT,
                ontology_version TEXT,
                schema_version TEXT,
                config TEXT,
                notes TEXT
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS discursos (
                codigo TEXT PRIMARY KEY,
                input TEXT NOT NULL,
                summarizer_payload TEXT, summarizer_version TEXT, summarizer_error TEXT,
                metadata_payload TEXT, metadata_version TEXT, metadata_error TEXT,
                enunciation_payload TEXT, enunciation_version TEXT, enunciation_error TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS frases (
                codigo TEXT NOT NULL,
                unit_idx INTEGER NOT NULL,
                frase TEXT NOT NULL,
                actores_payload TEXT, actores_version TEXT, actores_error TEXT,
                emociones_payload TEXT, emociones_version TEXT, emociones_error TEXT,
                emociones_pass2_payload TEXT, emociones_pass2_version TEXT, emociones_pass2_error TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (codigo, unit_idx)
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS emociones (
                codigo TEXT NOT NULL,
                frase_idx INTEGER NOT NULL,
                emocion_idx INTEGER NOT NULL,
                experienciador TEXT NOT NULL,
                tipo_emocion TEXT NOT NULL,
                modo_existencia TEXT NOT NULL,
                deteccion_justificacion TEXT,
                caracterizacion_payload TEXT,
                caracterizacion_version TEXT,
                caracterizacion_error TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (codigo, frase_idx, emocion_idx)
            )
        """)


def _insert_discurso(db: Database, codigo: str, enunciador: str = "el presidente",
                     enunciatarios: list[dict] | None = None) -> None:
    enunciatarios = enunciatarios or []
    payload = json.dumps({
        "enunciador": enunciador,
        "enunciatarios": enunciatarios,
    })
    with db.transaction() as cur:
        cur.execute(
            "INSERT INTO discursos (codigo, input, enunciation_payload) VALUES (?, ?, ?)",
            (codigo, '{"titulo": "test"}', payload),
        )


def _insert_emocion(db: Database, codigo: str, frase_idx: int, emocion_idx: int,
                    experienciador: str, tipo_emocion: str, modo_existencia: str,
                    caract: dict | None = None) -> None:
    caract_json = json.dumps(caract) if caract else None
    with db.transaction() as cur:
        cur.execute(
            """
            INSERT INTO emociones
                (codigo, frase_idx, emocion_idx, experienciador, tipo_emocion,
                 modo_existencia, caracterizacion_payload)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (codigo, frase_idx, emocion_idx, experienciador, tipo_emocion,
             modo_existencia, caract_json),
        )


def _default_caract(**overrides) -> dict:
    base = dict(
        foria="euforico",
        foria_justificacion="j",
        dominancia="cognoscitiva",
        dominancia_justificacion="j",
        intensidad="alta",
        intensidad_justificacion="j",
        fuente="la situación",
        tipo_fuente="situacion",
        fuente_justificacion="j",
    )
    base.update(overrides)
    return base


# ══════════════════════════════════════════════════════════════════════════════
#  V-01
# ══════════════════════════════════════════════════════════════════════════════

class TestV01:
    v = V01_ModoPotencialVirtualExperienciador()

    def test_dispara_cuando_virtual_y_experienciador_es_enunciador(self):
        issues = self.v.validate(**_base_kwargs(
            modo_existencia="virtual",
            experienciador="Javier Milei",
            enunciador="Javier Milei",
        ))
        assert len(issues) == 1
        assert issues[0].validator_id == "V-01"

    def test_dispara_subcadena_parcial(self):
        """El experienciador contiene al enunciador como subcadena."""
        issues = self.v.validate(**_base_kwargs(
            modo_existencia="potencial",
            experienciador="el presidente Milei",
            enunciador="Milei",
        ))
        assert len(issues) == 1

    def test_no_dispara_para_modo_realizada(self):
        issues = self.v.validate(**_base_kwargs(
            modo_existencia="realizada",
            experienciador="Javier Milei",
            enunciador="Javier Milei",
        ))
        assert issues == []

    def test_no_dispara_si_enunciador_no_identificado(self):
        issues = self.v.validate(**_base_kwargs(
            modo_existencia="virtual",
            experienciador="el presidente",
            enunciador="no identificado",
        ))
        assert issues == []

    def test_no_dispara_si_experienciador_distinto(self):
        issues = self.v.validate(**_base_kwargs(
            modo_existencia="virtual",
            experienciador="la oposición",
            enunciador="Javier Milei",
        ))
        assert issues == []


# ══════════════════════════════════════════════════════════════════════════════
#  V-02
# ══════════════════════════════════════════════════════════════════════════════

class TestV02:
    v = V02_FuenteNoIdentificadaConIntensidadAlta()

    def test_dispara_cuando_no_identificada_y_alta(self):
        issues = self.v.validate(**_base_kwargs(
            tipo_fuente="no_se_identifica",
            intensidad="alta",
        ))
        assert len(issues) == 1
        assert issues[0].validator_id == "V-02"

    def test_no_dispara_si_intensidad_baja(self):
        issues = self.v.validate(**_base_kwargs(
            tipo_fuente="no_se_identifica",
            intensidad="baja",
        ))
        assert issues == []

    def test_no_dispara_si_fuente_identificada(self):
        issues = self.v.validate(**_base_kwargs(
            tipo_fuente="actor",
            intensidad="alta",
        ))
        assert issues == []


# ══════════════════════════════════════════════════════════════════════════════
#  V-04
# ══════════════════════════════════════════════════════════════════════════════

class TestV04:
    v = V04_AforicoConIntensidadAlta()

    def test_dispara_aforico_con_alta(self):
        issues = self.v.validate(**_base_kwargs(
            foria="aforico",
            intensidad="alta",
        ))
        assert len(issues) == 1
        assert issues[0].validator_id == "V-04"

    def test_no_dispara_aforico_con_baja(self):
        issues = self.v.validate(**_base_kwargs(
            foria="aforico",
            intensidad="baja",
        ))
        assert issues == []

    def test_no_dispara_euforico_con_alta(self):
        issues = self.v.validate(**_base_kwargs(
            foria="euforico",
            intensidad="alta",
        ))
        assert issues == []


# ══════════════════════════════════════════════════════════════════════════════
#  V-05
# ══════════════════════════════════════════════════════════════════════════════

class TestV05:
    v = V05_AmbiforicaConIntensidadBaja()

    def test_dispara_ambiforico_con_baja(self):
        issues = self.v.validate(**_base_kwargs(
            foria="ambiforico",
            intensidad="baja",
        ))
        assert len(issues) == 1
        assert issues[0].validator_id == "V-05"

    def test_no_dispara_ambiforico_con_alta(self):
        issues = self.v.validate(**_base_kwargs(
            foria="ambiforico",
            intensidad="alta",
        ))
        assert issues == []

    def test_no_dispara_disforico_con_baja(self):
        issues = self.v.validate(**_base_kwargs(
            foria="disforico",
            intensidad="baja",
        ))
        assert issues == []


# ══════════════════════════════════════════════════════════════════════════════
#  V-06
# ══════════════════════════════════════════════════════════════════════════════

class TestV06:
    v = V06_VirtualConForiaAforica()

    def test_dispara_virtual_aforico(self):
        issues = self.v.validate(**_base_kwargs(
            modo_existencia="virtual",
            foria="aforico",
        ))
        assert len(issues) == 1
        assert issues[0].validator_id == "V-06"

    def test_no_dispara_virtual_disforico(self):
        issues = self.v.validate(**_base_kwargs(
            modo_existencia="virtual",
            foria="disforico",
        ))
        assert issues == []

    def test_no_dispara_realizada_aforico(self):
        """Afórico en modo realizada no es incoherente (observación neutral)."""
        issues = self.v.validate(**_base_kwargs(
            modo_existencia="realizada",
            foria="aforico",
        ))
        assert issues == []


# ══════════════════════════════════════════════════════════════════════════════
#  V-07
# ══════════════════════════════════════════════════════════════════════════════

class TestV07:
    v = V07_TipoFuenteActorSinFuenteNombrada()

    def test_dispara_tipo_actor_fuente_no_identificada(self):
        issues = self.v.validate(**_base_kwargs(
            tipo_fuente="actor",
            fuente="no identificado",
        ))
        assert len(issues) == 1
        assert issues[0].validator_id == "V-07"

    def test_dispara_tipo_actor_fuente_sentinel_alternativo(self):
        issues = self.v.validate(**_base_kwargs(
            tipo_fuente="actor",
            fuente="no_se_identifica",
        ))
        assert len(issues) == 1

    def test_no_dispara_tipo_actor_con_fuente_nombrada(self):
        issues = self.v.validate(**_base_kwargs(
            tipo_fuente="actor",
            fuente="el ministro de economía",
        ))
        assert issues == []

    def test_no_dispara_tipo_situacion_sin_fuente(self):
        """Otro tipo de fuente no activa la regla aunque fuente sea genérica."""
        issues = self.v.validate(**_base_kwargs(
            tipo_fuente="situacion",
            fuente="no identificado",
        ))
        assert issues == []


# ══════════════════════════════════════════════════════════════════════════════
#  V-08
# ══════════════════════════════════════════════════════════════════════════════

class TestV08:
    v = V08_ActorCoincideConEnunciador()

    def _emo(self, experienciador: str, tipo: str = "miedo", modo: str = "realizada",
             fi: int = 0, ei: int = 0) -> dict:
        return dict(
            frase_idx=fi, emocion_idx=ei,
            experienciador=experienciador,
            tipo_emocion=tipo,
            modo_existencia=modo,
        )

    def test_dispara_cuando_experienciador_es_enunciador(self):
        issues = self.v.validate(
            codigo="D001",
            emociones=[self._emo("Milei")],
            enunciador="Milei",
            enunciatarios=[],
        )
        assert len(issues) == 1
        assert issues[0].validator_id == "V-08"

    def test_no_dispara_si_experienciador_diferente(self):
        issues = self.v.validate(
            codigo="D001",
            emociones=[self._emo("la oposición")],
            enunciador="Milei",
            enunciatarios=[],
        )
        assert issues == []

    def test_no_dispara_si_enunciador_no_identificado(self):
        issues = self.v.validate(
            codigo="D001",
            emociones=[self._emo("Milei")],
            enunciador="no identificado",
            enunciatarios=[],
        )
        assert issues == []

    def test_multiples_emociones_con_enunciador(self):
        """Cada emoción con experienciador=enunciador genera su propio issue."""
        issues = self.v.validate(
            codigo="D001",
            emociones=[
                self._emo("Milei", fi=0, ei=0),
                self._emo("la gente", fi=0, ei=1),
                self._emo("Milei", fi=1, ei=0),
            ],
            enunciador="Milei",
            enunciatarios=[],
        )
        assert len(issues) == 2


# ══════════════════════════════════════════════════════════════════════════════
#  V-09
# ══════════════════════════════════════════════════════════════════════════════

class TestV09:
    v = V09_EmocionDuplicadaMismoActorMismaFrase()

    def _emo(self, fi: int, ei: int, tipo: str, exp: str) -> dict:
        return dict(
            frase_idx=fi, emocion_idx=ei,
            tipo_emocion=tipo, experienciador=exp,
            modo_existencia="realizada",
        )

    def test_dispara_con_duplicado(self):
        issues = self.v.validate(
            codigo="D001",
            emociones=[
                self._emo(0, 0, "miedo", "Juan"),
                self._emo(0, 1, "miedo", "Juan"),  # duplicado
            ],
            enunciador="x",
            enunciatarios=[],
        )
        assert len(issues) == 1
        assert issues[0].validator_id == "V-09"
        assert issues[0].contexto["ocurrencias"] == 2

    def test_no_dispara_misma_emocion_diferente_actor(self):
        issues = self.v.validate(
            codigo="D001",
            emociones=[
                self._emo(0, 0, "miedo", "Juan"),
                self._emo(0, 1, "miedo", "María"),
            ],
            enunciador="x",
            enunciatarios=[],
        )
        assert issues == []

    def test_no_dispara_misma_emocion_diferente_frase(self):
        """Mismo actor + misma emoción en FRASES distintas no es duplicado."""
        issues = self.v.validate(
            codigo="D001",
            emociones=[
                self._emo(0, 0, "miedo", "Juan"),
                self._emo(1, 0, "miedo", "Juan"),  # frase distinta: ok
            ],
            enunciador="x",
            enunciatarios=[],
        )
        assert issues == []

    def test_normalizacion_case_insensitive(self):
        """Variantes de capitalización se tratan como duplicado."""
        issues = self.v.validate(
            codigo="D001",
            emociones=[
                self._emo(0, 0, "Miedo", "Juan"),
                self._emo(0, 1, "miedo", "juan"),
            ],
            enunciador="x",
            enunciatarios=[],
        )
        assert len(issues) == 1


# ══════════════════════════════════════════════════════════════════════════════
#  V-10
# ══════════════════════════════════════════════════════════════════════════════

class TestV10:
    v = V10_ModoPotencialConExperienciadorNoEnunciatario()

    def _enun(self, actor: str, tipo: str = "prodestinatario") -> dict:
        return {"actor": actor, "tipo": tipo, "justificacion": "x"}

    def _emo(self, fi: int, ei: int, exp: str, modo: str = "potencial") -> dict:
        return dict(
            frase_idx=fi, emocion_idx=ei,
            experienciador=exp, modo_existencia=modo,
            tipo_emocion="orgullo",
        )

    def test_dispara_cuando_experienciador_no_es_enunciatario(self):
        issues = self.v.validate(
            codigo="D001",
            emociones=[self._emo(0, 0, "el establishment")],
            enunciador="Milei",
            enunciatarios=[self._enun("los libertarios")],
        )
        assert len(issues) == 1
        assert issues[0].validator_id == "V-10"

    def test_no_dispara_cuando_experienciador_es_enunciatario(self):
        issues = self.v.validate(
            codigo="D001",
            emociones=[self._emo(0, 0, "los libertarios")],
            enunciador="Milei",
            enunciatarios=[self._enun("los libertarios")],
        )
        assert issues == []

    def test_no_dispara_sin_enunciatarios(self):
        """Sin enunciatarios no se puede comparar: no dispara."""
        issues = self.v.validate(
            codigo="D001",
            emociones=[self._emo(0, 0, "la casta")],
            enunciador="Milei",
            enunciatarios=[],
        )
        assert issues == []

    def test_no_dispara_modo_no_potencial(self):
        """La regla solo aplica a modo potencial."""
        issues = self.v.validate(
            codigo="D001",
            emociones=[self._emo(0, 0, "la casta", modo="virtual")],
            enunciador="Milei",
            enunciatarios=[self._enun("los libertarios")],
        )
        assert issues == []

    def test_coincidencia_parcial_no_dispara(self):
        """El enunciatario es subcadena del experienciador: coherente."""
        issues = self.v.validate(
            codigo="D001",
            emociones=[self._emo(0, 0, "todos los argentinos")],
            enunciador="Milei",
            enunciatarios=[self._enun("los argentinos")],
        )
        assert issues == []


# ══════════════════════════════════════════════════════════════════════════════
#  ValidationRepository
# ══════════════════════════════════════════════════════════════════════════════

class TestValidationRepository:

    def _make_issue(self, codigo: str = "D001", validator_id: str = "V-04",
                    frase_idx: int | None = 0, emocion_idx: int | None = 0) -> ValidationIssue:
        return ValidationIssue(
            validator_id=validator_id,
            mensaje="test issue",
            codigo=codigo,
            frase_idx=frase_idx,
            emocion_idx=emocion_idx,
            contexto={"key": "val"},
        )

    def test_save_and_list(self):
        db = _make_db()
        _bootstrap_db(db)
        repo = ValidationRepository(db)

        issues = [self._make_issue(), self._make_issue(validator_id="V-09")]
        repo.save_issues(issues)

        listed = repo.list_issues()
        assert len(listed) == 2

    def test_count_total(self):
        db = _make_db()
        _bootstrap_db(db)
        repo = ValidationRepository(db)
        repo.save_issues([self._make_issue()] * 3)
        assert repo.count_total() == 3

    def test_count_by_validator(self):
        db = _make_db()
        _bootstrap_db(db)
        repo = ValidationRepository(db)
        repo.save_issues([
            self._make_issue(validator_id="V-04"),
            self._make_issue(validator_id="V-04"),
            self._make_issue(validator_id="V-09"),
        ])
        counts = repo.count_by_validator()
        assert counts["V-04"] == 2
        assert counts["V-09"] == 1

    def test_delete_issues_for_codigo(self):
        db = _make_db()
        _bootstrap_db(db)
        repo = ValidationRepository(db)
        repo.save_issues([
            self._make_issue(codigo="D001"),
            self._make_issue(codigo="D002"),
        ])
        repo.delete_issues_for_codigo("D001")
        listed = repo.list_issues()
        assert all(i["codigo"] != "D001" for i in listed)
        assert len(listed) == 1

    def test_filter_by_codigo(self):
        db = _make_db()
        _bootstrap_db(db)
        repo = ValidationRepository(db)
        repo.save_issues([
            self._make_issue(codigo="D001"),
            self._make_issue(codigo="D002"),
        ])
        listed = repo.list_issues(codigo="D001")
        assert len(listed) == 1
        assert listed[0]["codigo"] == "D001"

    def test_delete_all(self):
        db = _make_db()
        _bootstrap_db(db)
        repo = ValidationRepository(db)
        repo.save_issues([self._make_issue()] * 5)
        repo.delete_all()
        assert repo.count_total() == 0

    def test_contexto_roundtrip(self):
        """El contexto JSON se serializa y deserializa correctamente."""
        db = _make_db()
        _bootstrap_db(db)
        repo = ValidationRepository(db)
        issue = ValidationIssue(
            validator_id="V-04",
            mensaje="x",
            codigo="D001",
            frase_idx=1,
            emocion_idx=2,
            contexto={"foria": "aforico", "intensidad": "alta", "n": 42},
        )
        repo.save_issues([issue])
        listed = repo.list_issues()
        assert listed[0]["contexto"] == {"foria": "aforico", "intensidad": "alta", "n": 42}


# ══════════════════════════════════════════════════════════════════════════════
#  ValidationRunner (integración con DB en memoria)
# ══════════════════════════════════════════════════════════════════════════════

class TestValidationRunner:

    def _setup_db_with_emocion(
        self,
        codigo: str = "D001",
        experienciador: str = "la oposición",
        tipo_emocion: str = "miedo",
        modo_existencia: str = "realizada",
        enunciador: str = "el presidente",
        enunciatarios: list[dict] | None = None,
        caract: dict | None = None,
    ) -> Database:
        db = _make_db()
        _bootstrap_db(db)
        _insert_discurso(db, codigo, enunciador, enunciatarios or [])
        _insert_emocion(
            db, codigo, 0, 0, experienciador, tipo_emocion, modo_existencia,
            caract=caract or _default_caract(),
        )
        return db

    def test_runner_sin_issues(self):
        db = self._setup_db_with_emocion(
            experienciador="la oposición",
            enunciador="el presidente",
            caract=_default_caract(foria="euforico", intensidad="alta",
                                   tipo_fuente="situacion"),
        )
        runner = ValidationRunner(db)
        issues = runner.run()
        assert issues == []

    def test_runner_detecta_v04(self):
        """V-04: afórico + alta en DB real."""
        db = self._setup_db_with_emocion(
            caract=_default_caract(foria="aforico", intensidad="alta"),
        )
        runner = ValidationRunner(db)
        issues = runner.run()
        assert any(i.validator_id == "V-04" for i in issues)

    def test_runner_detecta_v08(self):
        """V-08: experienciador == enunciador."""
        db = self._setup_db_with_emocion(
            experienciador="el presidente",
            enunciador="el presidente",
            caract=_default_caract(),
        )
        runner = ValidationRunner(db)
        issues = runner.run()
        assert any(i.validator_id == "V-08" for i in issues)

    def test_runner_omite_emociones_sin_caracterizacion(self):
        """Emociones sin caracterizacion_payload no generan issues (no hay datos)."""
        db = _make_db()
        _bootstrap_db(db)
        _insert_discurso(db, "D001")
        _insert_emocion(db, "D001", 0, 0, "la oposición", "miedo", "realizada",
                        caract=None)  # sin caracterización
        runner = ValidationRunner(db)
        issues = runner.run()
        assert issues == []

    def test_runner_persiste_issues_en_db(self):
        """Las issues se guardan en la tabla validation_issues."""
        db = self._setup_db_with_emocion(
            caract=_default_caract(foria="aforico", intensidad="alta"),
        )
        runner = ValidationRunner(db)
        runner.run()

        repo = ValidationRepository(db)
        assert repo.count_total() > 0

    def test_runner_idempotente(self):
        """Dos ejecuciones consecutivas no duplican issues."""
        db = self._setup_db_with_emocion(
            caract=_default_caract(foria="aforico", intensidad="alta"),
        )
        runner = ValidationRunner(db)
        runner.run()
        runner.run()  # segunda vez

        repo = ValidationRepository(db)
        count_after_second = repo.count_total()

        runner.run()  # tercera vez
        assert repo.count_total() == count_after_second

    def test_runner_sin_emociones_caracterizadas(self):
        """Si no hay nada caracterizado, devuelve lista vacía sin error."""
        db = _make_db()
        _bootstrap_db(db)
        runner = ValidationRunner(db)
        issues = runner.run()
        assert issues == []
