# ══════════════════════════════════════════════════════════════════════════════
#  tests.unit.test_cli
#
#  Tests del CLI:
#  - Parser construye correctamente.
#  - Dispatch a subcomandos.
#  - Manejo de errores y exit codes.
#  - El subcomando `run` end-to-end con backends mockeados.
# ══════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, TypeVar

import pytest
import yaml
from pydantic import BaseModel

from emoparse.cli import main
from emoparse.cli.commands import inspect_cmd, retry_cmd, stats_cmd, status_cmd
from emoparse.cli.commands.run_cmd import _parse_stages, _resolve_db_path
from emoparse.core.backend.base import LLMBackend, LLMResponse, TokenUsage
from emoparse.core.schemas import (
    ActoresBatchItemSchema,
    ActorSchema,
    CaracterizacionBatchItemSchema,
    CaracterizacionEmocionSchema,
    EmocionesBatchItemSchema,
    EmocionSchema,
    EnunciacionSchema,
    EnunciadorSchema,
    EnunciatarioSchema,
    ListaActoresBatchSchema,
    ListaCaracterizacionBatchSchema,
    ListaEmocionesBatchSchema,
    MetadatosSchema,
)
from emoparse.pipeline import STAGE_ORDER, PipelineRunner

T = TypeVar("T", bound=BaseModel)


# ══════════════════════════════════════════════════════════════════════════════
#  Helpers para no duplicar entre tests del Runner y del CLI
# ══════════════════════════════════════════════════════════════════════════════


class _MockBackend(LLMBackend):
    def __init__(self, alias: str = "fake") -> None:
        self.alias = alias

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
        if schema is None:
            return LLMResponse(
                parsed=None, raw="resumen",
                usage=TokenUsage(10, 5), latency_ms=1.0,
                model_alias=self.alias, cache_hit=False, finish_reason="stop",
            )
        n_units = max(1, user.count("UNIDAD [") + user.count("EMOCIÓN ["))
        parsed: BaseModel
        if schema is MetadatosSchema:
            parsed = MetadatosSchema(
                tipo_discurso="asuncion",
                tipo_discurso_justificacion="j",
                ciudad="BA", provincia="BA", pais="AR",
                lugar_justificacion="j",
            )
        elif schema is EnunciacionSchema:
            parsed = EnunciacionSchema(
                enunciador=EnunciadorSchema(actor="Yo", justificacion="j"),
                enunciatarios=[EnunciatarioSchema(
                    actor="Pueblo", tipo="prodestinatario", justificacion="j",
                )],
            )
        elif schema is ListaActoresBatchSchema:
            parsed = ListaActoresBatchSchema(root=[
                ActoresBatchItemSchema(unit_idx=i, actores=[
                    ActorSchema(actor="X", tipo="colectivo",
                                modo="explicito", justificacion="j"),
                ]) for i in range(n_units)
            ])
        elif schema is ListaEmocionesBatchSchema:
            parsed = ListaEmocionesBatchSchema(root=[
                EmocionesBatchItemSchema(unit_idx=i, emociones=[
                    EmocionSchema(experienciador="X", tipo_emocion="miedo",
                                  fuente_inferencia="actor", fuente_marca="marca",
                                  modo_existencia="realizada", justificacion="j"),
                ]) for i in range(n_units)
            ])
        elif schema is ListaCaracterizacionBatchSchema:
            parsed = ListaCaracterizacionBatchSchema(root=[
                CaracterizacionBatchItemSchema(
                    unit_idx=i,
                    caracterizacion=CaracterizacionEmocionSchema(
                        foria="disforico", foria_justificacion="j",
                        dominancia="cognoscitiva", dominancia_justificacion="j",
                        intensidad="alta", intensidad_justificacion="j",
                    ),
                ) for i in range(n_units)
            ])
        else:
            raise NotImplementedError
        return LLMResponse(
            parsed=parsed, raw="(m)",
            usage=TokenUsage(10, 5), latency_ms=1.0,
            model_alias=self.alias, cache_hit=False, finish_reason="stop",
        )

    def healthcheck(self) -> bool:
        return True


@pytest.fixture
def populated_setup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> dict[str, Any]:
    """Crea: knowledge dir, config.yaml, input.csv, y corre un pipeline
    completo. Devuelve dict con paths para reutilizar."""
    # Knowledge.
    kdir = tmp_path / "knowledge"
    kdir.mkdir()
    (kdir / "tipos_discurso.json").write_text(
        json.dumps({"asuncion": "Asunción presidencial."}),
        encoding="utf-8",
    )
    (kdir / "emociones.json").write_text(
        json.dumps({
            "modos_existencia": {
                "realizada": {"nombre": "R", "descripcion": "d"}
            }
        }),
        encoding="utf-8",
    )
    (kdir / "emociones_ontologia.json").write_text(
        json.dumps({
            "miedo": {
                "canonico": "miedo",
                "aliases": ["miedo"]
            }
        }),
        encoding="utf-8",
    )
    (kdir / "configuraciones_emocion.json").write_text(
        json.dumps({
            "version": "v1",
            "configuraciones": {
                "miedo": {
                    "foria": ["disforico"],
                    "dominancia": ["cognoscitiva"],
                    "intensidad": ["alta"],
                }
            }
        }),
        encoding="utf-8",
    )
    heur_dir = kdir / "heuristicas"
    heur_dir.mkdir()

    (heur_dir / "enunciation.md").write_text(
        "Heurísticas de enunciación.",
        encoding="utf-8",
    )
    (heur_dir / "actors.md").write_text(
    "Heurísticas de actores.",
    encoding="utf-8",
    )
    (heur_dir / "characterizer.md").write_text(
        "Heurísticas de caracterización.",
        encoding="utf-8",
    )
    (heur_dir / "emotions.md").write_text(
        "Heurísticas de emociones.",
        encoding="utf-8",
    )
    (heur_dir / "emotions_pass2.md").write_text(
        "Heurísticas de emociones (pase 2).",
        encoding="utf-8",
    )
    (heur_dir / "judge.md").write_text(
        "Heurísticas de judge.",
        encoding="utf-8",
    )

    # Input CSV.
    input_path = tmp_path / "input.csv"
    input_path.write_text(
        "codigo,contenido,titulo\n"
        'D1,"Hola compatriotas. Estoy esperanzado. Vamos a trabajar.",T1\n',
        encoding="utf-8",
    )

    # Config YAML.
    config_path = tmp_path / "config.yaml"
    runs_dir = tmp_path / "runs"
    config_path.write_text(yaml.safe_dump({
        "models": {"m": {"backend": "llama_cpp", "path": "ignored.gguf"}},
        "pipeline": {
            "stages": {
                s: "m" for s in STAGE_ORDER if s != "explode_emociones"
            }
        },
        "paths": {
            "knowledge_dir": str(kdir),
            "runs_dir": str(runs_dir),
        },
        "versions": {"prompt": "v1"},
    }), encoding="utf-8")

    # Patchear el backend factory.
    import emoparse.core.backend.registry as reg
    monkeypatch.setattr(reg, "build_backend", lambda alias, cfg: _MockBackend(alias))

    return {
        "kdir": kdir,
        "input_path": input_path,
        "config_path": config_path,
        "runs_dir": runs_dir,
        "tmp_path": tmp_path,
    }


# ══════════════════════════════════════════════════════════════════════════════
#  Parser y dispatch
# ══════════════════════════════════════════════════════════════════════════════


class TestParser:

    def test_no_args_exits_with_error(self) -> None:
        """`emoparse` sin subcomando muestra help y exit != 0."""
        with pytest.raises(SystemExit) as exc:
            main([])
        assert exc.value.code != 0

    def test_help_flag(self) -> None:
        """`-h` sale con 0 después de imprimir help."""
        with pytest.raises(SystemExit) as exc:
            main(["--help"])
        assert exc.value.code == 0

    def test_unknown_subcommand(self) -> None:
        with pytest.raises(SystemExit):
            main(["nonexistent"])


# ══════════════════════════════════════════════════════════════════════════════
#  run_cmd helpers
# ══════════════════════════════════════════════════════════════════════════════


class TestRunCmdHelpers:

    def test_resolve_db_path_with_explicit_arg(self, tmp_path: Path) -> None:
        explicit = tmp_path / "explicit.sqlite"
        result = _resolve_db_path(str(explicit), "ignored/", "ignored")
        assert result == explicit.resolve()

    def test_resolve_db_path_default(self, tmp_path: Path) -> None:
        runs_dir = tmp_path / "runs"
        result = _resolve_db_path(None, str(runs_dir), "my_run")
        assert result == (runs_dir / "my_run.sqlite").resolve()

    def test_parse_stages_valid(self) -> None:
        result = _parse_stages("metadata,emotions")
        assert result == ("metadata", "emotions")

    def test_parse_stages_strips_whitespace(self) -> None:
        result = _parse_stages(" metadata , emotions ")
        assert result == ("metadata", "emotions")

    def test_parse_stages_unknown_raises(self) -> None:
        with pytest.raises(ValueError, match="desconocidas"):
            _parse_stages("metadata,inexistente")

    def test_parse_stages_empty_raises(self) -> None:
        with pytest.raises(ValueError, match="vacío"):
            _parse_stages("")


# ══════════════════════════════════════════════════════════════════════════════
#  run end-to-end vía CLI
# ══════════════════════════════════════════════════════════════════════════════


class TestRunEndToEnd:

    def test_run_completes_successfully(
        self,
        populated_setup: dict[str, Any],
    ) -> None:
        rc = main([
            "run",
            "--config", str(populated_setup["config_path"]),
            "--input", str(populated_setup["input_path"]),
            "--run-id", "cli_test",
        ])
        assert rc == 0

        # DB creada en runs_dir/cli_test.sqlite.
        db_path = populated_setup["runs_dir"] / "cli_test.sqlite"
        assert db_path.is_file()

    def test_run_with_explicit_db_path(
        self,
        populated_setup: dict[str, Any],
        tmp_path: Path,
    ) -> None:
        custom_db = tmp_path / "custom.sqlite"
        rc = main([
            "run",
            "--config", str(populated_setup["config_path"]),
            "--input", str(populated_setup["input_path"]),
            "--run-id", "x",
            "--db", str(custom_db),
        ])
        assert rc == 0
        assert custom_db.is_file()

    def test_run_with_subset_of_stages(
        self,
        populated_setup: dict[str, Any],
    ) -> None:
        rc = main([
            "run",
            "--config", str(populated_setup["config_path"]),
            "--input", str(populated_setup["input_path"]),
            "--run-id", "subset",
            "--stages", "summarizer,metadata",
        ])
        assert rc == 0

    def test_run_with_invalid_config_returns_1(
        self,
        tmp_path: Path,
    ) -> None:
        bad_config = tmp_path / "bad.yaml"
        bad_config.write_text("not valid: [yaml", encoding="utf-8")
        # Necesitamos un input válido para llegar a leer el config primero.
        input_path = tmp_path / "input.csv"
        input_path.write_text("codigo,contenido\nA,x\n", encoding="utf-8")
        rc = main([
            "run", "--config", str(bad_config),
            "--input", str(input_path), "--run-id", "x",
        ])
        assert rc == 1

    def test_run_with_invalid_input_returns_1(
        self,
        populated_setup: dict[str, Any],
        tmp_path: Path,
    ) -> None:
        bad_input = tmp_path / "no_existe.csv"
        rc = main([
            "run",
            "--config", str(populated_setup["config_path"]),
            "--input", str(bad_input),
            "--run-id", "x",
        ])
        assert rc == 1

    def test_run_with_unknown_stage_returns_1(
        self,
        populated_setup: dict[str, Any],
    ) -> None:
        rc = main([
            "run",
            "--config", str(populated_setup["config_path"]),
            "--input", str(populated_setup["input_path"]),
            "--run-id", "x",
            "--stages", "metadata,inexistente",
        ])
        assert rc == 1


# ══════════════════════════════════════════════════════════════════════════════
#  status / inspect / stats / retry sobre DB poblada
# ══════════════════════════════════════════════════════════════════════════════


@pytest.fixture
def populated_db(populated_setup: dict[str, Any]) -> Path:
    """Corre el pipeline una vez y devuelve el path a la DB resultante."""
    db_path = populated_setup["runs_dir"] / "test.sqlite"
    main([
        "run",
        "--config", str(populated_setup["config_path"]),
        "--input", str(populated_setup["input_path"]),
        "--run-id", "test",
        "--db", str(db_path),
    ])
    return db_path


class TestStatus:

    def test_status_on_populated_db(
        self,
        populated_db: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        rc = main(["status", "--db", str(populated_db)])
        assert rc == 0
        out = capsys.readouterr().out
        # La tabla menciona las stages.
        assert "summarizer" in out
        assert "metadata" in out
        assert "characterizer" in out

    def test_status_db_not_found(
        self,
        tmp_path: Path,
    ) -> None:
        rc = main(["status", "--db", str(tmp_path / "no_existe.sqlite")])
        assert rc == 1

    def test_status_db_uninitialized(
        self,
        tmp_path: Path,
    ) -> None:
        """DB existe pero no tiene un run inicializado."""
        empty = tmp_path / "empty.sqlite"
        empty.touch()
        rc = main(["status", "--db", str(empty)])
        assert rc == 1


class TestInspect:

    def test_inspect_existing_codigo(
        self,
        populated_db: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        rc = main(["inspect", "--db", str(populated_db), "--codigo", "D1"])
        assert rc == 0
        out = capsys.readouterr().out
        assert "D1" in out
        assert "summarizer" in out

    def test_inspect_nonexistent_codigo(
        self,
        populated_db: Path,
    ) -> None:
        rc = main([
            "inspect", "--db", str(populated_db), "--codigo", "NONEXISTENT",
        ])
        assert rc == 1


class TestStats:

    def test_stats_on_populated_db(
        self,
        populated_db: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        rc = main(["stats", "--db", str(populated_db)])
        assert rc == 0
        out = capsys.readouterr().out
        assert "Cache stats" in out


class TestRetry:

    def test_retry_no_errors_returns_0(
        self,
        populated_db: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        rc = main([
            "retry", "--db", str(populated_db), "--stage", "metadata",
        ])
        assert rc == 0
        out = capsys.readouterr().out
        assert "Nada que reintentar" in out

    def test_retry_unknown_stage_returns_1(
        self,
        populated_db: Path,
    ) -> None:
        rc = main([
            "retry", "--db", str(populated_db), "--stage", "inexistente",
        ])
        assert rc == 1

    def test_retry_clears_errors(
        self,
        populated_db: Path,
    ) -> None:
        """Después de set_error, retry los limpia."""
        from emoparse.storage.db import Database
        from emoparse.storage.discursos import DiscursosRepository

        # Forzar un error.
        d_repo = DiscursosRepository(Database(populated_db))
        d_repo.set_error("D1", "metadata", "simulated")
        assert "D1" in d_repo.list_failed("metadata")

        # Retry.
        rc = main(["retry", "--db", str(populated_db), "--stage", "metadata"])
        assert rc == 0

        # El error fue limpiado.
        d_repo2 = DiscursosRepository(Database(populated_db))
        assert d_repo2.list_failed("metadata") == []
        # Y aparece como pending de nuevo.
        assert "D1" in d_repo2.list_pending("metadata")
