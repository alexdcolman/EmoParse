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
from emoparse.agents.enunciation import EnunciationAgent, EnunciatorIdAgent
from emoparse.agents.metadata import MetadataAgent
from emoparse.agents.summarizer import SummarizerAgent
from emoparse.config.models import RunConfig
from emoparse.core.backend.base import LLMBackend
from emoparse.core.backend.registry import BackendRegistry
from emoparse.core.backend.retry import RetryConfig
from emoparse.core.cache.backend import CachedBackend
from emoparse.core.cache.repository import CacheRepository
from emoparse.genres.presentation import attach_genre_presentation
from emoparse.inputs.seleccion import Seleccion
from emoparse.knowledge.genre_filter import filtrar_ontologia_por_genero
from emoparse.knowledge.loader import KnowledgeError, KnowledgeLoader
from emoparse.knowledge.normalization import (
    build_emotion_alias_lookup,
    format_emotion_ontology_for_prompt,
)
from emoparse.pipeline.dag import EMOPARSE_DAG
from emoparse.pipeline.genre_context import GenreContextProvider
from emoparse.pipeline.payload_selection import PayloadSelectionEngine
from emoparse.pipeline.stages import (
    ActantsStage,
    ActorsStage,
    CharacterizerStage,
    DeixisStage,
    EmojiAffectStage,
    EmotionsPass2Stage,
    EmotionsStage,
    EnunciationStage,
    ExplodeEmotionsStage,
    HashtagSemioticsStage,
    JudgeStage,
    MetadataStage,
    ModalidadStage,
    NormalizeEmotionsStage,
    ReframingStage,
    SemasStage,
    Stage,
    SummarizerStage,
    TechnoparseStage,
    TecnoUsageStage,
    VisionDescribeStage,
    _FraseStage,
)
from emoparse.storage.db import Database
from emoparse.storage.discursos import DiscursosRepository
from emoparse.storage.emociones import EmocionesRepository
from emoparse.storage.frases import FrasesRepository
from emoparse.storage.hashtags import HashtagsRepository
from emoparse.storage.hilos import HilosRepository
from emoparse.storage.judgments import JudgmentsRepository
from emoparse.storage.menciones import MencionesRepository
from emoparse.storage.metrics import (
    MetricsRepository,
    StageMetricsAccumulator,
)
from emoparse.storage.models import RunContext, Versions
from emoparse.storage.posts import PostsRepository
from emoparse.storage.runs import RunsRepository
from emoparse.storage.tecno import TecnoRepository

if TYPE_CHECKING:
    from emoparse.genres.base import Genre
    from emoparse.inputs.posts_loader import PostsBundle


#: Orden de stages derivado del DAG.
STAGE_ORDER: tuple[str, ...] = EMOPARSE_DAG.toposort()


#: Stages ejecutadas por default.
#: `actants` queda OPT-IN: análisis fino opcional sobre emociones detectadas.
#: `technoparse` y `emoji_affect` quedan OPT-IN por género: las habilitan
#: los géneros de discurso nativo digital (genre.technoparse=True) vía CLI.
#: `reframing`, `hashtag_semiotics`, `tecno_usage` y `modalidad` son
#: OPT-IN explícito (--stages); `modalidad` requiere además el extra `nlp`.
DEFAULT_ENABLED_STAGES: tuple[str, ...] = tuple(
    s
    for s in STAGE_ORDER
    if s
    not in (
        "technoparse",
        "reframing",
        "emoji_affect",
        "hashtag_semiotics",
        "tecno_usage",
        "vision_describe",
        "emotions_pass2",
        "deixis",
        "modalidad",
        "judge",
        "actants",
        "actors",
    )
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
        emotion_scope: tuple[str, ...] | None = None,
        validate_contracts: bool = True,
        ontology_filename: str = "emociones_ontologia.json",
        emotion_modes_filename: str = "emociones.json",
        heuristics_filename: str = "heuristicas.md",
        diccionario_filename: str = "tipos_discurso.json",
        colectivos_filename: str = "colectivos.json",
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
        genre: Genre | None = None,
        embed_context: bool = False,
        selection: Seleccion | None = None,
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
            ontology_filename: Nombre de la ontología léxica de emociones
                dentro de knowledge_dir.
            emotion_modes_filename: Nombre del catálogo de modos de existencia
                de las emociones dentro de knowledge_dir.
            heuristics_filename: Nombre del archivo de heurísticas (fallback
                monolítico si no se especifican los archivos por agente).
            diccionario_filename: Nombre del archivo de tipos de discurso.
            configurations_filename: Nombre del archivo JSON con las 8
                configuraciones del simulacro emocional (TIPO_CONF). Si el
                archivo no existe en knowledge_dir, EmotionsStage falla con
                un mensaje claro: se asume que la knowledge base lo provee.
            actors_kb_filename: Nombre del archivo JSON con la KB de actores
                conocidos (entity linking). Inerte en el pipeline base; se
                conserva por compatibilidad de configuración.
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
            selection: Selector declarativo. Los filtros del input ya llegan
                resueltos; los de payload se activan por stage.
        """
        self._run_id = run_id
        self._cfg = config
        self._knowledge = knowledge
        self._enabled_stages = tuple(enabled_stages)
        self._selection = selection
        self._emotion_scope = tuple(emotion_scope) if emotion_scope else None
        self._validate_contracts = validate_contracts
        self._actors_heuristics_filename = actors_heuristics_filename or heuristics_filename
        self._emotions_heuristics_filename = emotions_heuristics_filename or heuristics_filename
        self._emotions_pass2_heuristics_filename = (
            emotions_pass2_heuristics_filename or heuristics_filename
        )
        self._characterizer_heuristics_filename = characterizer_heuristics_filename
        self._enunciation_heuristics_filename = enunciation_heuristics_filename
        self._judge_heuristics_filename = judge_heuristics_filename
        self._actants_heuristics_filename = actants_heuristics_filename
        self._actants_components = actants_components

        self._embed_context = bool(embed_context)
        if genre is None:
            # Import lazy para no acoplar Runner a registry en hot path.
            from emoparse.genres import default_genre as _default_genre

            self._genre = _default_genre()
        else:
            self._genre = genre
        self._genre_context = (
            GenreContextProvider(self._genre) if self._genre.context_blocks else None
        )

        # Validar que las stages habilitadas son todas conocidas y que
        # forman un subset coherente del DAG.
        unknown = set(self._enabled_stages) - set(STAGE_ORDER)
        if unknown:
            raise ValueError(f"Stages desconocidas: {sorted(unknown)}. Válidas: {STAGE_ORDER}")

        self._ontology_filename = ontology_filename
        self._emotion_modes_filename = emotion_modes_filename
        self._emotion_resources_cache: tuple[str, str, dict[str, str]] | None = None
        self._heuristics_filename = heuristics_filename  # fallback monolítico
        self._diccionario_filename = diccionario_filename
        self._colectivos_filename = colectivos_filename
        self._configurations_filename = configurations_filename
        self._actors_kb_filename = actors_kb_filename
        self._db = Database(Path(db_path))
        self._runs_repo = RunsRepository(self._db)
        self._d_repo = DiscursosRepository(self._db)
        self._f_repo = FrasesRepository(self._db)
        self._e_repo = EmocionesRepository(self._db)
        self._j_repo = JudgmentsRepository(self._db)
        self._m_repo = MencionesRepository(self._db)
        self._p_repo = PostsRepository(self._db)
        self._h_repo = HilosRepository(self._db)
        self._t_repo = TecnoRepository(self._db)
        self._ht_repo = HashtagsRepository(self._db)
        self._cache_repo = CacheRepository(self._db)
        self._metrics_repo = MetricsRepository(self._db)
        self._payload_selection = PayloadSelectionEngine(
            self._db,
            self._selection,
            self._enabled_stages,
        )
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
            config=attach_genre_presentation(
                self._cfg.model_dump(by_alias=False, exclude_none=True),
                self._genre,
            ),
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

    def ingest_posts(self, bundle: PostsBundle) -> None:
        """Persiste el corpus de posts (posts, autores, hilos, media).

        Complementa a `ingest`: los posts analizables ya entraron como
        discursos; acá se guarda la materialidad técnica que `discursos` no
        modela (estructura conversacional, métricas, autores, adjuntos),
        incluidos los reposts puros, que registran circulación sin generar
        discurso propio.
        """
        if bundle.posts.empty:
            logger.warning("[Runner] ingest_posts llamado con bundle vacío.")
            return

        posts_rows = bundle.posts.to_dict(orient="records")
        n_posts = self._p_repo.upsert_posts(posts_rows)

        autores_rows = [
            {
                "plataforma": r["plataforma"],
                "handle": r["handle"],
                "display_name": r.get("display_name"),
                "extras": {"n_posts": int(r.get("n_posts", 0))},
            }
            for r in bundle.autores.to_dict(orient="records")
        ]
        n_autores = self._p_repo.upsert_autores(autores_rows)

        n_media = 0
        for r in posts_rows:
            media = r.get("media") or []
            if isinstance(media, list) and media:
                n_media += self._p_repo.replace_media(str(r["post_id"]), media)

        n_hilos = 0
        if bundle.hilos is not None and not bundle.hilos.empty:
            n_hilos = self._h_repo.upsert_hilos(bundle.hilos.to_dict(orient="records"))

        logger.info(
            f"[Runner] Ingest posts: {n_posts} post(s), {n_autores} autor(es), "
            f"{n_hilos} hilo(s), {n_media} adjunto(s)."
        )

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
            rows = [(codigo, idx, chunk) for idx, chunk in enumerate(chunks)]
            self._f_repo.upsert_frases(rows)
            total += len(rows)

        logger.info(f"[Runner] Chunking: {total} frases creadas.")
        return total

    # ── Run ──────────────────────────────────────────────────────────────────

    def run(self) -> dict[str, int]:
        """Ejecuta todas las etapas habilitadas en orden y devuelve reporte."""

        if not self._frases_exist():
            self.chunk_into_frases()

        self._payload_selection.prepare()
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
            stage.set_selector_scope(self._payload_selection.scope_for(stage_name))
            stage.metrics = accumulator
            stage.validate_contracts = self._validate_contracts
            if isinstance(stage, (_FraseStage, EmotionsPass2Stage)):
                stage.parallel = self._effective_parallel(stage_name)
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

    def _load_referentes_kb_safe(self) -> dict[str, Any]:
        """Carga el referentes_kb; devuelve {} si no existe todavía."""
        try:
            return self._knowledge.load_referentes_kb()
        except KnowledgeError:
            return {}

    def _load_enunciacion_kb_safe(self) -> dict[str, Any]:
        """Carga la KB de enunciación; devuelve {} si es ilegible."""
        try:
            return self._knowledge.load_enunciacion_kb()
        except KnowledgeError:
            return {}

    def _load_colectivos_safe(self) -> dict[str, Any]:
        """Carga la ontología de colectivos; devuelve {} si no existe."""
        try:
            return self._knowledge.load_colectivos(self._colectivos_filename)
        except KnowledgeError:
            return {}

    def _load_semas_vocab_safe(self) -> dict[str, Any]:
        """Carga el vocabulario de semas; devuelve {} si no existe."""
        try:
            return self._knowledge.load_semas()
        except KnowledgeError:
            return {}

    def _load_emoji_lexicon_safe(self) -> dict[str, Any]:
        """Carga knowledge/emoji_afecto.json; devuelve {} si no existe."""
        import json as _json

        path = Path(self._cfg.paths.knowledge_dir).expanduser().resolve() / "emoji_afecto.json"
        if not path.is_file():
            return {}
        try:
            data = _json.loads(path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except (OSError, _json.JSONDecodeError):
            return {}

    def _load_heuristics_safe(self, filename: str) -> str | None:
        """Carga un archivo de heurísticas; None si no existe."""
        try:
            return self._knowledge.load_heuristics(filename)
        except KnowledgeError:
            return None

    def _heuristics_for(self, stage: str, *filenames: str | None) -> str:
        """Heurísticas efectivas de una stage: base más el aporte del género.

        Los `filenames` son los archivos base, en el orden en que deben
        leerse (para `emotions_pass2`, las reglas comunes primero y las
        propias del pase después). Al final se suma el archivo que el género
        declare en `heuristics_overrides` para esa stage, si existe: el
        género agrega sus reglas de lectura sin repetir las comunes.
        Devuelve cadena vacía si no hay ninguna, y en ese caso el template
        omite la sección.
        """
        nombres = [f for f in filenames if f]
        extra = self._genre.heuristics_overrides.get(stage) if self._genre else None
        if extra and extra not in nombres:
            nombres.append(extra)
        bloques = [self._load_heuristics_safe(n) for n in nombres]
        return "\n\n".join(b for b in bloques if b)

    def _load_emotion_resources(self) -> tuple[str, str, dict[str, str]]:
        """Carga y valida vocabulario, modos y aliases para detección.

        La ontología léxica y los modos de existencia son archivos distintos.
        El lookup nunca puede quedar vacío: ante un archivo equivocado o una
        ontología sin emociones, el pipeline falla antes de llamar al modelo.
        """
        if self._emotion_resources_cache is not None:
            return self._emotion_resources_cache

        ontology_raw = filtrar_ontologia_por_genero(
            self._knowledge.load_emotion_ontology(self._ontology_filename),
            self._genre.genre_id,
        )
        emotion_alias_lookup = build_emotion_alias_lookup(
            ontology_raw,
            normalize_accents=True,
        )
        if not emotion_alias_lookup:
            raise KnowledgeError(
                "La ontología léxica de emociones no contiene entradas "
                f"utilizables para el género {self._genre.genre_id!r}: "
                f"{self._ontology_filename!r}. Verificá que no sea el "
                "archivo de modos de existencia."
            )

        ontologia = format_emotion_ontology_for_prompt(ontology_raw)
        if not ontologia.strip():
            raise KnowledgeError(
                "No se pudo formatear la ontología léxica de emociones: "
                f"{self._ontology_filename!r}."
            )
        modos_existencia = self._knowledge.load_ontology(self._emotion_modes_filename)
        if not modos_existencia.strip():
            raise KnowledgeError(
                f"El catálogo de modos de existencia está vacío: {self._emotion_modes_filename!r}."
            )

        self._emotion_resources_cache = (
            ontologia,
            modos_existencia,
            emotion_alias_lookup,
        )
        return self._emotion_resources_cache

    def _build_stage(self, name: str) -> Stage:
        """Construye el Stage con sus dependencias."""
        if name == "technoparse":
            # Determinista, sin LLM ni backend.
            return TechnoparseStage(
                self._d_repo,
                self._f_repo,
                self._t_repo,
                menciones_repo=self._m_repo,
                naturaleza_by_handle=self._p_repo.naturaleza_by_handle(),
            )

        if name == "reframing":
            backend = self._get_backend(name)
            # Emociones ya materializadas del post citado. Es enriquecimiento,
            # no requisito: si explode_emotions no corrió, el provider no
            # encuentra nada y el agente lee el texto citado como hasta ahora.
            from emoparse.pipeline.post_context import (
                make_emociones_detectadas_provider,
            )

            return ReframingStage(
                backend,
                self._p_repo,
                heuristicas=self._load_heuristics_safe("heuristicas/reframing.md"),
                agent_version=self._cfg.versions.prompt,
                retry_config=self._retry_config,
                genre=self._genre,
                emociones_provider=make_emociones_detectadas_provider(self._e_repo),
            )

        if name == "emoji_affect":
            # Híbrida: léxico primero; LLM solo para ambiguos. Sin backend
            # configurado, degrada a léxico-only sin romper.
            backend = None
            try:
                backend = self._get_backend(name)
            except Exception:
                backend = None
            return EmojiAffectStage(
                self._t_repo,
                emoji_lexicon=self._load_emoji_lexicon_safe(),
                backend=backend,
                heuristicas=self._load_heuristics_safe("heuristicas/emoji.md"),
                agent_version=self._cfg.versions.prompt,
                retry_config=self._retry_config,
                genre=self._genre,
            )

        if name == "vision_describe":
            backend = self._get_backend(name)
            return VisionDescribeStage(
                backend,
                self._p_repo,
                agent_version=self._cfg.versions.prompt,
                genre=self._genre,
            )

        if name == "hashtag_semiotics":
            backend = self._get_backend(name)
            return HashtagSemioticsStage(
                backend,
                self._t_repo,
                self._ht_repo,
                heuristicas=self._load_heuristics_safe("heuristicas/hashtags.md"),
                agent_version=self._cfg.versions.prompt,
                retry_config=self._retry_config,
                genre=self._genre,
            )

        if name == "tecno_usage":
            backend = self._get_backend(name)
            return TecnoUsageStage(
                backend,
                self._t_repo,
                heuristicas=self._load_heuristics_safe("heuristicas/tecno_usage.md"),
                agent_version=self._cfg.versions.prompt,
                retry_config=self._retry_config,
                genre=self._genre,
            )

        if name == "summarizer":
            backend = self._get_backend(name)
            agent = SummarizerAgent(
                backend,
                retry_config=self._retry_config,
                genre=self._genre,
            )
            return SummarizerStage(
                agent,
                self._d_repo,
                agent_version=self._cfg.versions.prompt,
                genre_context_provider=self._genre_context,
            )

        if name == "metadata":
            backend = self._get_backend(name)
            diccionario = self._knowledge.load_diccionario_tipos(self._diccionario_filename)
            agent = MetadataAgent(
                backend,
                diccionario,
                retry_config=self._retry_config,
                genre=self._genre,
            )
            return MetadataStage(
                agent,
                self._d_repo,
                agent_version=self._cfg.versions.prompt,
                posts_repo=self._p_repo,
                embed_context_provider=self._embed_provider(),
                hilo_context_provider=self._hilo_provider(),
                genre_context_provider=self._genre_context,
            )

        if name == "enunciation":
            backend = self._get_backend(name)
            heuristicas = (
                self._heuristics_for("enunciation", self._enunciation_heuristics_filename) or None
            )
            agent = EnunciationAgent(
                backend,
                retry_config=self._retry_config,
                genre=self._genre,
                heuristicas=heuristicas,
                colectivos=self._load_colectivos_safe() or None,
                destinatarios_indicadores=(
                    self._knowledge.load_destinatarios_indicadores(self._genre.genre_id) or None
                ),
                tipos_discurso=self._knowledge.load_diccionario_tipos(self._diccionario_filename),
            )
            # Sub-paso de identificación del enunciador: determinista en los
            # géneros con `enunciador_from_handle`; en el resto, un agente
            # mínimo con modelo propio si `pipeline.stages.enunciator_id`
            # está configurado (mismo backend de enunciation si no).
            enunciator_agent = None
            enunciator_release = None
            enunciador_determinista = bool(
                self._genre.enunciador_from_handle or self._genre.enunciador_from_input_field
            )
            if not enunciador_determinista:
                id_alias = self._cfg.pipeline.stages.get("enunciator_id")
                id_backend = self._get_backend("enunciator_id") if id_alias else backend
                enunciator_agent = EnunciatorIdAgent(
                    id_backend,
                    heuristicas=heuristicas,
                    retry_config=self._retry_config,
                )
                # Con modelo propio del sub-paso: descargarlo al terminar la
                # fase de enunciadores, para no sostener dos modelos en VRAM
                # durante el análisis principal. Si otra stage usa el mismo
                # alias, el registry lo recarga cuando haga falta.
                main_alias = self._cfg.pipeline.stages.get("enunciation")
                if id_alias and id_alias != main_alias:

                    def enunciator_release(alias: str = id_alias) -> None:
                        logger.info(
                            f"[Runner] Descargando '{alias}' (sub-paso de "
                            "enunciador) antes del análisis principal."
                        )
                        self._registry.unload(alias)

            return EnunciationStage(
                agent,
                self._d_repo,
                agent_version=self._cfg.versions.prompt,
                enunciator_agent=enunciator_agent,
                genre=self._genre,
                enunciacion_kb=self._load_enunciacion_kb_safe(),
                posts_repo=self._p_repo,
                embed_context_provider=self._embed_provider(),
                hilo_context_provider=self._hilo_provider(),
                enunciator_release=enunciator_release,
                genre_context_provider=self._genre_context,
            )

        if name == "actors":
            backend = self._get_backend(name)
            return ActorsStage(
                backend,
                self._d_repo,
                self._f_repo,
                heuristicas=self._knowledge.load_heuristics(self._actors_heuristics_filename)
                if self._actors_heuristics_filename
                else None,
                agent_version=self._cfg.versions.prompt,
                retry_config=self._retry_config,
                genre=self._genre,
            )

        if name == "emotions":
            backend = self._get_backend(name)
            ontologia, modos_existencia, emotion_alias_lookup = self._load_emotion_resources()
            heuristicas = self._heuristics_for("emotions", self._emotions_heuristics_filename)
            configuraciones = self._knowledge.load_emotion_configurations(
                self._configurations_filename
            )
            hilo_provider = None
            tecno_provider = None
            if self._genre.context_unit == "hilo":
                hilo_provider = self._hilo_provider(
                    max_parents=2,
                    max_chars=1000,
                    include_root=True,
                )
            media_provider = None
            if self._genre.technoparse:
                from emoparse.pipeline.post_context import (
                    make_media_context_provider,
                    make_tecno_context_provider,
                )

                tecno_provider = make_tecno_context_provider(
                    self._t_repo,
                    self._load_emoji_lexicon_safe(),
                    hashtags_como_bloque=True,
                )
                media_provider = make_media_context_provider(self._p_repo)
            if self._embed_provider() is not None:
                from emoparse.pipeline.post_context import (
                    combine_context_providers,
                )

                media_provider = combine_context_providers(
                    self._embed_provider(),
                    media_provider,
                    target_column="media_desc",
                    name="media_y_adjuntos",
                )
            return EmotionsStage(
                backend,
                self._d_repo,
                self._f_repo,
                ontologia=ontologia,
                heuristicas=heuristicas,
                configuraciones=configuraciones,
                modos_existencia=modos_existencia,
                emotion_alias_lookup=emotion_alias_lookup,
                emotion_scope=self._emotion_scope,
                hilo_context_provider=hilo_provider,
                tecno_context_provider=tecno_provider,
                media_context_provider=media_provider,
                genre_context_provider=self._genre_context,
                agent_version=self._cfg.versions.prompt,
                retry_config=self._retry_config,
                genre=self._genre,
            )

        if name == "emotions_pass2":
            backend = self._get_backend(name)
            ontologia, modos_existencia, emotion_alias_lookup = self._load_emotion_resources()
            heuristicas = self._heuristics_for(
                "emotions_pass2",
                self._emotions_heuristics_filename,
                self._emotions_pass2_heuristics_filename,
            )
            configuraciones = self._knowledge.load_emotion_configurations(
                self._configurations_filename
            )
            hilo_provider = None
            tecno_provider = None
            media_provider = None
            hilo_emotion_provider = None
            if self._genre.context_unit == "hilo":
                from emoparse.pipeline.post_context import (
                    make_hilo_emotion_context_provider,
                )

                hilo_provider = self._hilo_provider(max_chars=300)
                hilo_emotion_provider = make_hilo_emotion_context_provider(
                    self._p_repo, self._f_repo
                )
            if self._genre.technoparse:
                from emoparse.pipeline.post_context import (
                    make_media_context_provider,
                    make_tecno_context_provider,
                )

                tecno_provider = make_tecno_context_provider(
                    self._t_repo, self._load_emoji_lexicon_safe()
                )
                media_provider = make_media_context_provider(self._p_repo)
            if self._embed_provider() is not None:
                from emoparse.pipeline.post_context import (
                    combine_context_providers,
                )

                media_provider = combine_context_providers(
                    self._embed_provider(),
                    media_provider,
                    target_column="media_desc",
                    name="media_y_adjuntos",
                )
            return EmotionsPass2Stage(
                backend,
                self._d_repo,
                self._f_repo,
                ontologia=ontologia,
                heuristicas=heuristicas,
                configuraciones=configuraciones,
                modos_existencia=modos_existencia,
                emotion_alias_lookup=emotion_alias_lookup,
                emotion_scope=self._emotion_scope,
                agent_version=self._cfg.versions.prompt,
                retry_config=self._retry_config,
                genre=self._genre,
                hilo_emotion_context_provider=hilo_emotion_provider,
                hilo_context_provider=hilo_provider,
                tecno_context_provider=tecno_provider,
                media_context_provider=media_provider,
            )

        if name == "explode_emotions":
            return ExplodeEmotionsStage(
                self._d_repo,
                self._f_repo,
                self._e_repo,
                self._m_repo,
                referentes_kb=self._load_referentes_kb_safe(),
            )

        if name == "deixis":
            backend = self._get_backend(name)
            return DeixisStage(
                backend,
                self._d_repo,
                self._m_repo,
                agent_version=self._cfg.versions.prompt,
                retry_config=self._retry_config,
                genre=self._genre,
            )

        if name == "modalidad":
            # LLM por defecto para los casos ambiguos; si no hay backend
            # configurado para esta stage, degrada a NLP-only sin romper.
            backend = None
            try:
                backend = self._get_backend(name)
            except Exception:
                backend = None
            nlp_model = getattr(getattr(self._cfg, "modalidad", None), "nlp_model", None)
            return ModalidadStage(
                self._d_repo,
                self._m_repo,
                backend=backend,
                use_llm=backend is not None,
                nlp_model=nlp_model,
                agent_version=self._cfg.versions.prompt,
                retry_config=self._retry_config,
                genre=self._genre,
            )

        if name == "normalize_emotions":
            ontology = self._knowledge.load_emotion_ontology(self._ontology_filename)
            return NormalizeEmotionsStage(
                emociones_repo=self._e_repo,
                emotion_ontology=ontology,
                agent_version=self._cfg.versions.ontology,
            )

        if name == "characterizer":
            backend = self._get_backend(name)
            return CharacterizerStage(
                backend,
                self._d_repo,
                self._f_repo,
                self._e_repo,
                heuristicas=self._knowledge.load_heuristics(self._characterizer_heuristics_filename)
                if self._characterizer_heuristics_filename
                else None,
                agent_version=self._cfg.versions.prompt,
                retry_config=self._retry_config,
                genre=self._genre,
            )

        if name == "semas":
            backend = self._get_backend(name)
            return SemasStage(
                backend,
                self._m_repo,
                semas_vocab=self._load_semas_vocab_safe(),
                agent_version=self._cfg.versions.prompt,
                retry_config=self._retry_config,
                genre=self._genre,
            )

        if name == "judge":
            backend = self._get_backend(name)
            hilo_provider = None
            reframing_provider = None
            if self._genre.context_unit == "hilo":
                from emoparse.pipeline.post_context import (
                    make_reframing_context_provider,
                )

                hilo_provider = self._hilo_provider()
                reframing_provider = make_reframing_context_provider(self._p_repo)
            return JudgeStage(
                backend,
                self._d_repo,
                self._f_repo,
                self._e_repo,
                self._j_repo,
                heuristicas=self._knowledge.load_heuristics(self._judge_heuristics_filename)
                if self._judge_heuristics_filename
                else None,
                ontologia=self._load_emotion_resources()[0],
                agent_version=self._cfg.versions.prompt,
                retry_config=self._retry_config,
                genre=self._genre,
                hilo_context_provider=hilo_provider,
                reframing_provider=reframing_provider,
            )

        if name == "actants":
            backend = self._get_backend(name)
            return ActantsStage(
                backend,
                self._d_repo,
                self._f_repo,
                self._e_repo,
                heuristicas=self._knowledge.load_heuristics(self._actants_heuristics_filename)
                if self._actants_heuristics_filename
                else None,
                enabled_components=self._actants_components,
                agent_version=self._cfg.versions.prompt,
                retry_config=self._retry_config,
                genre=self._genre,
            )

        raise ValueError(f"Stage desconocida: {name}")

    def _effective_parallel(self, stage_name: str) -> int:
        """Parallel efectivo para una stage: `pipeline.parallel` acotado por
        el tipo de backend (in-process → 1)."""
        requested = int(getattr(self._cfg.pipeline, "parallel", 1) or 1)
        if requested <= 1:
            return 1
        alias = self._cfg.pipeline.stages.get(stage_name)
        if alias is None or alias not in self._cfg.models:
            return 1
        backend_kind = self._cfg.models[alias].backend
        if backend_kind == "llama_cpp":
            logger.warning(
                f"[Runner] pipeline.parallel={requested} ignorado para "
                f"'{stage_name}': el backend in-process '{alias}' no admite "
                "concurrencia (usá llama_server para paralelizar)."
            )
            return 1
        return requested

    def _hilo_provider(
        self,
        *,
        max_parents: int = 2,
        max_chars: int = 600,
        include_root: bool = False,
        include_participants: bool = False,
    ):
        """Provider de contexto conversacional, con presupuesto por stage.

        Cada stage recibe el contexto que su margen admite: lo que sobra
        después del prompt estático y del peor caso de generación. `emotions`
        es la que más margen tiene y recibe la cadena larga con los posts de
        las cuentas mencionadas que participan del hilo; `emotions_pass2`, que
        además carga el contexto previo, recibe la versión mínima. Cacheado
        por combinación de parámetros. None si el género no es conversacional.
        """
        if self._genre.context_unit != "hilo":
            return None
        cache = getattr(self, "_hilo_providers_cached", None)
        if cache is None:
            cache = self._hilo_providers_cached = {}
        key = (max_parents, max_chars, include_root, include_participants)
        if key not in cache:
            from emoparse.pipeline.post_context import (
                make_hilo_context_provider,
            )

            cache[key] = make_hilo_context_provider(
                self._p_repo,
                self._h_repo,
                max_parents=max_parents,
                max_chars=max_chars,
                include_root=include_root,
                include_participants=include_participants,
            )
        return cache[key]

    def _embed_provider(self):
        """Provider de contexto de embed (o None si el flag está apagado)."""
        if not self._embed_context:
            return None
        if getattr(self, "_embed_provider_cached", None) is None:
            from emoparse.pipeline.post_context import (
                make_embed_context_provider,
            )

            self._embed_provider_cached = make_embed_context_provider(self._p_repo)
        return self._embed_provider_cached

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
            logger.info(f"[Runner] Descargando '{current_alias}' antes de '{next_stage}'")
            self._registry.unload(current_alias)

    def _next_enabled_stage(self, current: str) -> str | None:
        """Devuelve la próxima stage habilitada después de la actual."""
        try:
            i = STAGE_ORDER.index(current)
        except ValueError:
            return None
        for s in STAGE_ORDER[i + 1 :]:
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
