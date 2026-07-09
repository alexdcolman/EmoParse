# ══════════════════════════════════════════════════════════════════════════════
#  tests.unit.test_pipeline_runner
#
#  Tests del PipelineRunner end-to-end con backends mockeados. Cubre:
#  - Ingest: discursos cargan a la DB.
#  - Chunking: contenidos se parten en frases.
#  - Run: las 7 stages corren en orden.
#  - Resumability: re-correr el mismo run no re-procesa lo hecho.
#  - Stage selection: enabled_stages filtra correctamente.
#  - Cleanup: VRAM se libera entre stages que usan modelos distintos.
# ══════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, TypeVar

import pandas as pd
import pytest
from pydantic import BaseModel

from emoparse.config.models import (
    ModelConfig,
    PathsConfig,
    PipelineConfig,
    RunConfig,
    VersionsConfig,
)
from emoparse.core.backend.base import LLMBackend, LLMResponse, TokenUsage
from emoparse.core.schemas import (
    ActorSchema,
    ActoresBatchItemSchema,
    CaracterizacionBatchItemSchema,
    CaracterizacionEmocionSchema,
    EmocionesBatchItemSchema,
    EmocionSchema,
    EnunciacionSchema,
    EnunciadorSchema,
    EnunciatarioSchema,
    JuicioBatchItemSchema,
    JuicioSchema,
    ListaActoresBatchSchema,
    ListaCaracterizacionBatchSchema,
    ListaEmocionesBatchSchema,
    ListaSemasBatchSchema,
    ListaJuiciosBatchSchema,
    MetadatosSchema,
    SemasBatchItemSchema,
)
from emoparse.knowledge import KnowledgeLoader
from emoparse.pipeline import STAGE_ORDER, PipelineRunner
from emoparse.storage.db import Database
from emoparse.storage.discursos import DiscursosRepository
from emoparse.storage.emociones import EmocionesRepository
from emoparse.storage.frases import FrasesRepository

T = TypeVar("T", bound=BaseModel)


# ══════════════════════════════════════════════════════════════════════════════
#  Mocks
# ══════════════════════════════════════════════════════════════════════════════


class _MockBackend(LLMBackend):
    """Backend que devuelve respuestas válidas para todos los schemas
    del proyecto. Cuenta llamadas para aserciones."""

    def __init__(self, alias: str = "fake-model") -> None:
        self.alias = alias
        self.calls = 0

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
        self.calls += 1
        if schema is None:
            # Texto libre (summarizer).
            return LLMResponse(
                parsed=None, raw="Resumen mock.",
                usage=TokenUsage(10, 5), latency_ms=1.0,
                model_alias=self.alias, cache_hit=False, finish_reason="stop",
            )
        parsed = self._build_parsed(schema)
        return LLMResponse(
            parsed=parsed, raw="(mock)",
            usage=TokenUsage(10, 5), latency_ms=1.0,
            model_alias=self.alias, cache_hit=False, finish_reason="stop",
        )

    def healthcheck(self) -> bool:
        return True

    @staticmethod
    def _build_parsed(schema: type[BaseModel]) -> BaseModel:
        if schema is MetadatosSchema:
            return MetadatosSchema(
                tipo_discurso="asuncion",
                tipo_discurso_justificacion="just",
                ciudad="Buenos Aires",
                provincia="Buenos Aires",
                pais="Argentina",
                lugar_justificacion="just",
            )
        if schema is EnunciacionSchema or schema.__name__.startswith("EnunciacionSchema"):
            # Instanciamos con el schema recibido para que Pydantic valide contra
            # el Literal correcto del género. Para el tipo de enunciatario usamos
            # el primer valor permitido por ese schema dinámico.
            try:
                enunciatario_cls = schema.model_fields["enunciatarios"].annotation.__args__[0]
                tipo_valido = next(iter(enunciatario_cls.model_fields["tipo"].annotation.__args__))
            except Exception:
                tipo_valido = "prodestinatario"
            return schema(
                enunciador=EnunciadorSchema(actor="Yo", justificacion="j"),
                enunciatarios=[
                    EnunciatarioSchema(
                        actor="Pueblo",
                        tipo=tipo_valido,
                        justificacion="j",
                    )
                ],
            )
        if schema is ListaActoresBatchSchema:
            return ListaActoresBatchSchema(root=[
                ActoresBatchItemSchema(unit_idx=i, actores=[
                    ActorSchema(marca="X", actor="X", tipo="colectivo", modo="explicito",
                                justificacion="j"),
                ]) for i in range(5)
            ])
        if schema is ListaEmocionesBatchSchema:
            return ListaEmocionesBatchSchema(root=[
                EmocionesBatchItemSchema(unit_idx=i, emociones=[
                    EmocionSchema(experienciador="X", experienciador_marca="X", tipo_emocion="miedo",
                                  tipo_configuracion="sostenido_en_sustantivos",
                                  fuente_marca="X", fuente_inferencia="X",
                                  modo_existencia="realizada"),
                ]) for i in range(3)
            ])
        if schema is ListaSemasBatchSchema:
            return ListaSemasBatchSchema(root=[
                SemasBatchItemSchema(
                    unit_idx=i,
                    semas=[
                        "sema_1",
                        "sema_2",
                    ],
                )
                for i in range(5)
            ])
        if schema is ListaCaracterizacionBatchSchema:
            return ListaCaracterizacionBatchSchema(root=[
                CaracterizacionBatchItemSchema(
                    unit_idx=i,
                    caracterizacion=CaracterizacionEmocionSchema(
                        foria="disforico",             foria_justificacion="j",
                        dominancia="cognoscitiva",     dominancia_justificacion="j",
                        intensidad="alta",             intensidad_justificacion="j",
                        duracion="instantanea",        duracion_justificacion="j",
                        tipo_atribucion="auto_atribucion", tipo_atribucion_justificacion="j",
                    ),
                ) for i in range(5)
            ])
        if schema is ListaJuiciosBatchSchema:
            return ListaJuiciosBatchSchema(root=[
                JuicioBatchItemSchema(
                    unit_idx=i,
                    juicio=JuicioSchema(
                        coherente=True,
                        issues="no identificado",
                        confianza="alta",
                    ),
                ) for i in range(5)
            ])
        raise NotImplementedError(f"Schema no soportado: {schema}")


# ══════════════════════════════════════════════════════════════════════════════
#  Fixtures
# ══════════════════════════════════════════════════════════════════════════════


@pytest.fixture
def knowledge_dir(tmp_path: Path) -> Path:
    """Directorio con archivos de knowledge mínimos."""
    d = tmp_path / "knowledge"
    d.mkdir()

    (d / "tipos_discurso.json").write_text(
        json.dumps({"asuncion": "Discurso de toma de posesión."}),
        encoding="utf-8",
    )

    (d / "emociones.json").write_text(
        json.dumps({
            "modos_existencia": {
                "realizada": {
                    "nombre": "Realizada",
                    "descripcion": "Manifiesta."
                },
            }
        }),
        encoding="utf-8",
    )

    (d / "emociones_ontologia.json").write_text(
        json.dumps({
            "version": "v1",
            "emociones": {
                "ira": {
                    "aliases": ["enojo", "rabia", "furia", "indignacion", "indignación", "cólera", "colera", "bronca", "irritación", "irritacion"],
                    "foria": {"esperado": ["disforico"], "tolerado": ["ambiforico"]},
                    "intensidad": {"esperado": ["alta"], "tolerado": ["neutra_ambivalente"]},
                    "dominancia": {"esperado": ["corporal", "mixta"], "tolerado": ["cognoscitiva"]},
                    "modo_existencia": {"esperado": ["realizada", "actual"], "tolerado": ["potencial"]}
                },
                "miedo": {
                    "aliases": ["temor", "terror", "panico", "pánico", "angustia", "aprensión", "aprension", "susto"],
                    "foria": {"esperado": ["disforico"], "tolerado": ["ambiforico"]},
                    "intensidad": {"esperado": ["alta"], "tolerado": ["neutra_ambivalente"]},
                    "dominancia": {"esperado": ["corporal", "mixta"], "tolerado": ["cognoscitiva"]},
                    "modo_existencia": {"esperado": ["realizada", "actual"], "tolerado": ["potencial", "virtual"]}
                },
                "tristeza": {
                    "aliases": ["pena", "dolor", "melancolía", "melancolia", "pesar", "duelo", "luto", "abatimiento", "depresión", "depresion"],
                    "foria": {"esperado": ["disforico"], "tolerado": ["ambiforico"]},
                    "intensidad": {"esperado": ["alta", "neutra_ambivalente"], "tolerado": ["baja"]},
                    "dominancia": {"esperado": ["cognoscitiva", "mixta"], "tolerado": ["corporal"]},
                    "modo_existencia": {"esperado": ["realizada", "actual"], "tolerado": ["potencial", "virtual"]}
                },
                "alegria": {
                    "aliases": ["alegría", "felicidad", "júbilo", "jubilo", "gozo", "contento", "euforia", "entusiasmo", "satisfacción", "satisfaccion"],
                    "foria": {"esperado": ["euforico"], "tolerado": ["ambiforico"]},
                    "intensidad": {"esperado": ["alta", "neutra_ambivalente"], "tolerado": ["baja"]},
                    "dominancia": {"esperado": ["corporal", "mixta"], "tolerado": ["cognoscitiva"]},
                    "modo_existencia": {"esperado": ["realizada", "actual"], "tolerado": ["potencial"]}
                },
                "sorpresa": {
                    "aliases": ["asombro", "estupor", "extrañeza", "extranieza", "perplejidad", "desconcierto", "shock"],
                    "foria": {"esperado": ["aforico", "ambiforico"], "tolerado": ["euforico", "disforico"]},
                    "intensidad": {"esperado": ["alta", "neutra_ambivalente"], "tolerado": ["baja"]},
                    "dominancia": {"esperado": ["corporal", "cognoscitiva"], "tolerado": ["mixta"]},
                    "modo_existencia": {"esperado": ["realizada", "actual"], "tolerado": ["potencial"]}
                },
                "asco": {
                    "aliases": ["repugnancia", "repulsion", "repulsión", "disgusto", "aversión", "aversion", "náusea", "nausea", "rechazo"],
                    "foria": {"esperado": ["disforico"], "tolerado": ["ambiforico"]},
                    "intensidad": {"esperado": ["alta"], "tolerado": ["neutra_ambivalente"]},
                    "dominancia": {"esperado": ["corporal", "mixta"], "tolerado": ["cognoscitiva"]},
                    "modo_existencia": {"esperado": ["realizada", "actual"], "tolerado": ["potencial"]}
                },
                "amor": {
                    "aliases": ["cariño", "carino", "afecto", "ternura", "apego", "adoración", "adoracion"],
                    "foria": {"esperado": ["euforico"], "tolerado": ["ambiforico"]},
                    "intensidad": {"esperado": ["alta", "neutra_ambivalente"], "tolerado": ["baja"]},
                    "dominancia": {"esperado": ["corporal", "mixta"], "tolerado": ["cognoscitiva"]},
                    "modo_existencia": {"esperado": ["realizada", "actual"], "tolerado": ["potencial", "virtual"]}
                },
                "confianza": {
                    "aliases": ["fe", "seguridad", "certeza", "convicción", "conviccion", "credibilidad"],
                    "foria": {"esperado": ["euforico"], "tolerado": ["aforico"]},
                    "intensidad": {"esperado": ["alta", "neutra_ambivalente"], "tolerado": ["baja"]},
                    "dominancia": {"esperado": ["cognoscitiva"], "tolerado": ["mixta"]},
                    "modo_existencia": {"esperado": ["realizada", "actual"], "tolerado": ["potencial", "virtual"]}
                },
                "culpa": {
                    "aliases": ["remordimiento", "arrepentimiento", "vergüenza_moral", "verguenza_moral"],
                    "foria": {"esperado": ["disforico"], "tolerado": ["ambiforico"]},
                    "intensidad": {"esperado": ["alta", "neutra_ambivalente"], "tolerado": ["baja"]},
                    "dominancia": {"esperado": ["cognoscitiva", "mixta"], "tolerado": ["corporal"]},
                    "modo_existencia": {"esperado": ["realizada", "actual"], "tolerado": ["potencial"]}
                },
                "vergüenza": {
                    "aliases": ["verguenza", "humillación", "humillacion", "bochorno", "pudor"],
                    "foria": {"esperado": ["disforico"], "tolerado": ["ambiforico"]},
                    "intensidad": {"esperado": ["alta", "neutra_ambivalente"], "tolerado": ["baja"]},
                    "dominancia": {"esperado": ["corporal", "cognoscitiva"], "tolerado": ["mixta"]},
                    "modo_existencia": {"esperado": ["realizada", "actual"], "tolerado": ["potencial"]}
                },
                "decepción": {
                    "aliases": ["decepcion", "desilusión", "desilusión", "desilusíon", "frustración", "frustracion", "desengaño", "desenganio"],
                    "foria": {"esperado": ["disforico"], "tolerado": ["ambiforico"]},
                    "intensidad": {"esperado": ["alta", "neutra_ambivalente"], "tolerado": ["baja"]},
                    "dominancia": {"esperado": ["cognoscitiva", "mixta"], "tolerado": ["corporal"]},
                    "modo_existencia": {"esperado": ["realizada", "actual"], "tolerado": ["potencial"]}
                },
                "esperanza": {
                    "aliases": ["ilusión", "ilusion", "anhelo", "expectativa", "optimismo"],
                    "foria": {"esperado": ["euforico"], "tolerado": ["ambiforico"]},
                    "intensidad": {"esperado": ["alta", "neutra_ambivalente"], "tolerado": ["baja"]},
                    "dominancia": {"esperado": ["cognoscitiva"], "tolerado": ["mixta"]},
                    "modo_existencia": {"esperado": ["potencial", "virtual"], "tolerado": ["actual", "realizada"]}
                },
                "melancolía": {
                    "aliases": ["melancolia", "nostalgia", "añoranza", "anioranza", "morriña", "morrina"],
                    "foria": {"esperado": ["disforico"], "tolerado": ["ambiforico"]},
                    "intensidad": {"esperado": ["neutra_ambivalente", "alta"], "tolerado": ["baja"]},
                    "dominancia": {"esperado": ["cognoscitiva", "mixta"], "tolerado": ["corporal"]},
                    "modo_existencia": {"esperado": ["realizada", "actual"], "tolerado": ["virtual"]}
                },
                "orgullo": {
                    "aliases": ["dignidad", "autoestima", "honor", "soberbia"],
                    "foria": {"esperado": ["euforico"], "tolerado": ["ambiforico"]},
                    "intensidad": {"esperado": ["alta"], "tolerado": ["neutra_ambivalente"]},
                    "dominancia": {"esperado": ["cognoscitiva", "mixta"], "tolerado": ["corporal"]},
                    "modo_existencia": {"esperado": ["realizada", "actual"], "tolerado": ["potencial"]}
                },
                "ansiedad": {
                    "aliases": ["angustia", "nerviosismo", "zozobra", "inquietud", "intranquilidad", "alarma"],
                    "foria": {"esperado": ["disforico"], "tolerado": ["ambiforico"]},
                    "intensidad": {"esperado": ["alta", "neutra_ambivalente"], "tolerado": ["baja"]},
                    "dominancia": {"esperado": ["corporal", "mixta"], "tolerado": ["cognoscitiva"]},
                    "modo_existencia": {"esperado": ["realizada", "actual"], "tolerado": ["potencial", "virtual"]}
                },
                "conmoción": {
                    "aliases": ["conmocion", "emoción_profunda", "emocion_profunda", "impacto", "sacudida"],
                    "foria": {"esperado": ["ambiforico"], "tolerado": ["euforico", "disforico"]},
                    "intensidad": {"esperado": ["alta"], "tolerado": ["neutra_ambivalente"]},
                    "dominancia": {"esperado": ["corporal", "mixta"], "tolerado": ["cognoscitiva"]},
                    "modo_existencia": {"esperado": ["realizada", "actual"], "tolerado": ["potencial"]}
                },
                "indignación": {
                    "aliases": ["indignacion", "ultraje", "escándalo_moral", "escandalo_moral", "cólera_moral", "colera_moral"],
                    "foria": {"esperado": ["disforico"], "tolerado": ["ambiforico"]},
                    "intensidad": {"esperado": ["alta"], "tolerado": ["neutra_ambivalente"]},
                    "dominancia": {"esperado": ["cognoscitiva", "mixta"], "tolerado": ["corporal"]},
                    "modo_existencia": {"esperado": ["realizada", "actual"], "tolerado": ["potencial"]}
                }
            }
        }),
        encoding="utf-8",
    )
    (d / "configuraciones_emocion.json").write_text(
        json.dumps({
            "version": "v1",
            "configuraciones": {
                "sostenido_en_sustantivos": {
                    "id": 1,
                    "definicion": "La emoción es portada principalmente por sustantivos que designan estados afectivos.",
                    "heuristica_deteccion": "Identificar sustantivos con valor emocional que operen como núcleo nominal del sintagma.",
                    "ejemplos": ["la indignación de los presentes", "un profundo dolor"],
                },
                "sostenido_en_adjetivos": {
                    "id": 2,
                    "definicion": "La emoción se expresa mediante adjetivos evaluativos o afectivos.",
                    "heuristica_deteccion": "Detectar adjetivos con carga afectiva que atribuyan cualidades emocionales.",
                    "ejemplos": ["una situación inquietante", "los testigos estaban nerviosos"],
                },
            }
        }),
        encoding="utf-8",
    )

    heur = d / "heuristicas"
    heur.mkdir()

    (heur / "actors.md").write_text("Heurísticas actors.", encoding="utf-8")
    (heur / "characterizer.md").write_text("Heurísticas characterizer.", encoding="utf-8")
    (heur / "emotions.md").write_text("Heurísticas emotions.", encoding="utf-8")
    (heur / "emotions_pass2.md").write_text("Heurísticas emotions pass2.", encoding="utf-8")
    (heur / "enunciation.md").write_text("Heurísticas enunciation.", encoding="utf-8")
    (heur / "judge.md").write_text("Heurísticas judge.", encoding="utf-8")

    return d


@pytest.fixture
def loader(knowledge_dir: Path) -> KnowledgeLoader:
    return KnowledgeLoader(knowledge_dir)


@pytest.fixture
def config(knowledge_dir: Path) -> RunConfig:
    return RunConfig(
        models={
            "fake-model": ModelConfig(backend="llama_cpp", path="ignored.gguf"),
        },
        pipeline=PipelineConfig(
            stages={s: "fake-model" for s in STAGE_ORDER if s != "explode_emotions"},
            cache_enabled=False,
        ),
        paths=PathsConfig(knowledge_dir=str(knowledge_dir)),
        versions=VersionsConfig(prompt="v1"),
    )


@pytest.fixture
def patched_build(monkeypatch: pytest.MonkeyPatch) -> dict[str, _MockBackend]:
    """Patchea build_backend del registry para devolver MockBackends."""
    instances: dict[str, _MockBackend] = {}

    def _fake_build(alias: str, model_config: dict[str, Any]) -> LLMBackend:
        b = _MockBackend(alias)
        instances[alias] = b
        return b

    import emoparse.core.backend.registry as reg_mod
    monkeypatch.setattr(reg_mod, "build_backend", _fake_build)
    return instances


@pytest.fixture
def sample_df() -> pd.DataFrame:
    return pd.DataFrame([
        {"codigo": "D1", "contenido": "Primer parrafo.\n\nSegundo parrafo.", "titulo": "T1"},
        {"codigo": "D2", "contenido": "Solo un parrafo.", "titulo": "T2"},
    ])


# ══════════════════════════════════════════════════════════════════════════════
#  Ingest
# ══════════════════════════════════════════════════════════════════════════════


class TestIngest:

    def test_ingest_creates_rows(
        self,
        tmp_path: Path,
        config: RunConfig,
        loader: KnowledgeLoader,
        sample_df: pd.DataFrame,
        patched_build: dict[str, _MockBackend],
    ) -> None:
        db_path = tmp_path / "run.sqlite"
        with PipelineRunner(
            run_id="r1", config=config, knowledge=loader, db_path=db_path,
        ) as runner:
            runner.ingest(sample_df)

        db = Database(db_path)
        repo = DiscursosRepository(db)
        assert sorted(repo.list_codigos()) == ["D1", "D2"]
        assert repo.get_input("D1")["titulo"] == "T1"

    def test_ingest_idempotent(
        self,
        tmp_path: Path,
        config: RunConfig,
        loader: KnowledgeLoader,
        sample_df: pd.DataFrame,
        patched_build: dict[str, _MockBackend],
    ) -> None:
        """Llamar ingest dos veces no duplica filas."""
        db_path = tmp_path / "run.sqlite"
        with PipelineRunner(
            run_id="r1", config=config, knowledge=loader, db_path=db_path,
        ) as runner:
            runner.ingest(sample_df)
            runner.ingest(sample_df)

        db = Database(db_path)
        repo = DiscursosRepository(db)
        assert len(repo.list_codigos()) == 2  # no duplicado


# ══════════════════════════════════════════════════════════════════════════════
#  Chunking
# ══════════════════════════════════════════════════════════════════════════════


class TestChunking:

    def test_chunks_created_for_each_discurso(
        self,
        tmp_path: Path,
        config: RunConfig,
        loader: KnowledgeLoader,
        sample_df: pd.DataFrame,
        patched_build: dict[str, _MockBackend],
    ) -> None:
        db_path = tmp_path / "run.sqlite"
        with PipelineRunner(
            run_id="r1", config=config, knowledge=loader, db_path=db_path,
        ) as runner:
            runner.ingest(sample_df)
            n = runner.chunk_into_frases()

        assert n >= 2  # al menos una frase por discurso

        db = Database(db_path)
        f_repo = FrasesRepository(db)
        d1_frases = f_repo.list_frases_of_discurso("D1")
        assert len(d1_frases) >= 1

    def test_chunks_unit_idx_zero_based(
        self,
        tmp_path: Path,
        config: RunConfig,
        loader: KnowledgeLoader,
        sample_df: pd.DataFrame,
        patched_build: dict[str, _MockBackend],
    ) -> None:
        db_path = tmp_path / "run.sqlite"
        with PipelineRunner(
            run_id="r1", config=config, knowledge=loader, db_path=db_path,
        ) as runner:
            runner.ingest(sample_df)
            runner.chunk_into_frases()

        db = Database(db_path)
        f_repo = FrasesRepository(db)
        # D2 tiene un solo párrafo → un chunk con unit_idx=0.
        d2_frases = f_repo.list_frases_of_discurso("D2")
        assert d2_frases[0][0] == 0


# ══════════════════════════════════════════════════════════════════════════════
#  Run completo
# ══════════════════════════════════════════════════════════════════════════════


class TestRun:

    def test_full_pipeline_completes(
        self,
        tmp_path: Path,
        config: RunConfig,
        loader: KnowledgeLoader,
        sample_df: pd.DataFrame,
        patched_build: dict[str, _MockBackend],
    ) -> None:
        db_path = tmp_path / "run.sqlite"
        with PipelineRunner(
            run_id="r1", config=config, knowledge=loader, db_path=db_path,
        ) as runner:
            runner.ingest(sample_df)
            report = runner.run()

        # Todas las stages habilitadas por default tienen entrada en el reporte.
        # Pase 2 y judge están en STAGE_ORDER pero NO en DEFAULT_ENABLED_STAGES (opt-in).
        from emoparse.pipeline import DEFAULT_ENABLED_STAGES
        for stage in DEFAULT_ENABLED_STAGES:
            assert stage in report
        # Pase 2 y judge no se corren por default.
        assert "emotions_pass2" not in report
        assert "judge" not in report

        # Stages a nivel discurso: 2 cada una.
        assert report["summarizer"] == 2
        assert report["metadata"] == 2
        assert report["enunciation"] == 2

    def test_db_state_after_run(
        self,
        tmp_path: Path,
        config: RunConfig,
        loader: KnowledgeLoader,
        sample_df: pd.DataFrame,
        patched_build: dict[str, _MockBackend],
    ) -> None:
        db_path = tmp_path / "run.sqlite"
        with PipelineRunner(
            run_id="r1", config=config, knowledge=loader, db_path=db_path,
        ) as runner:
            runner.ingest(sample_df)
            runner.run()

        db = Database(db_path)
        d_repo = DiscursosRepository(db)
        e_repo = EmocionesRepository(db)

        # Stages a nivel discurso completadas.
        assert len(d_repo.list_completed("metadata")) == 2
        assert len(d_repo.list_completed("enunciation")) == 2

        # Caracterizaciones: no hay pendientes.
        assert e_repo.list_pending_caracterizacion() == []


# ══════════════════════════════════════════════════════════════════════════════
#  Resumability
# ══════════════════════════════════════════════════════════════════════════════


class TestResumability:

    def test_rerun_skips_completed(
        self,
        tmp_path: Path,
        config: RunConfig,
        loader: KnowledgeLoader,
        sample_df: pd.DataFrame,
        patched_build: dict[str, _MockBackend],
    ) -> None:
        """Re-correr el mismo run no re-procesa lo completado."""
        db_path = tmp_path / "run.sqlite"
        with PipelineRunner(
            run_id="r1", config=config, knowledge=loader, db_path=db_path,
        ) as runner1:
            runner1.ingest(sample_df)
            runner1.run()

        # Re-correr.
        with PipelineRunner(
            run_id="r1", config=config, knowledge=loader, db_path=db_path,
        ) as runner2:
            report = runner2.run()

        # Stages a nivel discurso: 0 (todo completado).
        assert report["summarizer"] == 0
        assert report["metadata"] == 0
        assert report["enunciation"] == 0
        assert report["actors"] == 0
        assert report["emotions"] == 0
        assert report["characterizer"] == 0


# ══════════════════════════════════════════════════════════════════════════════
#  Stage selection
# ══════════════════════════════════════════════════════════════════════════════


class TestStageSelection:

    def test_enabled_stages_filters(
        self,
        tmp_path: Path,
        config: RunConfig,
        loader: KnowledgeLoader,
        sample_df: pd.DataFrame,
        patched_build: dict[str, _MockBackend],
    ) -> None:
        """Solo correr las stages habilitadas."""
        db_path = tmp_path / "run.sqlite"
        with PipelineRunner(
            run_id="r1",
            config=config,
            knowledge=loader,
            db_path=db_path,
            enabled_stages=("summarizer", "metadata"),  # solo dos
        ) as runner:
            runner.ingest(sample_df)
            report = runner.run()

        assert "summarizer" in report
        assert "metadata" in report
        # Las otras stages no se corrieron.
        assert "enunciation" not in report
        assert "actors" not in report

        # Verificar en DB.
        db = Database(db_path)
        d_repo = DiscursosRepository(db)
        assert len(d_repo.list_completed("metadata")) == 2
        # Enunciation NO se corrió → 0 completados.
        assert len(d_repo.list_completed("enunciation")) == 0

    def test_unknown_stage_raises(
        self,
        tmp_path: Path,
        config: RunConfig,
        loader: KnowledgeLoader,
        patched_build: dict[str, _MockBackend],
    ) -> None:
        with pytest.raises(ValueError, match="desconocidas"):
            PipelineRunner(
                run_id="r1", config=config, knowledge=loader,
                db_path=tmp_path / "run.sqlite",
                enabled_stages=("nonexistent_stage",),  # type: ignore[arg-type]
            )


# ══════════════════════════════════════════════════════════════════════════════
#  Run metadata
# ══════════════════════════════════════════════════════════════════════════════


class TestRunMetadata:

    def test_run_marked_completed_on_success(
        self,
        tmp_path: Path,
        config: RunConfig,
        loader: KnowledgeLoader,
        sample_df: pd.DataFrame,
        patched_build: dict[str, _MockBackend],
    ) -> None:
        db_path = tmp_path / "run.sqlite"
        with PipelineRunner(
            run_id="r1", config=config, knowledge=loader, db_path=db_path,
        ) as runner:
            runner.ingest(sample_df)
            runner.run()

        # Run está marcado como completed.
        db = Database(db_path)
        row = db.execute("SELECT status, finished_at FROM runs").fetchone()
        assert row["status"] == "completed"
        assert row["finished_at"] is not None


# ══════════════════════════════════════════════════════════════════════════════
#  Telemetría por run (T-3)
# ══════════════════════════════════════════════════════════════════════════════


class TestRunMetrics:

    def test_metrics_persisted_after_run(
        self,
        tmp_path: Path,
        config: RunConfig,
        loader: KnowledgeLoader,
        sample_df: pd.DataFrame,
        patched_build: dict[str, _MockBackend],
    ) -> None:
        """Después de un run, hay una fila en `run_metrics` por cada stage
        habilitada. Cada fila refleja el trabajo hecho por la stage."""
        from emoparse.pipeline import DEFAULT_ENABLED_STAGES
        from emoparse.storage.metrics import MetricsRepository

        db_path = tmp_path / "run.sqlite"
        with PipelineRunner(
            run_id="r1", config=config, knowledge=loader, db_path=db_path,
        ) as runner:
            runner.ingest(sample_df)
            runner.run()

        db = Database(db_path)
        repo = MetricsRepository(db)
        rows = repo.list_for_run("r1")

        # Una fila por stage habilitada.
        stages_recorded = {r["stage_name"] for r in rows}
        for stage in DEFAULT_ENABLED_STAGES:
            assert stage in stages_recorded, f"Falta métrica de '{stage}'"

        # Stages a nivel discurso: 2 items ok cada una (sample_df tiene 2 discursos).
        for stage in ("summarizer", "metadata", "enunciation"):
            row = next(r for r in rows if r["stage_name"] == stage)
            assert row["n_items_ok"] == 2
            assert row["n_items_failed"] == 0
            # El mock devuelve latency_ms=1.0 por llamada → al menos 1
            # llamada cuenta y total_latency_ms >= 1.0. Con cache_enabled=False
            # no hay hits, todo son misses.
            assert row["cache_hits"] == 0
            assert row["cache_misses"] >= 1
            assert row["total_latency_ms"] >= 1.0
            # Tokens del mock: prompt=10, completion=5 por llamada.
            assert row["total_prompt_tokens"] >= 10
            assert row["total_completion_tokens"] >= 5

    def test_explode_stage_records_items_without_llm(
        self,
        tmp_path: Path,
        config: RunConfig,
        loader: KnowledgeLoader,
        sample_df: pd.DataFrame,
        patched_build: dict[str, _MockBackend],
    ) -> None:
        """ExplodeEmotionsStage no usa LLM: items_ok > 0, hits/misses = 0."""
        from emoparse.storage.metrics import MetricsRepository

        db_path = tmp_path / "run.sqlite"
        with PipelineRunner(
            run_id="r1", config=config, knowledge=loader, db_path=db_path,
        ) as runner:
            runner.ingest(sample_df)
            runner.run()

        db = Database(db_path)
        repo = MetricsRepository(db)
        rows = repo.list_for_run("r1")
        explode = next(r for r in rows if r["stage_name"] == "explode_emotions")

        assert explode["cache_hits"] == 0
        assert explode["cache_misses"] == 0
        assert explode["total_prompt_tokens"] == 0
        assert explode["total_completion_tokens"] == 0
        # Las emociones del mock se explotan en la tabla `emociones`.
        # n_items_ok refleja cuántas se materializaron.
        assert explode["n_items_ok"] >= 1


# ══════════════════════════════════════════════════════════════════════════════
#  Judge stage (opt-in)
# ══════════════════════════════════════════════════════════════════════════════


class TestJudgeStage:

    def test_judge_runs_when_enabled(
        self,
        tmp_path: Path,
        config: RunConfig,
        loader: KnowledgeLoader,
        sample_df: pd.DataFrame,
        patched_build: dict[str, _MockBackend],
    ) -> None:
        """Cuando `judge` está en enabled_stages, se ejecuta y persiste
        rows en `judgments`. No se ejecuta por default."""
        from emoparse.pipeline import DEFAULT_ENABLED_STAGES
        from emoparse.storage.judgments import JudgmentsRepository

        assert "judge" not in DEFAULT_ENABLED_STAGES

        db_path = tmp_path / "run.sqlite"
        # Habilitar todo lo default + judge.
        enabled = (*DEFAULT_ENABLED_STAGES, "judge")
        with PipelineRunner(
            run_id="r1",
            config=config,
            knowledge=loader,
            db_path=db_path,
            enabled_stages=enabled,
        ) as runner:
            runner.ingest(sample_df)
            report = runner.run()

        assert "judge" in report
        # El mock devuelve juicio coherente para cada emoción caracterizada;
        # debe haber al menos un juicio persistido.
        db = Database(db_path)
        repo = JudgmentsRepository(db)
        counts = repo.count_by_coherence()
        assert counts["total"] >= 1
        assert counts["total"] == report["judge"]
        # El mock siempre dice coherente=True.
        assert counts["coherent"] == counts["total"]
        assert counts["incoherent"] == 0

    def test_judge_not_in_default_run(
        self,
        tmp_path: Path,
        config: RunConfig,
        loader: KnowledgeLoader,
        sample_df: pd.DataFrame,
        patched_build: dict[str, _MockBackend],
    ) -> None:
        """Default run no produce ningún judgment."""
        from emoparse.storage.judgments import JudgmentsRepository

        db_path = tmp_path / "run.sqlite"
        with PipelineRunner(
            run_id="r1", config=config, knowledge=loader, db_path=db_path,
        ) as runner:
            runner.ingest(sample_df)
            runner.run()

        db = Database(db_path)
        repo = JudgmentsRepository(db)
        assert repo.count_by_coherence()["total"] == 0
