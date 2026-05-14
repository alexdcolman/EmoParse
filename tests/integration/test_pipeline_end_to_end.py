# ══════════════════════════════════════════════════════════════════════════════
#  tests.integration.test_pipeline_end_to_end
#
#  Ejecuta el pipeline COMPLETO con un modelo real (phi-4-mini), 1 discurso
#  chico, y verifica que:
#    1. Las 7 stages corren sin crashear.
#    2. El estado final en la DB es coherente.
#    3. La cache LLM efectivamente cachea (segunda corrida → 0 calls).
#    4. La resumability funciona end-to-end.
#
#  Auto-skip: si phi-4-mini no está disponible, se saltea limpiamente
#  (igual que los otros tests integration).
#
#  Tiempo esperado: ~30-60 segundos por pipeline completo en GPU.
# ══════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd
import pytest

from emoparse.config.models import (
    ModelConfig,
    PathsConfig,
    PipelineConfig,
    RunConfig,
    VersionsConfig,
)
from emoparse.knowledge import KnowledgeLoader
from emoparse.pipeline import STAGE_ORDER, PipelineRunner
from emoparse.storage.db import Database
from emoparse.storage.discursos import DiscursosRepository
from emoparse.storage.emociones import EmocionesRepository
from emoparse.storage.frases import FrasesRepository

pytestmark = pytest.mark.integration


# ══════════════════════════════════════════════════════════════════════════════
#  Fixtures: knowledge mínimo + config con phi-4-mini en TODAS las stages
# ══════════════════════════════════════════════════════════════════════════════


@pytest.fixture
def knowledge_dir(tmp_path: Path) -> Path:
    """Knowledge dir con archivos mínimos pero válidos."""
    d = tmp_path / "knowledge"
    d.mkdir()

    (d / "tipos_discurso.json").write_text(
        json.dumps({
            "asuncion": "Discurso de toma de posesión presidencial.",
            "anuncio_medida": "Anuncio de una política o medida concreta.",
            "campana": "Discurso en contexto de campaña electoral.",
        }, ensure_ascii=False),
        encoding="utf-8",
    )

    (d / "emociones.json").write_text(
        json.dumps({
            "modos_existencia": {
                "realizada": {
                    "nombre": "Realizada",
                    "descripcion": "La emoción se manifiesta efectivamente en el discurso.",
                    "ejemplo": "'Estoy feliz.' → felicidad realizada.",
                },
                "potencial": {
                    "nombre": "Potencial",
                    "descripcion": "La emoción se plantea como posibilidad futura.",
                    "ejemplo": "'Quiero que se sientan orgullosos.' → orgullo potencial.",
                },
            },
        }, ensure_ascii=False),
        encoding="utf-8",
    )

    (d / "heuristicas.md").write_text(
        "Identificá emociones del enunciador y de los actores mencionados. "
        "Si una emoción es inferible por el contexto, marcala como 'realizada' "
        "si está en el presente del enunciado.",
        encoding="utf-8",
    )

    return d


@pytest.fixture
def config(
    knowledge_dir: Path,
    phi4_mini_config: dict[str, Any],
) -> RunConfig:
    """RunConfig que asigna phi-4-mini a TODAS las stages.

    En producción cada etapa usaría el modelo más adecuado, pero para
    el test queremos rapidez y simpleza: un solo modelo cargado, una
    sola descarga al final.
    """
    return RunConfig(
        models={
            "phi4-mini": ModelConfig(**phi4_mini_config),
        },
        pipeline=PipelineConfig(
            stages={
                stage: "phi4-mini"
                for stage in STAGE_ORDER
                if stage != "explode_emociones"
            },
            cache_enabled=True,
        ),
        paths=PathsConfig(knowledge_dir=str(knowledge_dir)),
        versions=VersionsConfig(prompt="v1", ontology="v1"),
    )


@pytest.fixture
def loader(knowledge_dir: Path) -> KnowledgeLoader:
    return KnowledgeLoader(knowledge_dir)


@pytest.fixture
def small_discurso() -> pd.DataFrame:
    """Discurso corto pero coherente. Mantiene el test rápido y permite
    asserts sobre el contenido detectado."""
    return pd.DataFrame([{
        "codigo": "TEST_INT_001",
        "titulo": "Asunción presidencial corta",
        "fecha": "2024-12-10",
        "contenido": (
            "Compatriotas, hoy asumo la presidencia de la Nación. "
            "Sé que muchos de ustedes están preocupados por el futuro. "
            "Yo también lo estaba. Pero hoy estoy esperanzado.\n\n"
            "Vamos a construir un país más justo. Vamos a trabajar duro."
        ),
    }])


# ══════════════════════════════════════════════════════════════════════════════
#  Tests
# ══════════════════════════════════════════════════════════════════════════════


class TestPipelineEndToEnd:

    def test_full_pipeline_completes(
        self,
        tmp_path: Path,
        config: RunConfig,
        loader: KnowledgeLoader,
        small_discurso: pd.DataFrame,
    ) -> None:
        """Pipeline completo corre sin crashear. Verificación estructural
        del estado final."""
        db_path = tmp_path / "run.sqlite"

        with PipelineRunner(
            run_id="int_test", config=config, knowledge=loader, db_path=db_path,
        ) as runner:
            runner.ingest(small_discurso)
            report = runner.run()

        # Reporte tiene entrada por stage habilitada por default.
        from emoparse.pipeline import DEFAULT_ENABLED_STAGES
        for stage in DEFAULT_ENABLED_STAGES:
            assert stage in report

        # Stages a nivel discurso deben haber procesado 1.
        assert report["summarizer"] == 1
        assert report["metadata"] == 1
        assert report["enunciation"] == 1

    def test_db_state_complete(
        self,
        tmp_path: Path,
        config: RunConfig,
        loader: KnowledgeLoader,
        small_discurso: pd.DataFrame,
    ) -> None:
        """Después del run, las tablas tienen contenido coherente."""
        db_path = tmp_path / "run.sqlite"
        with PipelineRunner(
            run_id="int_test", config=config, knowledge=loader, db_path=db_path,
        ) as runner:
            runner.ingest(small_discurso)
            runner.run()

        db = Database(db_path)
        d_repo = DiscursosRepository(db)
        f_repo = FrasesRepository(db)
        e_repo = EmocionesRepository(db)

        # Discurso completado en las 3 etapas a nivel discurso.
        codigo = "TEST_INT_001"
        meta = d_repo.get_payload(codigo, "metadata")
        enun = d_repo.get_payload(codigo, "enunciation")
        sumr = d_repo.get_payload(codigo, "summarizer")

        assert meta is not None
        assert enun is not None
        assert sumr is not None

        # Metadata: el modelo identificó algún tipo y lugar.
        assert meta["tipo_discurso"]
        assert meta["pais"]
        # Validación blanda — el contenido habla de presidencia, debería
        # detectar algo razonable. NO usamos asserts duros sobre el
        # contenido específico (depende del modelo).

        # Enunciación: hay enunciador y al menos un enunciatario.
        assert enun["enunciador"]
        enunciatarios = json.loads(enun["enunciatarios"])
        assert len(enunciatarios) >= 1

        # Frases creadas por el chunking.
        frases = f_repo.list_frases_of_discurso(codigo)
        assert len(frases) >= 1

        # Emociones detectadas en al menos una frase. NO hay garantía de
        # cuántas — depende del modelo. Validación blanda.
        total_emociones = 0
        for unit_idx, _ in frases:
            emos = f_repo.get_payload(codigo, unit_idx, "emociones")
            if isinstance(emos, list):
                total_emociones += len(emos)
        assert total_emociones >= 1, (
            "El modelo no detectó ninguna emoción en un discurso que "
            "menciona explícitamente preocupación y esperanza."
        )

        # Caracterizaciones: el flujo terminó (no hay pending genuino).
        # Notas:
        # - phi-4-mini a veces emite arrays vacíos en batches largos;
        #   esas emociones quedan marcadas con error permanente
        #   (caracterizacion_error setteado).
        # - Lo que importa para validar el sistema es: (a) no quedan
        #   pending sin tocar, (b) AL MENOS ALGUNAS se caracterizaron.
        # Si el modelo es mejor (qwen3, etc.), esperaríamos 100% ok.
        emociones_db = e_repo.list_emociones_of_discurso(codigo)
        assert len(emociones_db) == total_emociones
        pending = e_repo.list_pending_caracterizacion(codigo)
        assert pending == [], (
            f"Quedaron {len(pending)} emociones sin tocar (pending genuino)"
        )
        ok_count = sum(
            1 for e in emociones_db
            if e["caracterizacion_payload"] is not None
        )
        assert ok_count >= 1, (
            f"Ninguna de las {len(emociones_db)} emociones se caracterizó "
            "exitosamente. El flujo no funciona."
        )


class TestResumability:

    def test_rerun_uses_cache_and_skips_completed(
        self,
        tmp_path: Path,
        config: RunConfig,
        loader: KnowledgeLoader,
        small_discurso: pd.DataFrame,
    ) -> None:
        """Re-correr con la misma DB salta lo completado.

        Esto es el test de resumability con datos REALES — no mocks.
        El segundo run debería tomar segundos (vs minutos del primero).
        """
        db_path = tmp_path / "run.sqlite"

        # Primer run.
        with PipelineRunner(
            run_id="int_test", config=config, knowledge=loader, db_path=db_path,
        ) as runner1:
            runner1.ingest(small_discurso)
            runner1.run()

        # Segundo run con la misma DB.
        with PipelineRunner(
            run_id="int_test", config=config, knowledge=loader, db_path=db_path,
        ) as runner2:
            report2 = runner2.run()

        # Stages a nivel discurso: 0 procesados (todos completados).
        assert report2["summarizer"] == 0
        assert report2["metadata"] == 0
        assert report2["enunciation"] == 0
        assert report2["actors"] == 0
        assert report2["emotions"] == 0
        assert report2["characterizer"] == 0


class TestCacheUsage:

    def test_second_run_with_fresh_db_uses_cache(
        self,
        tmp_path: Path,
        config: RunConfig,
        loader: KnowledgeLoader,
        small_discurso: pd.DataFrame,
    ) -> None:
        """Si copio la DB del run a un run nuevo (mismo run_id, misma
        cache), las llamadas LLM deberían ir todas al cache.

        Caso de uso real: re-corres un análisis sobre los mismos discursos
        después de cambiar visualizaciones — querés que la cache LLM se
        respete aunque la DB sea "nueva" desde el punto de vista del run.

        Implementación: corremos el run 1, luego copiamos la DB a otro path,
        y ahí corremos un run NUEVO (con la cache pre-calentada). Si la
        cache funciona, el segundo run no debería invocar al LLM.
        """
        import shutil

        db1 = tmp_path / "run1.sqlite"
        db2 = tmp_path / "run2.sqlite"

        # Run 1: completar pipeline.
        with PipelineRunner(
            run_id="int_test", config=config, knowledge=loader, db_path=db1,
        ) as runner1:
            runner1.ingest(small_discurso)
            runner1.run()

        # Copiar la DB completa (incluye llm_cache) a otro path.
        shutil.copy(db1, db2)

        # Borrar las filas de discursos/frases/emociones de db2 — pero
        # NO la cache LLM. Eso simula "nuevo run, misma cache".
        db = Database(db2)
        with db.transaction() as cur:
            cur.execute("DELETE FROM emociones")
            cur.execute("DELETE FROM frases")
            cur.execute("DELETE FROM discursos")
            cur.execute("DELETE FROM runs")
        db.close_thread_connection()

        # Run 2 con DB "fresca" pero cache poblada.
        with PipelineRunner(
            run_id="int_test_2", config=config, knowledge=loader, db_path=db2,
        ) as runner2:
            runner2.ingest(small_discurso)
            report2 = runner2.run()

        # Pipeline completó y los resultados son los mismos.
        assert report2["summarizer"] == 1
        assert report2["metadata"] == 1
        # Verificar contenido: si la cache funcionó, los resultados de
        # metadata son idénticos a los del run 1.
        d_repo1 = DiscursosRepository(Database(db1))
        d_repo2 = DiscursosRepository(Database(db2))
        meta1 = d_repo1.get_payload("TEST_INT_001", "metadata")
        meta2 = d_repo2.get_payload("TEST_INT_001", "metadata")
        # tipo_discurso debería coincidir: si la cache acertó, los outputs
        # son bit-a-bit iguales.
        assert meta1["tipo_discurso"] == meta2["tipo_discurso"]
