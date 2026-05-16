# ══════════════════════════════════════════════════════════════════════════════
#  emoparse.pipeline.runner
#
#  Orquestador del pipeline.
# ══════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

import pandas as pd
from loguru import logger

from emoparse.agents.actants import ACTANTS_COMPONENTS
from emoparse.agents.metadata import MetadataAgent
from emoparse.agents.enunciation import EnunciationAgent
from emoparse.agents.summarizer import SummarizerAgent
from emoparse.config.models import RunConfig
from emoparse.core.backend.base import LLMBackend
from emoparse.core.backend.registry import BackendRegistry
from emoparse.core.backend.retry import RetryConfig
from emoparse.core.cache.backend import CachedBackend
from emoparse.core.cache.repository import CacheRepository
from emoparse.knowledge.loader import KnowledgeLoader
from emoparse.pipeline.dag import EMOPARSE_DAG
from emoparse.pipeline.stages import (
    ActantsStage,
    ActorsStage,
    CharacterizerStage,
    EmotionsPass2Stage,
    EmotionsStage,
    EnunciationStage,
    ExplodeEmocionesStage,
    JudgeStage,
    MetadataStage,
    NormalizeActorsStage,
    NormalizeEmotionsStage,
    Stage,
    SummarizerStage,
)
from emoparse.storage.actors_kb_discoveries import ActorsKbDiscoveriesRepository
from emoparse.storage.db import Database
from emoparse.storage.discursos import DiscursosRepository
from emoparse.storage.emociones import EmocionesRepository
from emoparse.storage.frases import FrasesRepository
from emoparse.storage.judgments import JudgmentsRepository
from emoparse.storage.metrics import (
    MetricsRepository,
    StageMetricsAccumulator,
)
from emoparse.storage.models import RunContext, Versions
from emoparse.storage.runs import RunsRepository
from emoparse.genres.registry import DEFAULT_GENRE_ID

if TYPE_CHECKING:
    from emoparse.genres.base import Genre    


#: Orden de stages derivado del DAG.
STAGE_ORDER: tuple[str, ...] = EMOPARSE_DAG.toposort()


#: Stages ejecutadas por default.
#: `normalize_actors` queda OPT-IN: requiere KB poblada y se piloteaba sobre
#: un subset antes de tirarla a producción.
#: `actants` queda OPT-IN: análisis fino opcional sobre emociones detectadas.
DEFAULT_ENABLED_STAGES: tuple[str, ...] = tuple(
    s for s in STAGE_ORDER
    if s not in ("emotions_pass2", "judge", "normalize_actors", "actants")
)


# ══════════════════════════════════════════════════════════════════════════════
#  _MeteredBackend — decorator que registra métricas por llamada.
# ══════════════════════════════════════════════════════════════════════════════


class _MeteredBackend(LLMBackend):
    """LLMBackend decorator que registra métricas por llamada."""

    def __init__(
        self,
        wrapped: LLMBackend,
        accumulator: StageMetricsAccumulator,
    ) -> None:
        self._wrapped = wrapped
        self._accumulator = accumulator
        self.alias = wrapped.alias

    def generate(self, *args: Any, **kwargs: Any) -> Any:
        response = self._wrapped.generate(*args, **kwargs)
        self._accumulator.record_llm_call(
            latency_ms=response.latency_ms,
            prompt_tokens=response.usage.prompt_tokens,
            completion_tokens=response.usage.completion_tokens,
            cache_hit=response.cache_hit,
        )
        return response

    def healthcheck(self) -> bool:
        return self._wrapped.healthcheck()

    def close(self) -> None:
        self._wrapped.close()

    def reset_state(self) -> None:
        self._wrapped.reset_state()

    def __repr__(self) -> str:
        return f"<MeteredBackend wrapping={self._wrapped!r}>"


class PipelineRunner:
    """Orquesta el pipeline completo."""

    def __init__(
        self,
        run_id: str,
        config: RunConfig,
        knowledge: KnowledgeLoader,
        db_path: Path | str,
        *,
        enabled_stages: tuple[str, ...] = DEFAULT_ENABLED_STAGES,
        validate_contracts: bool = True,
        ontology_filename: str = "emociones.json",
        heuristics_filename: str = "heuristicas.md",
        diccionario_filename: str = "tipos_discurso.json",
        configurations_filename: str = "configuraciones_emocion.json",
        actors_kb_filename: str = "actors_kb.json",
        actors_heuristics_filename: str | None = "heuristicas/actors.md",
        emotions_heuristics_filename: str | None = "heuristicas/emotions.md",
        emotions_pass2_heuristics_filename: str | None = "heuristicas/emotions_pass2.md",
        characterizer_heuristics_filename: str | None = "heuristicas/characterizer.md",
        enunciation_heuristics_filename: str | None = "heuristicas/enunciation.md",
        judge_heuristics_filename: str | None = "heuristicas/judge.md",
        actants_heuristics_filename: str | None = "heuristicas/actants.md",
        actants_components: tuple[str, ...] = ACTANTS_COMPONENTS,
        genre: "Genre | None" = None,
    ) -> None:
        """
        Args:
            run_id: Identificador del run (también nombre del
                archivo .sqlite si db_path no se especifica).
            config: RunConfig validado (de `load_config()`).
            knowledge: KnowledgeLoader con knowledge_dir configurado.
            db_path: Path al archivo .sqlite de este run. Si
                existe, se reanuda; si no, se crea.
            enabled_stages: Etapas a ejecutar.
            ontology_filename: Nombre del archivo de ontología de emociones
                dentro de knowledge_dir.
            heuristics_filename: Nombre del archivo de heurísticas (fallback
                monolítico si no se especifican los archivos por agente).
            diccionario_filename: Nombre del archivo de tipos de discurso.
            configurations_filename: Nombre del archivo JSON con las 8
                configuraciones del simulacro emocional (TIPO_CONF). Si el
                archivo no existe en knowledge_dir, EmotionsStage falla con
                un mensaje claro: se asume que la knowledge base lo provee.
            actors_kb_filename: Nombre del archivo JSON con la KB de actores
                conocidos (entity linking). Usado solo si la stage
                `normalize_actors` está habilitada.
            actors_heuristics_filename: Heurísticas para ActorsAgent.
                Si None, usa heuristics_filename.
            emotions_heuristics_filename: Heurísticas para EmotionsAgent (pase 1).
                Si None, usa heuristics_filename.
            emotions_pass2_heuristics_filename: Heurísticas para EmotionsAgentPass2.
                Si None, usa heuristics_filename.
            characterizer_heuristics_filename: Heurísticas para CharacterizerAgent.
                Si None, no se pasan heurísticas (el agente no las requiere por default).
            enunciation_heuristics_filename: Heurísticas para EnunciationAgent.
                Si None, no se pasan heurísticas (el agente no las requiere por default).
            judge_heuristics_filename: Heurísticas para JudgeAgent.
                Si None, no se pasan heurísticas (el agente no las requiere por default).
            actants_heuristics_filename: Heurísticas para ActantsAgent.
                Si None, no se pasan heurísticas (el agente no las requiere por default).
            actants_components: Subconjunto de componentes actanciales que
                el ActantsAgent debe pedirle al LLM. Los no incluidos se
                rellenan con un placeholder determinístico al persistir.
                Default: los cuatro componentes.
            genre: Género del discurso.
        """
        self._run_id = run_id
        self._cfg = config
        self._knowledge = knowledge
        self._enabled_stages = tuple(enabled_stages)
        self._validate_contracts = validate_contracts
        self._actors_heuristics_filename = actors_heuristics_filename or heuristics_filename
        self._emotions_heuristics_filename = emotions_heuristics_filename or heuristics_filename
        self._emotions_pass2_heuristics_filename = emotions_pass2_heuristics_filename or heuristics_filename
        self._characterizer_heuristics_filename = characterizer_heuristics_filename
        self._enunciation_heuristics_filename = enunciation_heuristics_filename
        self._judge_heuristics_filename = judge_heuristics_filename
        self._actants_heuristics_filename = actants_heuristics_filename
        self._actants_components = actants_components

        if genre is None:
            # Import lazy para no acoplar Runner a registry en hot path.
            from emoparse.genres import default_genre as _default_genre
            self._genre = _default_genre()
        else:
            self._genre = genre

        # Validar que las stages habilitadas son todas conocidas y que
        # forman un subset coherente del DAG.
        unknown = set(self._enabled_stages) - set(STAGE_ORDER)
        if unknown:
            raise ValueError(
                f"Stages desconocidas: {sorted(unknown)}. "
                f"Válidas: {STAGE_ORDER}"
            )

        self._ontology_filename = ontology_filename
        self._heuristics_filename = heuristics_filename  # fallback monolítico
        self._diccionario_filename = diccionario_filename
        self._configurations_filename = configurations_filename
        self._actors_kb_filename = actors_kb_filename
        self._db = Database(Path(db_path))
        self._runs_repo = RunsRepository(self._db)
        self._d_repo = DiscursosRepository(self._db)
        self._f_repo = FrasesRepository(self._db)
        self._e_repo = EmocionesRepository(self._db)
        self._j_repo = JudgmentsRepository(self._db)
        self._cache_repo = CacheRepository(self._db)
        self._metrics_repo = MetricsRepository(self._db)
        self._discoveries_repo = ActorsKbDiscoveriesRepository(self._db)
        self._current_accumulator: StageMetricsAccumulator | None = None
        self._ctx = self._build_run_context()
        self._runs_repo.bootstrap(self._ctx)
        self._registry = BackendRegistry(
            {
                alias: cfg.model_config_for_alias(alias)
                for alias, cfg in [(a, config) for a in config.models]
            }
        )

        p = self._cfg.pipeline
        self._retry_config = RetryConfig(
            max_retries=p.max_retries,
            delays_seconds=p.retry_delays_seconds,
        )

    # ── Bootstrap helpers ────────────────────────────────────────────────────

    def _build_run_context(self) -> RunContext:
        """Construye RunContext desde config y run_id."""
        v = self._cfg.versions
        return RunContext(
            run_id=self._run_id,
            versions=Versions(
                knowledge=v.knowledge,
                prompt=v.prompt,
                ontology=v.ontology,
                schema=v.schema_,  # Nota: alias para `schema` reservado.
            ),
            config=self._cfg.model_dump(by_alias=False, exclude_none=True),
        )

    def _wrap_with_cache(self, backend: LLMBackend) -> LLMBackend:
        """Envuelve el backend con CachedBackend si el cache está habilitado."""
        if self._cfg.pipeline.cache_enabled:
            return CachedBackend(backend, self._cache_repo, self._ctx)
        return backend

    def _wrap_with_metrics(
        self,
        backend: LLMBackend,
        accumulator: StageMetricsAccumulator,
    ) -> LLMBackend:
        """Envuelve backend con _MeteredBackend para registrar métricas."""
        return _MeteredBackend(backend, accumulator)

    # ── Ingest ───────────────────────────────────────────────────────────────

    def ingest(self, df: pd.DataFrame) -> None:
        """Carga discursos al storage (upsert)."""
        if df.empty:
            logger.warning("[Runner] Ingest llamado con DF vacío.")
            return

        rows: list[tuple[str, dict[str, Any]]] = []
        for _, row in df.iterrows():
            codigo = str(row["codigo"])
            payload = {k: v for k, v in row.to_dict().items() if k != "codigo"}
            rows.append((codigo, payload))
        self._d_repo.upsert_inputs(rows)
        logger.info(f"[Runner] Ingest: {len(rows)} discurso(s).")

    def chunk_into_frases(
        self,
        chunker: Any | None = None,
    ) -> int:
        """Parte discursos en unidades textuales y las upserta a frases.

        El splitter se despacha según `self._genre.unit`:
          - "frase": `split_into_sentences`. Una unidad ≈ una oración.
                Apropiado para discursos largos donde cada línea
                individual se quiere analizar.
          - "parrafo": `split_into_paragraphs`. Una unidad ≈ un párrafo.
                Útil para textos cuya unidad semántica natural ya es el
                párrafo.
          - "documento": sin chunking. Cada discurso es una sola unidad.
                Apropiado para textos cortos como tuits donde fragmentar
                pierde contexto.
        """
        from emoparse.pipeline.chunking import split_into_sentences
        from emoparse.pipeline.unit_dispatch import (
            split_for,
            split_into_paragraphs,
        )

        if chunker is None:
            unit = self._genre.unit

            if unit == "frase":
                def _genre_chunker(text: str, max_chars: int) -> list[str]:
                    return split_into_sentences(text, max_chars=max_chars)
            elif unit == "parrafo":
                def _genre_chunker(text: str, max_chars: int) -> list[str]:
                    return split_into_paragraphs(text)
            else:  # "documento" — split_for devuelve [text.strip()] o [].
                def _genre_chunker(text: str, max_chars: int) -> list[str]:
                    return split_for(text, "documento")

            chunker = _genre_chunker

        codigos = self._d_repo.list_codigos()
        total = 0
        for codigo in codigos:
            input_data = self._d_repo.get_input(codigo) or {}
            contenido = str(input_data.get("contenido", "")).strip()
            if not contenido:
                continue
            chunks = chunker(contenido, 400)  # max_chars
            rows = [
                (codigo, idx, chunk) for idx, chunk in enumerate(chunks)
            ]
            self._f_repo.upsert_frases(rows)
            total += len(rows)

        logger.info(f"[Runner] Chunking: {total} frases creadas.")
        return total

    # ── Run ──────────────────────────────────────────────────────────────────

    def run(self) -> dict[str, int]:
        """Ejecuta todas las etapas habilitadas en orden y devuelve reporte."""

        if not self._frases_exist():
            self.chunk_into_frases()

        report: dict[str, int] = {}
        try:
            for stage_name in STAGE_ORDER:
                if stage_name not in self._enabled_stages:
                    logger.info(f"[Runner] Stage '{stage_name}' deshabilitada, skip.")
                    continue

                logger.info(f"[Runner] === Stage: {stage_name} ===")
                ok_count = self._run_one_stage(stage_name)
                report[stage_name] = ok_count

                # Liberar VRAM si el siguiente stage usa otro modelo.
                self._maybe_unload_for_next(stage_name)

            self._runs_repo.mark_completed()
        except Exception as e:
            logger.exception(f"[Runner] Falló: {e}")
            self._runs_repo.mark_failed(str(e))
            raise

        logger.info(f"[Runner] Completado. Reporte: {report}")
        return report

    def _run_one_stage(self, stage_name: str) -> int:
        """Construye, ejecuta y persiste métricas de un stage."""
        accumulator = StageMetricsAccumulator()
        self._current_accumulator = accumulator
        try:
            stage = self._build_stage(stage_name)
            stage.metrics = accumulator
            stage.validate_contracts = self._validate_contracts
            ok = stage.run_pending()
        finally:
            self._current_accumulator = None

        self._metrics_repo.insert(
            run_id=self._run_id,
            stage_name=stage_name,
            snapshot=accumulator.snapshot(),
        )
        return ok

    def _frases_exist(self) -> bool:
        """True si ya existen frases en DB."""
        row = self._db.execute("SELECT 1 FROM frases LIMIT 1").fetchone()
        return row is not None

    # ── Construcción de stages ───────────────────────────────────────────────

    def _build_stage(self, name: str) -> Stage:
        """Construye el Stage con sus dependencias."""
        if name == "summarizer":
            backend = self._get_backend(name)
            agent = SummarizerAgent(
                backend,
                retry_config=self._retry_config,
                genre=self._genre,
            )
            return SummarizerStage(
                agent, self._d_repo, agent_version=self._cfg.versions.prompt
            )

        if name == "metadata":
            backend = self._get_backend(name)
            diccionario = self._knowledge.load_diccionario_tipos(
                self._diccionario_filename
            )
            agent = MetadataAgent(
                backend,
                diccionario,
                retry_config=self._retry_config,
                genre=self._genre,
            )
            return MetadataStage(
                agent, self._d_repo, agent_version=self._cfg.versions.prompt
            )

        if name == "enunciation":
            backend = self._get_backend(name)
            diccionario = self._knowledge.load_diccionario_tipos(
                self._diccionario_filename
            )
            genre_for_agent = (
                self._genre if self._genre.genre_id != DEFAULT_GENRE_ID else None
            )
            agent = EnunciationAgent(
                backend, diccionario,
                retry_config=self._retry_config,
                genre=genre_for_agent,
                heuristicas=self._knowledge.load_heuristics(
                    self._enunciation_heuristics_filename
                ) if self._enunciation_heuristics_filename else None,
            )
            return EnunciationStage(
                agent, self._d_repo, agent_version=self._cfg.versions.prompt
            )

        if name == "actors":
            backend = self._get_backend(name)
            return ActorsStage(
                backend, self._d_repo, self._f_repo,
                heuristicas=self._knowledge.load_heuristics(
                    self._actors_heuristics_filename
                ) if self._actors_heuristics_filename else None,
                agent_version=self._cfg.versions.prompt,
                retry_config=self._retry_config,
                genre=self._genre,
            )

        if name == "normalize_actors":
            backend = self._get_backend(name)
            actors_kb = self._knowledge.load_actors_kb(self._actors_kb_filename)
            return NormalizeActorsStage(
                backend, self._d_repo, self._f_repo,
                actors_kb=actors_kb,
                discoveries_repo=self._discoveries_repo,
                agent_version=self._cfg.versions.prompt,
                retry_config=self._retry_config,
                genre=self._genre,
            )

        if name == "emotions":
            backend = self._get_backend(name)
            ontologia = self._knowledge.load_ontology(self._ontology_filename)
            heuristicas = self._knowledge.load_heuristics(
                self._emotions_heuristics_filename
            )
            configuraciones = self._knowledge.load_emotion_configurations(
                self._configurations_filename
            )
            return EmotionsStage(
                backend, self._d_repo, self._f_repo,
                ontologia=ontologia,
                heuristicas=heuristicas,
                configuraciones=configuraciones,
                agent_version=self._cfg.versions.prompt,
                retry_config=self._retry_config,
                genre=self._genre,
            )

        if name == "emotions_pass2":
            backend = self._get_backend(name)
            ontologia = self._knowledge.load_ontology(self._ontology_filename)
            heuristicas = self._knowledge.load_heuristics(
                self._emotions_pass2_heuristics_filename
            )
            configuraciones = self._knowledge.load_emotion_configurations(
                self._configurations_filename
            )
            return EmotionsPass2Stage(
                backend, self._d_repo, self._f_repo,
                ontologia=ontologia,
                heuristicas=heuristicas,
                configuraciones=configuraciones,
                agent_version=self._cfg.versions.prompt,
                retry_config=self._retry_config,
                genre=self._genre,
            )

        if name == "explode_emociones":
            return ExplodeEmocionesStage(
                self._d_repo, self._f_repo, self._e_repo
            )

        if name == "normalize_emotions":
            ontology = self._knowledge.load_emotion_ontology(
                "emociones_ontologia.json"
            )
            return NormalizeEmotionsStage(
                emociones_repo=self._e_repo,
                emotion_ontology=ontology,
                agent_version=self._cfg.versions.ontology,
            )

        if name == "characterizer":
            backend = self._get_backend(name)
            return CharacterizerStage(
                backend, self._d_repo, self._f_repo, self._e_repo,
                heuristicas=self._knowledge.load_heuristics(
                    self._characterizer_heuristics_filename
                ) if self._characterizer_heuristics_filename else None,
                agent_version=self._cfg.versions.prompt,
                retry_config=self._retry_config,
                genre=self._genre,
            )

        if name == "judge":
            backend = self._get_backend(name)
            return JudgeStage(
                backend,
                self._d_repo, self._f_repo, self._e_repo, self._j_repo,
                heuristicas=self._knowledge.load_heuristics(
                    self._judge_heuristics_filename
                ) if self._judge_heuristics_filename else None,
                agent_version=self._cfg.versions.prompt,
                retry_config=self._retry_config,
                genre=self._genre,
            )

        if name == "actants":
            backend = self._get_backend(name)
            return ActantsStage(
                backend, self._d_repo, self._f_repo, self._e_repo,
                heuristicas=self._knowledge.load_heuristics(
                    self._actants_heuristics_filename
                ) if self._actants_heuristics_filename else None,
                enabled_components=self._actants_components,
                agent_version=self._cfg.versions.prompt,
                retry_config=self._retry_config,
                genre=self._genre,
            )

        raise ValueError(f"Stage desconocida: {name}")

    def _get_backend(self, stage_name: str) -> LLMBackend:
        """Devuelve backend con cache y métricas para una stage."""
        alias = self._cfg.pipeline.stages.get(stage_name)
        if alias is None:
            raise ValueError(
                f"No hay alias asignado para la stage '{stage_name}' en "
                f"`pipeline.stages` del config. Stages configuradas: "
                f"{list(self._cfg.pipeline.stages)}"
            )
        raw = self._registry.get(alias)
        cached = self._wrap_with_cache(raw)
        accumulator = getattr(self, "_current_accumulator", None)
        if accumulator is not None:
            return self._wrap_with_metrics(cached, accumulator)
        return cached

    # ── Gestión de VRAM ──────────────────────────────────────────────────────

    def _maybe_unload_for_next(self, current_stage: str) -> None:
        """Descarga el modelo actual si la próxima stage usa otro."""
        next_stage = self._next_enabled_stage(current_stage)
        if next_stage is None:
            return  # Última stage del run; no hay siguiente que comparar

        current_alias = self._cfg.pipeline.stages.get(current_stage)
        next_alias = self._cfg.pipeline.stages.get(next_stage)

        if current_alias is not None and current_alias != next_alias:
            logger.info(
                f"[Runner] Descargando '{current_alias}' antes de '{next_stage}'"
            )
            self._registry.unload(current_alias)

    def _next_enabled_stage(self, current: str) -> str | None:
        """Devuelve la próxima stage habilitada después de la actual."""
        try:
            i = STAGE_ORDER.index(current)
        except ValueError:
            return None
        for s in STAGE_ORDER[i + 1:]:
            if s in self._enabled_stages:
                return s
        return None

    # ── Cleanup ──────────────────────────────────────────────────────────────

    def close(self) -> None:
        """Cierra modelos y conexión a la DB."""
        self._registry.unload_all()
        self._db.close_thread_connection()

    def __enter__(self) -> PipelineRunner:
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()
