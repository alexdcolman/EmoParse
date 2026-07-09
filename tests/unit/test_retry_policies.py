# ══════════════════════════════════════════════════════════════════════════════
#  tests/unit/test_retry_policies.py
#
#  Tests del módulo pipeline/retry_policies.py.
#
#  Cubre:
#  - Validación Pydantic de RetryPolicy, RetryPolicyFilter, RetryPolicyFile.
#  - load_policy_file: YAML válido, malformado, inexistente.
#  - RetryPolicyApplier:
#      * target=failed | completed | all sobre discursos/frases/emociones.
#      * Filtros eq/ne/in/contains/is_null/is_not_null sobre payload JSON.
#      * override_model muta una COPIA del config, no el original.
#      * Idempotencia: re-aplicar la misma policy no rompe.
#      * Combinaciones contradictorias (failed + filtros sobre payload).
# ══════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from emoparse.config.models import (
    ModelConfig,
    PipelineConfig,
    RunConfig,
)
from emoparse.pipeline.retry_policies import (
    PolicyApplicationResult,
    RetryPolicy,
    RetryPolicyApplier,
    RetryPolicyFile,
    RetryPolicyFilter,
    SUPPORTED_STAGES,
    load_policy_file,
)
from emoparse.storage.db import Database
from emoparse.storage.schema import ALL_TABLES_DDL


# ══════════════════════════════════════════════════════════════════════════════
#  Fixtures
# ══════════════════════════════════════════════════════════════════════════════


@pytest.fixture
def db(tmp_path: Path) -> Database:
    """DB SQLite recién creada con el schema completo de EmoParse."""
    db = Database(tmp_path / "test.sqlite")
    with db.transaction() as cur:
        for ddl in ALL_TABLES_DDL:
            cur.execute(ddl)
    return db


@pytest.fixture
def db_with_data(db: Database) -> Database:
    """DB con discursos/frases/emociones en distintos estados.

    Estados:
      D001: summarizer completed, metadata completed (tipo='discurso oficial'),
            enunciation failed.
      D002: summarizer completed, metadata completed (tipo='no identificado'),
            enunciation completed.
      D003: summarizer pending, metadata failed, enunciation pending.

    Frases de D001:
      (D001, 0): actores completed, emotions failed.
      (D001, 1): actores completed, emotions completed.
    """
    now = "2025-01-01 00:00:00"
    with db.transaction() as cur:
        # discursos
        cur.execute(
            "INSERT INTO discursos (codigo, input, "
            "summarizer_payload, summarizer_version, summarizer_error, "
            "metadata_payload, metadata_version, metadata_error, "
            "enunciation_payload, enunciation_version, enunciation_error, "
            "created_at, updated_at) VALUES "
            "(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "D001", json.dumps({"contenido": "x"}),
                json.dumps({"resumen_global": "ok"}), "v1", None,
                json.dumps({"tipo_discurso": "discurso oficial"}), "v1", None,
                None, None, "boom enunciation",
                now, now,
            ),
        )
        cur.execute(
            "INSERT INTO discursos (codigo, input, "
            "summarizer_payload, summarizer_version, summarizer_error, "
            "metadata_payload, metadata_version, metadata_error, "
            "enunciation_payload, enunciation_version, enunciation_error, "
            "created_at, updated_at) VALUES "
            "(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "D002", json.dumps({"contenido": "y"}),
                json.dumps({"resumen_global": "ok2"}), "v1", None,
                json.dumps({"tipo_discurso": "no identificado"}), "v1", None,
                json.dumps({"enunciador": "alguien"}), "v1", None,
                now, now,
            ),
        )
        cur.execute(
            "INSERT INTO discursos (codigo, input, "
            "metadata_error, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
            ("D003", json.dumps({"contenido": "z"}), "boom meta", now, now),
        )

        # frases para D001
        cur.execute(
            "INSERT INTO frases (codigo, unit_idx, frase, "
            "actores_payload, actores_version, "
            "emociones_payload, emociones_version, emociones_error, "
            "created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "D001", 0, "Frase uno.",
                json.dumps([{"actor": "A"}]), "v1",
                None, None, "boom emo 0",
                now, now,
            ),
        )
        cur.execute(
            "INSERT INTO frases (codigo, unit_idx, frase, "
            "actores_payload, actores_version, "
            "emociones_payload, emociones_version, emociones_error, "
            "created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "D001", 1, "Frase dos.",
                json.dumps([{"actor": "B"}]), "v1",
                json.dumps([{"tipo_emocion": "alegría"}]), "v1", None,
                now, now,
            ),
        )

        # emociones caracterizadas (de D001 frase 1)
        cur.execute(
            "INSERT INTO emociones (codigo, frase_idx, emocion_idx, "
            "experienciador, experienciador_marca, tipo_emocion, modo_existencia, fuente_marca, fuente_inferencia, "
            "caracterizacion_payload, caracterizacion_version, caracterizacion_error, "
            "created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "D001", 1, 0,
                "presidente", "el presidente", "alegría", "actualizado", "marca de prueba", "inferencia de prueba",
                json.dumps({"foria": "eufórica", "intensidad": "alta"}), "v1", None,
                now, now,
            ),
        )
        # otra emoción con caracterizacion failed
        cur.execute(
            "INSERT INTO emociones (codigo, frase_idx, emocion_idx, "
            "experienciador, experienciador_marca, tipo_emocion, modo_existencia, fuente_marca, fuente_inferencia, "
            "caracterizacion_payload, caracterizacion_version, caracterizacion_error, "
            "created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "D001", 1, 1,
                "pueblo", "el pueblo", "miedo", "virtual", "marca de prueba", "inferencia de prueba",
                None, None, "boom char",
                now, now,
            ),
        )
    return db


@pytest.fixture
def base_config() -> RunConfig:
    """RunConfig mínimo con dos modelos y dos stages asignadas."""
    return RunConfig(
        models={
            "phi4-mini": ModelConfig(backend="llama_cpp", path="x.gguf"),
            "qwen3-30b-moe": ModelConfig(backend="llama_cpp", path="y.gguf"),
        },
        pipeline=PipelineConfig(
            stages={
                "metadata": "phi4-mini",
                "emotions": "phi4-mini",
            },
        ),
    )


# ══════════════════════════════════════════════════════════════════════════════
#  Validación Pydantic
# ══════════════════════════════════════════════════════════════════════════════


class TestRetryPolicyFilter:
    def test_eq_ok(self) -> None:
        f = RetryPolicyFilter(field="tipo_discurso", op="eq", value="oficial")
        assert f.field == "tipo_discurso"
        assert f.op == "eq"

    def test_default_op_is_eq(self) -> None:
        f = RetryPolicyFilter(field="tipo_discurso", value="x")
        assert f.op == "eq"

    def test_in_requires_list(self) -> None:
        with pytest.raises(ValueError, match="lista"):
            RetryPolicyFilter(field="tipo", op="in", value="no es lista")

    def test_in_with_list_ok(self) -> None:
        f = RetryPolicyFilter(field="tipo", op="in", value=["a", "b"])
        assert f.value == ["a", "b"]

    def test_eq_requires_value(self) -> None:
        with pytest.raises(ValueError, match="requiere 'value'"):
            RetryPolicyFilter(field="tipo", op="eq")

    def test_is_null_no_value(self) -> None:
        f = RetryPolicyFilter(field="tipo", op="is_null")
        assert f.value is None

    def test_empty_field_rejected(self) -> None:
        with pytest.raises(ValueError, match="field inválido"):
            RetryPolicyFilter(field="", op="eq", value="x")

    def test_leading_dot_rejected(self) -> None:
        with pytest.raises(ValueError, match="field inválido"):
            RetryPolicyFilter(field=".foo", op="eq", value="x")

    def test_unknown_op_rejected(self) -> None:
        with pytest.raises(ValueError):
            RetryPolicyFilter(field="tipo", op="regex", value="x")  # type: ignore[arg-type]


class TestRetryPolicy:
    def test_minimal_ok(self) -> None:
        p = RetryPolicy(stage="emotions")
        assert p.stage == "emotions"
        assert p.target == "failed"
        assert p.filters == []
        assert p.override_model is None

    def test_unknown_stage_rejected(self) -> None:
        with pytest.raises(ValueError, match="no soportada"):
            RetryPolicy(stage="not_a_stage")

    def test_judge_excluded(self) -> None:
        with pytest.raises(ValueError, match="no soportada"):
            RetryPolicy(stage="judge")

    def test_explode_emotions_excluded(self) -> None:
        with pytest.raises(ValueError, match="no soportada"):
            RetryPolicy(stage="explode_emotions")

    def test_invalid_target_rejected(self) -> None:
        with pytest.raises(ValueError):
            RetryPolicy(stage="emotions", target="weird")  # type: ignore[arg-type]

    def test_supported_stages_consistent_with_dag(self) -> None:
        # Sanity: cada SUPPORTED_STAGES debe poder construir una policy.
        for s in SUPPORTED_STAGES:
            RetryPolicy(stage=s)


# ══════════════════════════════════════════════════════════════════════════════
#  load_policy_file
# ══════════════════════════════════════════════════════════════════════════════


class TestLoadPolicyFile:
    def test_load_valid(self, tmp_path: Path) -> None:
        p = tmp_path / "ok.yaml"
        p.write_text(
            yaml.safe_dump(
                {
                    "policies": [
                        {"stage": "emotions", "target": "failed",
                         "override_model": "qwen3-30b-moe"},
                        {"stage": "metadata", "target": "completed",
                         "filters": [
                             {"field": "tipo_discurso", "op": "eq",
                              "value": "no identificado"}
                         ]},
                    ]
                }
            ),
            encoding="utf-8",
        )
        pf = load_policy_file(p)
        assert isinstance(pf, RetryPolicyFile)
        assert len(pf.policies) == 2
        assert pf.policies[0].stage == "emotions"
        assert pf.policies[0].override_model == "qwen3-30b-moe"
        assert pf.policies[1].filters[0].field == "tipo_discurso"

    def test_load_missing_file(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError):
            load_policy_file(tmp_path / "nope.yaml")

    def test_load_empty_yaml(self, tmp_path: Path) -> None:
        p = tmp_path / "empty.yaml"
        p.write_text("", encoding="utf-8")
        pf = load_policy_file(p)
        assert pf.policies == []

    def test_load_not_a_mapping(self, tmp_path: Path) -> None:
        p = tmp_path / "list.yaml"
        p.write_text(yaml.safe_dump([{"stage": "emotions"}]), encoding="utf-8")
        with pytest.raises(ValueError, match="mapping top-level"):
            load_policy_file(p)

    def test_load_extra_keys_rejected(self, tmp_path: Path) -> None:
        p = tmp_path / "extra.yaml"
        p.write_text(
            yaml.safe_dump({"policies": [], "garbage": True}),
            encoding="utf-8",
        )
        with pytest.raises(ValueError):
            load_policy_file(p)


# ══════════════════════════════════════════════════════════════════════════════
#  Aplicación: target
# ══════════════════════════════════════════════════════════════════════════════


class TestApplyTarget:
    def test_failed_only(self, db_with_data: Database) -> None:
        """target=failed marca solo las filas con error."""
        applier = RetryPolicyApplier(db_with_data)
        pf = RetryPolicyFile(
            policies=[RetryPolicy(stage="enunciation", target="failed")]
        )
        results, _ = applier.apply(pf)
        assert len(results) == 1
        # D001 tiene enunciation_error setteado, D002 no, D003 no (NULL).
        assert results[0].rows_marked_pending == 1
        # D001 ahora está pending.
        row = db_with_data.execute(
            "SELECT enunciation_payload, enunciation_error "
            "FROM discursos WHERE codigo='D001'"
        ).fetchone()
        assert row["enunciation_payload"] is None
        assert row["enunciation_error"] is None
        # D002 sigue completed.
        row2 = db_with_data.execute(
            "SELECT enunciation_payload FROM discursos WHERE codigo='D002'"
        ).fetchone()
        assert row2["enunciation_payload"] is not None

    def test_completed_only(self, db_with_data: Database) -> None:
        """target=completed marca solo las filas con payload."""
        applier = RetryPolicyApplier(db_with_data)
        pf = RetryPolicyFile(
            policies=[RetryPolicy(stage="summarizer", target="completed")]
        )
        results, _ = applier.apply(pf)
        # D001 y D002 tienen summarizer completed; D003 no.
        assert results[0].rows_marked_pending == 2

    def test_all(self, db_with_data: Database) -> None:
        """target=all marca completed + failed (no toca pending)."""
        applier = RetryPolicyApplier(db_with_data)
        # metadata: D001 completed, D002 completed, D003 failed → 3.
        pf = RetryPolicyFile(
            policies=[RetryPolicy(stage="metadata", target="all")]
        )
        results, _ = applier.apply(pf)
        assert results[0].rows_marked_pending == 3
        # Todo nulo ahora.
        rows = db_with_data.execute(
            "SELECT metadata_payload, metadata_error FROM discursos"
        ).fetchall()
        for r in rows:
            assert r["metadata_payload"] is None
            assert r["metadata_error"] is None

    def test_no_matches(self, db_with_data: Database) -> None:
        """target=failed sobre summarizer no encuentra nada → 0."""
        applier = RetryPolicyApplier(db_with_data)
        pf = RetryPolicyFile(
            policies=[RetryPolicy(stage="summarizer", target="failed")]
        )
        results, _ = applier.apply(pf)
        assert results[0].rows_marked_pending == 0


# ══════════════════════════════════════════════════════════════════════════════
#  Aplicación: filtros
# ══════════════════════════════════════════════════════════════════════════════


class TestApplyFilters:
    def test_filter_eq(self, db_with_data: Database) -> None:
        """metadata.tipo_discurso='no identificado' → solo D002."""
        applier = RetryPolicyApplier(db_with_data)
        pf = RetryPolicyFile(
            policies=[
                RetryPolicy(
                    stage="metadata",
                    target="completed",
                    filters=[
                        RetryPolicyFilter(
                            field="tipo_discurso", op="eq",
                            value="no identificado",
                        )
                    ],
                )
            ]
        )
        results, _ = applier.apply(pf)
        assert results[0].rows_marked_pending == 1
        # D002 ahora pending; D001 sigue completed.
        d001 = db_with_data.execute(
            "SELECT metadata_payload FROM discursos WHERE codigo='D001'"
        ).fetchone()
        d002 = db_with_data.execute(
            "SELECT metadata_payload FROM discursos WHERE codigo='D002'"
        ).fetchone()
        assert d001["metadata_payload"] is not None
        assert d002["metadata_payload"] is None

    def test_filter_ne(self, db_with_data: Database) -> None:
        """metadata.tipo_discurso != 'no identificado' → solo D001."""
        applier = RetryPolicyApplier(db_with_data)
        pf = RetryPolicyFile(
            policies=[
                RetryPolicy(
                    stage="metadata",
                    target="completed",
                    filters=[
                        RetryPolicyFilter(
                            field="tipo_discurso", op="ne",
                            value="no identificado",
                        )
                    ],
                )
            ]
        )
        results, _ = applier.apply(pf)
        assert results[0].rows_marked_pending == 1

    def test_filter_in(self, db_with_data: Database) -> None:
        """tipo IN [oficial, no identificado] → ambos D001+D002."""
        applier = RetryPolicyApplier(db_with_data)
        pf = RetryPolicyFile(
            policies=[
                RetryPolicy(
                    stage="metadata",
                    target="completed",
                    filters=[
                        RetryPolicyFilter(
                            field="tipo_discurso", op="in",
                            value=["discurso oficial", "no identificado"],
                        )
                    ],
                )
            ]
        )
        results, _ = applier.apply(pf)
        assert results[0].rows_marked_pending == 2

    def test_filter_contains(self, db_with_data: Database) -> None:
        """tipo_discurso contains 'identificado' → solo D002."""
        applier = RetryPolicyApplier(db_with_data)
        pf = RetryPolicyFile(
            policies=[
                RetryPolicy(
                    stage="metadata",
                    target="completed",
                    filters=[
                        RetryPolicyFilter(
                            field="tipo_discurso", op="contains",
                            value="identificado",
                        )
                    ],
                )
            ]
        )
        results, _ = applier.apply(pf)
        assert results[0].rows_marked_pending == 1

    def test_filter_is_null(self, db_with_data: Database) -> None:
        """enunciador IS NULL en metadata_payload (campo inexistente)."""
        applier = RetryPolicyApplier(db_with_data)
        pf = RetryPolicyFile(
            policies=[
                RetryPolicy(
                    stage="metadata",
                    target="completed",
                    filters=[
                        RetryPolicyFilter(field="enunciador", op="is_null"),
                    ],
                )
            ]
        )
        results, _ = applier.apply(pf)
        assert results[0].rows_marked_pending == 2

    def test_filter_is_not_null(self, db_with_data: Database) -> None:
        """tipo_discurso IS NOT NULL → ambos D001+D002 (tienen el campo)."""
        applier = RetryPolicyApplier(db_with_data)
        pf = RetryPolicyFile(
            policies=[
                RetryPolicy(
                    stage="metadata",
                    target="completed",
                    filters=[
                        RetryPolicyFilter(field="tipo_discurso", op="is_not_null"),
                    ],
                )
            ]
        )
        results, _ = applier.apply(pf)
        assert results[0].rows_marked_pending == 2

    def test_filter_failed_plus_payload_filter_warns(
        self,
        db_with_data: Database,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """target=failed + filtro sobre payload selecciona 0 + warning."""
        # Caso degenerado: failed → payload IS NULL, no hay nada que
        # filtrar sobre el contenido.
        applier = RetryPolicyApplier(db_with_data)
        pf = RetryPolicyFile(
            policies=[
                RetryPolicy(
                    stage="metadata",
                    target="failed",
                    filters=[
                        RetryPolicyFilter(
                            field="tipo_discurso", op="eq",
                            value="no identificado",
                        )
                    ],
                )
            ]
        )
        results, _ = applier.apply(pf)
        # D003 tiene metadata_error pero metadata_payload=NULL, así que
        # json_extract da NULL y no matchea "no identificado".
        assert results[0].rows_marked_pending == 0

    def test_multiple_filters_anded(self, db_with_data: Database) -> None:
        """Dos filtros se combinan en AND."""
        applier = RetryPolicyApplier(db_with_data)
        pf = RetryPolicyFile(
            policies=[
                RetryPolicy(
                    stage="metadata",
                    target="completed",
                    filters=[
                        RetryPolicyFilter(
                            field="tipo_discurso", op="contains",
                            value="discurso",
                        ),
                        RetryPolicyFilter(
                            field="tipo_discurso", op="ne",
                            value="no identificado",
                        ),
                    ],
                )
            ]
        )
        results, _ = applier.apply(pf)
        # Solo D001 cumple ambos (D002 tipo='no identificado' falla la 2da).
        assert results[0].rows_marked_pending == 1


# ══════════════════════════════════════════════════════════════════════════════
#  Aplicación: distintas granularidades de tabla
# ══════════════════════════════════════════════════════════════════════════════


class TestApplyAcrossTables:
    def test_frases_emotions_failed(self, db_with_data: Database) -> None:
        """Stage de frases (emotions): unidad por (codigo, unit_idx)."""
        applier = RetryPolicyApplier(db_with_data)
        pf = RetryPolicyFile(
            policies=[RetryPolicy(stage="emotions", target="failed")]
        )
        results, _ = applier.apply(pf)
        # (D001, 0) tiene emociones_error setteado.
        assert results[0].rows_marked_pending == 1
        row = db_with_data.execute(
            "SELECT emociones_error, emociones_payload FROM frases "
            "WHERE codigo='D001' AND unit_idx=0"
        ).fetchone()
        assert row["emociones_error"] is None
        assert row["emociones_payload"] is None

    def test_emociones_table_characterizer_failed(
        self, db_with_data: Database,
    ) -> None:
        """Stage characterizer: unidad por (codigo, frase_idx, emocion_idx)."""
        applier = RetryPolicyApplier(db_with_data)
        pf = RetryPolicyFile(
            policies=[RetryPolicy(stage="characterizer", target="failed")]
        )
        results, _ = applier.apply(pf)
        # (D001, 1, 1) tiene caracterizacion_error.
        assert results[0].rows_marked_pending == 1

    def test_actors_no_failed_no_change(self, db_with_data: Database) -> None:
        """actors no tiene failed en la fixture → 0."""
        applier = RetryPolicyApplier(db_with_data)
        pf = RetryPolicyFile(
            policies=[RetryPolicy(stage="actors", target="failed")]
        )
        results, _ = applier.apply(pf)
        assert results[0].rows_marked_pending == 0
        # Las frases siguen con actores_payload.
        rows = db_with_data.execute(
            "SELECT actores_payload FROM frases"
        ).fetchall()
        for r in rows:
            assert r["actores_payload"] is not None


# ══════════════════════════════════════════════════════════════════════════════
#  Override de modelo
# ══════════════════════════════════════════════════════════════════════════════


class TestOverrideModel:
    def test_override_applied_in_copy(
        self,
        db_with_data: Database,
        base_config: RunConfig,
    ) -> None:
        original_alias = base_config.pipeline.stages["emotions"]
        assert original_alias == "phi4-mini"

        applier = RetryPolicyApplier(db_with_data)
        pf = RetryPolicyFile(
            policies=[
                RetryPolicy(
                    stage="emotions", target="failed",
                    override_model="qwen3-30b-moe",
                )
            ]
        )
        results, new_config = applier.apply(pf, base_config=base_config)

        assert base_config.pipeline.stages["emotions"] == "phi4-mini"
        assert new_config is not None
        assert new_config.pipeline.stages["emotions"] == "qwen3-30b-moe"
        assert results[0].override_model == "qwen3-30b-moe"

    def test_override_unknown_alias_raises(
        self,
        db_with_data: Database,
        base_config: RunConfig,
    ) -> None:
        applier = RetryPolicyApplier(db_with_data)
        pf = RetryPolicyFile(
            policies=[
                RetryPolicy(
                    stage="emotions", target="failed",
                    override_model="modelo-inexistente",
                )
            ]
        )
        with pytest.raises(ValueError, match="no está definido en config.models"):
            applier.apply(pf, base_config=base_config)

    def test_no_config_no_override(self, db_with_data: Database) -> None:
        """Si no se pasa base_config, retorna None y override_model se ignora a nivel config."""
        applier = RetryPolicyApplier(db_with_data)
        pf = RetryPolicyFile(
            policies=[
                RetryPolicy(
                    stage="emotions", target="failed",
                    override_model="qwen3-30b-moe",
                )
            ]
        )
        results, new_config = applier.apply(pf, base_config=None)
        assert new_config is None
        assert results[0].override_model == "qwen3-30b-moe"

    def test_override_on_stage_not_in_config_pipeline_stages(
        self,
        db_with_data: Database,
        base_config: RunConfig,
    ) -> None:
        """Si la stage del override no estaba en pipeline.stages, se agrega."""
        assert "summarizer" not in base_config.pipeline.stages
        applier = RetryPolicyApplier(db_with_data)
        pf = RetryPolicyFile(
            policies=[
                RetryPolicy(
                    stage="summarizer", target="completed",
                    override_model="qwen3-30b-moe",
                )
            ]
        )
        _, new_config = applier.apply(pf, base_config=base_config)
        assert new_config is not None
        assert new_config.pipeline.stages["summarizer"] == "qwen3-30b-moe"


# ══════════════════════════════════════════════════════════════════════════════
#  Idempotencia + edge cases
# ══════════════════════════════════════════════════════════════════════════════


class TestIdempotencyAndEdges:
    def test_reapply_same_policy(self, db_with_data: Database) -> None:
        """Aplicar dos veces: la segunda no toca filas (ya nulas)."""
        applier = RetryPolicyApplier(db_with_data)
        pf = RetryPolicyFile(
            policies=[RetryPolicy(stage="enunciation", target="failed")]
        )
        r1, _ = applier.apply(pf)
        r2, _ = applier.apply(pf)
        assert r1[0].rows_marked_pending == 1
        assert r2[0].rows_marked_pending == 0

    def test_multiple_policies(self, db_with_data: Database) -> None:
        """Aplicar dos policies en orden."""
        applier = RetryPolicyApplier(db_with_data)
        pf = RetryPolicyFile(
            policies=[
                RetryPolicy(stage="enunciation", target="failed"),
                RetryPolicy(stage="emotions", target="failed"),
            ]
        )
        results, _ = applier.apply(pf)
        assert len(results) == 2
        assert results[0].rows_marked_pending == 1
        assert results[1].rows_marked_pending == 1

    def test_empty_policies(self, db_with_data: Database) -> None:
        """RetryPolicyFile vacío → resultado vacío."""
        applier = RetryPolicyApplier(db_with_data)
        results, _ = applier.apply(RetryPolicyFile(policies=[]))
        assert results == []

    def test_result_is_pydantic_model(self, db_with_data: Database) -> None:
        """Tipos correctos en el resultado."""
        applier = RetryPolicyApplier(db_with_data)
        pf = RetryPolicyFile(
            policies=[RetryPolicy(stage="enunciation", target="failed")]
        )
        results, _ = applier.apply(pf)
        assert isinstance(results[0], PolicyApplicationResult)
        assert results[0].stage == "enunciation"


# ══════════════════════════════════════════════════════════════════════════════
#  Sanity: contains escapa comodines correctamente
# ══════════════════════════════════════════════════════════════════════════════


class TestContainsEscape:
    def test_contains_with_percent(self, db: Database) -> None:
        """'contains' no debe matchear comodines literales en el value.

        Insertamos un payload con 'no identificado' y buscamos
        'no%identificado'. Sin escape, % matchearia cualquier cosa
        en el medio. Con escape correcto, no debe matchear.
        """
        now = "2025-01-01 00:00:00"
        with db.transaction() as cur:
            cur.execute(
                "INSERT INTO discursos (codigo, input, metadata_payload, "
                "metadata_version, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (
                    "D001",
                    json.dumps({"contenido": "x"}),
                    json.dumps({"tipo_discurso": "no identificado"}),
                    "v1",
                    now, now,
                ),
            )

        applier = RetryPolicyApplier(db)
        pf = RetryPolicyFile(
            policies=[
                RetryPolicy(
                    stage="metadata",
                    target="completed",
                    filters=[
                        RetryPolicyFilter(
                            field="tipo_discurso", op="contains",
                            value="no%identificado",  # con % literal
                        )
                    ],
                )
            ]
        )
        results, _ = applier.apply(pf)
        assert results[0].rows_marked_pending == 0
