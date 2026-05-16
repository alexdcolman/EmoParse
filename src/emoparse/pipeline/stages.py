# ══════════════════════════════════════════════════════════════════════════════
#  emoparse.pipeline.stages
#
#  Etapas del pipeline.
# ══════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from typing import Any, Literal

import pandas as pd
import pandera.pandas as pa
from loguru import logger

from emoparse.agents.actors import ActorsAgent
from emoparse.agents.actants import ACTANTS_COMPONENTS, ActantsAgent
from emoparse.agents.normalize_actors import NormalizeActorsAgent
from emoparse.pipeline.contracts import (
    DiscursoInputContract,
    EmocionExplodedContract,
    FraseConActoresContract,
    FraseConEmocionesContract,
    FraseInputContract,
    FraseParaLinkingContract,
    validate as validate_contract,
)
from emoparse.agents.characterizer import CharacterizerAgent
from emoparse.agents.emotions import (
    EmotionsAgent,
    compute_emotion_rolling_summary,
    compute_emotion_full_summary,
)
from emoparse.agents.emotions_pass2 import EmotionsAgentPass2
from emoparse.agents.judge import JudgeAgent
from emoparse.core.backend.base import LLMBackend
from emoparse.core.backend.retry import RetryConfig
from emoparse.genres.base import Genre
from emoparse.knowledge.normalization import build_emotion_alias_lookup
from emoparse.pipeline.coref import (
    cluster_mentions_within_discurso,
    pick_representative,
)
from emoparse.storage.actors_kb_discoveries import ActorsKbDiscoveriesRepository
from emoparse.storage.discursos import DiscursosRepository
from emoparse.storage.emociones import EmocionesRepository
from emoparse.storage.frases import FrasesRepository
from emoparse.storage.judgments import JudgmentsRepository
from emoparse.storage.metrics import StageMetricsAccumulator


class Stage(ABC):
    """Etapa abstracta del pipeline."""

    NAME: str

    def __init__(self) -> None:
        self.metrics = StageMetricsAccumulator()
        self.validate_contracts: bool = True

    def _validate(
        self,
        contract: type[pa.DataFrameModel],
        df: "pd.DataFrame",
        label: str = "",
    ) -> "pd.DataFrame":
        """Valida df contra el contrato si validate_contracts está activo."""
        if not self.validate_contracts:
            return df
        try:
            return validate_contract(contract, df, lazy=False)
        except pa.errors.SchemaError as e:
            raise pa.errors.SchemaError(
                schema=e.schema,
                data=e.data,
                message=(
                    f"[Stage:{self.NAME}] Contrato {contract.__name__}"
                    + (f" ({label})" if label else "")
                    + f" violado: {e.args[0]}"
                ),
            ) from e

    def reset_metrics(self) -> StageMetricsAccumulator:
        """Resetea acumulador de métricas."""
        self.metrics = StageMetricsAccumulator()
        return self.metrics

    @abstractmethod
    def run_pending(self) -> int:
        """Procesa los items pendientes de la etapa."""


# ══════════════════════════════════════════════════════════════════════════════
#  Etapas a nivel discurso
# ══════════════════════════════════════════════════════════════════════════════

class _DiscursoStage(Stage):
    """Base para etapas que procesan discursos en la tabla discursos."""

    STAGE_KEY: str  # "summarizer" | "metadata" | "enunciation"

    def __init__(
        self,
        agent: Any,
        discursos_repo: DiscursosRepository,
        agent_version: str | None = None,
    ) -> None:
        super().__init__()
        self._agent = agent
        self._repo = discursos_repo
        self._version = agent_version

    def run_pending(self) -> int:
        codigos = self._repo.list_pending(self.STAGE_KEY)  # type: ignore[arg-type]
        if not codigos:
            logger.info(f"[Stage:{self.NAME}] Nada pendiente.")
            return 0

        logger.info(f"[Stage:{self.NAME}] Procesando {len(codigos)} discurso(s)")
        ok = 0
        for i, codigo in enumerate(codigos):
            input_data = self._repo.get_input(codigo)
            if input_data is None:
                logger.warning(
                    f"[Stage:{self.NAME}] {codigo}: sin input en DB, salteando"
                )
                continue

            # Construir un DF de 1 fila para reutilizar la API run() del agente.
            row_dict = {"codigo": codigo, **input_data}
            df_in = pd.DataFrame([row_dict])

            self._validate(DiscursoInputContract, df_in, "entrada")

            try:
                df_out = self._agent.run(df_in)
            except Exception as e:
                logger.error(
                    f"[Stage:{self.NAME}] {codigo}: error inesperado: {e}"
                )
                self._repo.set_error(codigo, self.STAGE_KEY, str(e))  # type: ignore[arg-type]
                self.metrics.record_item_failed()
                continue

            # El agente devuelve None en las columnas si falló internamente.
            row = df_out.iloc[0]
            payload = self._extract_payload(row)
            if payload is None:
                self._repo.set_error(
                    codigo,
                    self.STAGE_KEY,  # type: ignore[arg-type]
                    "Backend error (ver logs del agente)",
                )
                self.metrics.record_item_failed()
                continue

            self._repo.set_payload(
                codigo,
                self.STAGE_KEY,  # type: ignore[arg-type]
                payload,
                version=self._version,
            )
            ok += 1
            self.metrics.record_item_ok()

            if (i + 1) % 10 == 0:
                logger.info(f"[Stage:{self.NAME}] {i + 1}/{len(codigos)}")

        logger.info(
            f"[Stage:{self.NAME}] Completado: {ok}/{len(codigos)} ok, "
            f"{len(codigos) - ok} con error."
        )
        return ok

    @abstractmethod
    def _extract_payload(self, row: pd.Series) -> dict[str, Any] | None:
        """Extrae payload desde una row del agente."""


class SummarizerStage(_DiscursoStage):
    NAME = "summarizer"
    STAGE_KEY = "summarizer"

    def _extract_payload(self, row: pd.Series) -> dict[str, Any] | None:
        """Payload con resumen_global y resumen_fragmentos."""
        if pd.isna(row.get("resumen_global")) and pd.isna(row.get("resumen_fragmentos")):
            return None
        return {
            "resumen_global": row.get("resumen_global"),
            "resumen_fragmentos": row.get("resumen_fragmentos"),
        }


class MetadataStage(_DiscursoStage):
    NAME = "metadata"
    STAGE_KEY = "metadata"

    def _extract_payload(self, row: pd.Series) -> dict[str, Any] | None:
        """Payload con tipo_discurso y lugar."""
        if pd.isna(row.get("tipo_discurso")):
            return None
        return {
            "tipo_discurso": row.get("tipo_discurso"),
            "tipo_discurso_justificacion": row.get("tipo_discurso_justificacion"),
            "ciudad": row.get("ciudad"),
            "provincia": row.get("provincia"),
            "pais": row.get("pais"),
            "lugar_justificacion": row.get("lugar_justificacion"),
        }


class EnunciationStage(_DiscursoStage):
    NAME = "enunciation"
    STAGE_KEY = "enunciation"

    def _extract_payload(self, row: pd.Series) -> dict[str, Any] | None:
        """Payload con enunciador y enunciatarios."""
        if pd.isna(row.get("enunciador")):
            return None
        # `enunciatarios` ya es string JSON desde el agente.
        return {
            "enunciador": row.get("enunciador"),
            "enunciador_justificacion": row.get("enunciador_justificacion"),
            "enunciatarios": row.get("enunciatarios"),
        }


# ══════════════════════════════════════════════════════════════════════════════
#  Etapas a nivel frase
# ══════════════════════════════════════════════════════════════════════════════

class _FraseStage(Stage):
    """Base para etapas que procesan frases."""

    STAGE_KEY: str  # "actores" | "emociones"

    def __init__(
        self,
        backend: LLMBackend,
        discursos_repo: DiscursosRepository,
        frases_repo: FrasesRepository,
        agent_version: str | None = None,
        retry_config: RetryConfig | None = None,
        genre: Genre | None = None,
    ) -> None:
        super().__init__()
        self._backend = backend
        self._d_repo = discursos_repo
        self._f_repo = frases_repo
        self._version = agent_version
        self._retry_config = retry_config
        self._genre = genre

    def run_pending(self) -> int:
        """Procesa frases pendientes agrupadas por discurso."""
        all_pending = self._f_repo.list_pending(self.STAGE_KEY)  # type: ignore[arg-type]
        if not all_pending:
            logger.info(f"[Stage:{self.NAME}] Nada pendiente.")
            return 0

        by_codigo: dict[str, list[int]] = {}
        for codigo, unit_idx in all_pending:
            by_codigo.setdefault(codigo, []).append(unit_idx)

        logger.info(
            f"[Stage:{self.NAME}] Procesando {len(by_codigo)} discurso(s) "
            f"con {sum(len(v) for v in by_codigo.values())} frases pendientes."
        )

        total_ok = 0
        for codigo, pending_idxs in by_codigo.items():
            input_data = self._d_repo.get_input(codigo) or {}

            agent = self._build_agent(input_data, codigo)

            df_in = self._build_input_df(codigo, pending_idxs)
            if df_in.empty:
                continue
            self._validate(self._input_contract(), df_in, "entrada")

            try:
                df_out = agent.run(df_in)
            except Exception as e:
                logger.error(
                    f"[Stage:{self.NAME}] {codigo}: error inesperado: {e}"
                )
                for idx in pending_idxs:
                    self._f_repo.set_error(
                        codigo, idx, self.STAGE_KEY, str(e)  # type: ignore[arg-type]
                    )
                    self.metrics.record_item_failed()
                continue

            for _, row in df_out.iterrows():
                idx = int(row["unit_idx"])
                payload_raw = self._extract_payload(row)
                if payload_raw is None:
                    self._f_repo.set_error(
                        codigo, idx, self.STAGE_KEY,  # type: ignore[arg-type]
                        "Backend error (ver logs del agente)",
                    )
                    self.metrics.record_item_failed()
                    continue
                self._f_repo.set_payload(
                    codigo, idx, self.STAGE_KEY,  # type: ignore[arg-type]
                    payload_raw,
                    version=self._version,
                )
                total_ok += 1
                self.metrics.record_item_ok()

        logger.info(f"[Stage:{self.NAME}] Completado: {total_ok} frases ok.")
        return total_ok

    def _build_input_df(
        self,
        codigo: str,
        unit_idxs: list[int],
    ) -> pd.DataFrame:
        """Construye DataFrame con frases pendientes."""
        rows: list[dict[str, Any]] = []
        for idx in unit_idxs:
            frase = self._f_repo.get_frase(codigo, idx)
            if frase is None:
                continue
            rows.append({
                "codigo": codigo,
                "unit_idx": idx,
                "frase": frase,
            })
        return pd.DataFrame(rows)

    def _input_contract(self) -> type[pa.DataFrameModel]:
        """Contrato Pandera para el DF de entrada."""
        return FraseInputContract

    @abstractmethod
    def _build_agent(self, input_data: dict[str, Any], codigo: str) -> Any:
        """Construye el agente con el contexto del discurso."""

    @abstractmethod
    def _extract_payload(self, row: pd.Series) -> Any:
        """Extrae el payload a guardar para una row del output del agente."""


class ActorsStage(_FraseStage):
    NAME = "actors"
    STAGE_KEY = "actores"

    def __init__(
        self,
        backend: LLMBackend,
        discursos_repo: DiscursosRepository,
        frases_repo: FrasesRepository,
        heuristicas: str | None = None,
        agent_version: str | None = None,
        retry_config: RetryConfig | None = None,
        genre: Genre | None = None,
    ) -> None:
        super().__init__(backend, discursos_repo, frases_repo, agent_version, retry_config, genre)
        self._heuristicas = heuristicas

    def _build_agent(
        self, input_data: dict[str, Any], codigo: str
    ) -> ActorsAgent:
        # Los metadatos pueden no estar: usar defaults seguros.
        meta = self._d_repo.get_payload(codigo, "metadata") or {}
        enun = self._d_repo.get_payload(codigo, "enunciation") or {}
        return ActorsAgent(
            self._backend,
            titulo=str(input_data.get("titulo", "")),
            tipo_discurso=str(meta.get("tipo_discurso", "")),
            enunciador=str(enun.get("enunciador", "")),
            heuristicas=self._heuristicas,
            retry_config=self._retry_config,
            genre=self._genre,
        )

    def _extract_payload(self, row: pd.Series) -> Any:
        """Payload con actores deserializados desde JSON."""
        actores_str = row.get("actores")
        if pd.isna(actores_str):
            return None
        try:
            return json.loads(actores_str)
        except (json.JSONDecodeError, TypeError):
            return None


# ══════════════════════════════════════════════════════════════════════════════
#  NormalizeActorsStage
# ══════════════════════════════════════════════════════════════════════════════

class NormalizeActorsStage(Stage):
    """Linkea menciones de actores contra una KB conocida (opt-in).

    Procesamiento por discurso:
      A. Coref intra-discurso por heurística léxica conservadora
         (`pipeline.coref.cluster_mentions_within_discurso`). Las menciones
         que claramente refieren a la misma entidad se agrupan; se llama
         al LLM una sola vez por cluster en lugar de una por mención.
      B. Entity linking con LLM contra la KB: para cada cluster, se envía
         la mención representativa + un contexto breve (la frase) y se
         obtiene `actor_canonico` o `es_nuevo=True`.
      C. Persistencia: el linking se propaga a TODAS las menciones del
         cluster y se escribe en `frases.actores_canonicos_payload` (una
         lista, en el orden original de actores por frase). Las entidades
         nuevas (`es_nuevo=true`) se acumulan en `actors_kb_discoveries`
         para revisión humana.

    La stage es OPT-IN: no se incluye en `DEFAULT_ENABLED_STAGES`. El
    pipeline de emociones no depende de ella, por lo que puede correrse
    a posteriori sobre runs existentes sin invalidar resultados.
    """

    NAME = "normalize_actors"
    STAGE_KEY = "actores_canonicos"

    def __init__(
        self,
        backend: LLMBackend,
        discursos_repo: DiscursosRepository,
        frases_repo: FrasesRepository,
        actors_kb: dict[str, Any],
        discoveries_repo: ActorsKbDiscoveriesRepository | None = None,
        agent_version: str | None = None,
        retry_config: RetryConfig | None = None,
        genre: Genre | None = None,
    ) -> None:
        super().__init__()
        self.validate_contracts = True
        self._backend = backend
        self._d_repo = discursos_repo
        self._f_repo = frases_repo
        self._discoveries_repo = discoveries_repo
        self._kb = actors_kb
        self._kb_serialized = self._serialize_kb(actors_kb)
        self._version = agent_version
        self._retry_config = retry_config
        self._genre = genre

    # ── API ──────────────────────────────────────────────────────────────────

    def run_pending(self) -> int:
        """Procesa frases pendientes agrupadas por discurso."""
        all_pending = self._f_repo.list_pending(self.STAGE_KEY)  # type: ignore[arg-type]
        if not all_pending:
            logger.info(f"[Stage:{self.NAME}] Nada pendiente.")
            return 0

        by_codigo: dict[str, list[int]] = {}
        for codigo, unit_idx in all_pending:
            by_codigo.setdefault(codigo, []).append(unit_idx)

        logger.info(
            f"[Stage:{self.NAME}] Procesando {len(by_codigo)} discurso(s) "
            f"con {sum(len(v) for v in by_codigo.values())} frases pendientes."
        )

        total_ok = 0
        for codigo, pending_idxs in by_codigo.items():
            total_ok += self._process_discurso(codigo, set(pending_idxs))

        logger.info(f"[Stage:{self.NAME}] Completado: {total_ok} frases ok.")
        return total_ok

    # ── Procesamiento por discurso ───────────────────────────────────────────

    def _process_discurso(
        self,
        codigo: str,
        pending_idxs: set[int],
    ) -> int:
        """Procesa todas las frases pendientes de un discurso.

        El coref aprovecha menciones de todas las frases del discurso
        (no solo las pendientes) para tener contexto completo. El linking
        se aplica únicamente a las frases pendientes.
        """
        actors_by_frase: list[tuple[int, list[dict]]] = []
        actors_by_frase_map: dict[int, list[dict]] = {}
        frases_text: dict[int, str] = {}

        for unit_idx, frase_text in self._f_repo.list_frases_of_discurso(codigo):
            frases_text[unit_idx] = frase_text
            actores_payload = self._f_repo.get_payload(codigo, unit_idx, "actores")
            if not isinstance(actores_payload, list):
                if unit_idx in pending_idxs:
                    self._f_repo.set_payload(
                        codigo, unit_idx, self.STAGE_KEY,  # type: ignore[arg-type]
                        [],
                        version=self._version,
                    )
                    self.metrics.record_item_ok()
                continue
            actors_by_frase.append((unit_idx, actores_payload))
            actors_by_frase_map[unit_idx] = actores_payload

        if not actors_by_frase:
            return 0

        # Paso A: coref léxico.
        clusters = cluster_mentions_within_discurso(actors_by_frase)

        # Paso B: linking por cluster (una fila por cluster que toca alguna
        # frase pendiente).
        df_in, _ = self._build_linking_df(
            codigo,
            clusters,
            actors_by_frase_map,
            frases_text,
            pending_idxs,
        )

        cluster_link: dict[int, dict[str, Any]] = {}

        if not df_in.empty:
            self._validate(FraseParaLinkingContract, df_in, "entrada")
            agent = NormalizeActorsAgent(
                self._backend,
                actors_kb_serialized=self._kb_serialized,
                retry_config=self._retry_config,
                genre=self._genre,
            )
            try:
                df_out = agent.run(df_in)
            except Exception as e:
                logger.error(
                    f"[Stage:{self.NAME}] {codigo}: error inesperado: {e}"
                )
                for unit_idx in pending_idxs:
                    self._f_repo.set_error(
                        codigo, unit_idx, self.STAGE_KEY, str(e)  # type: ignore[arg-type]
                    )
                    self.metrics.record_item_failed()
                return 0

            for _, row in df_out.iterrows():
                cluster_idx = int(row["cluster_idx"])
                actores_canonicos_str = row.get("actores_canonicos")
                if pd.isna(actores_canonicos_str):
                    cluster_link[cluster_idx] = self._unknown_linking_dict()
                    continue
                try:
                    linkings = json.loads(actores_canonicos_str)
                except (json.JSONDecodeError, TypeError):
                    cluster_link[cluster_idx] = self._unknown_linking_dict()
                    continue
                if isinstance(linkings, list) and linkings:
                    cluster_link[cluster_idx] = linkings[0]
                else:
                    cluster_link[cluster_idx] = self._unknown_linking_dict()

        # Paso C: persistencia por frase pendiente.
        total_ok = 0
        for unit_idx in pending_idxs:
            actores = actors_by_frase_map.get(unit_idx)
            if actores is None:
                continue

            payload: list[dict[str, Any]] = []
            for mention_idx, actor in enumerate(actores):
                mention_key = (unit_idx, mention_idx)
                cluster_idx = self._find_cluster_idx(mention_key, clusters)
                if cluster_idx is None or cluster_idx not in cluster_link:
                    payload.append(self._unknown_linking_dict(
                        actor_mencionado=str(actor.get("actor", "")),
                    ))
                    continue
                link = dict(cluster_link[cluster_idx])
                # actor_mencionado debe reflejar la mención de esta frase,
                # no la del representante del cluster.
                link["actor_mencionado"] = str(actor.get("actor", ""))
                payload.append(link)

            self._f_repo.set_payload(
                codigo, unit_idx, self.STAGE_KEY,  # type: ignore[arg-type]
                payload,
                version=self._version,
            )
            total_ok += 1
            self.metrics.record_item_ok()

            if self._discoveries_repo is not None:
                for link in payload:
                    if link.get("es_nuevo") is True:
                        self._discoveries_repo.insert(
                            codigo=codigo,
                            unit_idx=unit_idx,
                            actor_mencionado=str(link.get("actor_mencionado", "")),
                            confianza=str(link.get("confianza", "baja")),
                            contexto=frases_text.get(unit_idx),
                            justificacion=str(link.get("justificacion", "")),
                        )

        return total_ok

    # ── Helpers ──────────────────────────────────────────────────────────────

    def _build_linking_df(
        self,
        codigo: str,
        clusters: list[set[tuple[int, int]]],
        actors_by_frase_map: dict[int, list[dict]],
        frases_text: dict[int, str],
        pending_idxs: set[int],
    ) -> tuple[pd.DataFrame, dict[int, int]]:
        """Una fila por cluster que toca alguna frase pendiente."""
        rows: list[dict[str, Any]] = []
        cluster_to_row: dict[int, int] = {}

        for cluster_idx, cluster in enumerate(clusters):
            touched_pending = any(uidx in pending_idxs for uidx, _ in cluster)
            if not touched_pending:
                continue

            rep_name = pick_representative(cluster, actors_by_frase_map)
            if not rep_name:
                continue

            rep_unit_idx: int | None = None
            for uidx, _ in sorted(cluster):
                if uidx in pending_idxs:
                    rep_unit_idx = uidx
                    break
            if rep_unit_idx is None:
                rep_unit_idx = next(iter(sorted(cluster)))[0]

            frase = frases_text.get(rep_unit_idx, "")
            actores_a_linkear = json.dumps(
                [{"actor": rep_name, "tipo": "?"}],
                ensure_ascii=False,
            )

            cluster_to_row[cluster_idx] = len(rows)
            rows.append({
                "codigo": codigo,
                "unit_idx": rep_unit_idx,
                "frase": frase,
                "actores_a_linkear": actores_a_linkear,
                "cluster_idx": cluster_idx,
            })

        return pd.DataFrame(rows), cluster_to_row

    @staticmethod
    def _find_cluster_idx(
        mention_key: tuple[int, int],
        clusters: list[set[tuple[int, int]]],
    ) -> int | None:
        """Devuelve el índice del cluster que contiene la mención."""
        for i, c in enumerate(clusters):
            if mention_key in c:
                return i
        return None

    @staticmethod
    def _serialize_kb(kb: dict[str, Any]) -> str:
        """Serializa la KB en formato compacto para el system prompt."""
        actors = kb.get("actors") or {}
        if not isinstance(actors, dict) or not actors:
            return "(KB vacía)"
        lines: list[str] = []
        for canonical_id, entry in actors.items():
            if not isinstance(entry, dict):
                continue
            display = str(entry.get("display_name", canonical_id))
            tipo = str(entry.get("tipo", "?"))
            aliases = entry.get("aliases") or []
            aliases_str = "; ".join(str(a) for a in aliases) if aliases else "(sin aliases)"
            lines.append(
                f"- {canonical_id} [tipo={tipo}]: {display} | aliases: {aliases_str}"
            )
        return "\n".join(lines)

    @staticmethod
    def _unknown_linking_dict(actor_mencionado: str = "") -> dict[str, Any]:
        """Linking de fallback cuando el LLM falló o no devolvió resultado."""
        return {
            "actor_mencionado": actor_mencionado,
            "actor_canonico": None,
            "confianza": "baja",
            "es_nuevo": False,
            "justificacion": "Sin linking (backend error o cluster sin output).",
        }


# ══════════════════════════════════════════════════════════════════════════════
#  EmotionsStage
# ══════════════════════════════════════════════════════════════════════════════


class EmotionsStage(_FraseStage):
    NAME = "emotions"
    STAGE_KEY = "emociones"

    def _input_contract(self) -> type[pa.DataFrameModel]:
        """Contrato: frases con actores ya procesados."""
        return FraseConActoresContract

    def __init__(
        self,
        backend: LLMBackend,
        discursos_repo: DiscursosRepository,
        frases_repo: FrasesRepository,
        ontologia: str,
        heuristicas: str,
        configuraciones: str = "",
        agent_version: str | None = None,
        retry_config: RetryConfig | None = None,
        genre: Genre | None = None,
    ) -> None:
        super().__init__(backend, discursos_repo, frases_repo, agent_version, retry_config, genre)
        self._ontologia = ontologia
        self._heuristicas = heuristicas
        self._configuraciones = configuraciones

    def _build_agent(
        self, input_data: dict[str, Any], codigo: str
    ) -> EmotionsAgent:
        """Construye EmotionsAgent con ontología y heurísticas."""
        meta = self._d_repo.get_payload(codigo, "metadata") or {}
        enun = self._d_repo.get_payload(codigo, "enunciation") or {}
        return EmotionsAgent(
            self._backend,
            ontologia=self._ontologia,
            heuristicas=self._heuristicas,
            configuraciones=self._configuraciones,
            titulo=str(input_data.get("titulo", "")),
            tipo_discurso=str(meta.get("tipo_discurso", "")),
            enunciador=str(enun.get("enunciador", "")),
            retry_config=self._retry_config,
            genre=self._genre,
        )

    def _build_input_df(
        self,
        codigo: str,
        unit_idxs: list[int],
    ) -> pd.DataFrame:
        """Construye DataFrame con frases y actores serializados."""
        rows: list[dict[str, Any]] = []
        for idx in unit_idxs:
            frase = self._f_repo.get_frase(codigo, idx)
            if frase is None:
                continue
            actores = self._f_repo.get_payload(codigo, idx, "actores")
            actores_str = (
                json.dumps(actores, ensure_ascii=False)
                if actores is not None
                else None
            )
            rows.append({
                "codigo": codigo,
                "unit_idx": idx,
                "frase": frase,
                "actores": actores_str,
            })
        return pd.DataFrame(rows)

    def _extract_payload(self, row: pd.Series) -> Any:
        """Payload con emociones deserializadas desde JSON."""
        emociones_str = row.get("emociones")
        if pd.isna(emociones_str):
            return None
        try:
            return json.loads(emociones_str)
        except (json.JSONDecodeError, TypeError):
            return None


# ══════════════════════════════════════════════════════════════════════════════
#  Etapa de explode
# ══════════════════════════════════════════════════════════════════════════════

class ExplodeEmocionesStage(Stage):
    """Explota emociones detectadas a la tabla `emociones`."""

    NAME = "explode_emociones"

    def __init__(
        self,
        discursos_repo: DiscursosRepository,
        frases_repo: FrasesRepository,
        emociones_repo: EmocionesRepository,
    ) -> None:
        super().__init__()
        self._d_repo = discursos_repo
        self._f_repo = frases_repo
        self._e_repo = emociones_repo

    def run_pending(self) -> int:
        """Procesa discursos y explota emociones pendientes."""
        codigos = self._d_repo.list_codigos()
        total = 0
        for codigo in codigos:
            count = self._explode_for_codigo(codigo)
            total += count
        for _ in range(total):
            self.metrics.record_item_ok()
        if total > 0:
            logger.info(f"[Stage:{self.NAME}] Explotadas {total} emociones.")
        return total

    def _explode_for_codigo(self, codigo: str) -> int:
        """Explota emociones de un discurso a filas individuales."""
        frases = self._f_repo.list_frases_of_discurso(codigo)
        rows: list[dict[str, Any]] = []
        for frase_idx, _frase_text in frases:
            emos_payload = self._f_repo.get_payload(
                codigo, frase_idx, "emociones"
            )
            if not isinstance(emos_payload, list):
                continue
            for emo_idx, emo in enumerate(emos_payload):
                if not isinstance(emo, dict):
                    continue
                rows.append({
                    "codigo": codigo,
                    "frase_idx": frase_idx,
                    "emocion_idx": emo_idx,
                    "experienciador": emo.get("experienciador", ""),
                    "tipo_emocion": emo.get("tipo_emocion", ""),
                    "modo_existencia": emo.get("modo_existencia", ""),
                    "tipo_configuracion": emo.get("tipo_configuracion"),
                    "deteccion_justificacion": emo.get("justificacion"),
                })
        if rows:
            df_rows = pd.DataFrame(rows)
            self._validate(EmocionExplodedContract, df_rows, "salida")
            self._e_repo.upsert_emociones(rows)
        return len(rows)


# ══════════════════════════════════════════════════════════════════════════════
#  Etapa normalización de emociones (sin LLM)
# ══════════════════════════════════════════════════════════════════════════════

class NormalizeEmotionsStage(Stage):
    """Mapea tipo_emocion (texto libre del LLM) a canónico vía ontología.

    Opera sobre filas de la tabla ``emociones`` con ``tipo_emocion`` no nulo
    y ``tipo_emocion_canonico`` nulo. Escribe el canónico en la columna nueva;
    si la emoción no está cubierta por la ontología, deja NULL (sin error).

    Stage determinística, sin LLM, idempotente: re-ejecutar solo procesa
    las filas aún pendientes.
    """

    NAME = "normalize_emotions"

    def __init__(
        self,
        emociones_repo: EmocionesRepository,
        emotion_ontology: dict[str, Any],
        agent_version: str | None = None,
    ) -> None:
        super().__init__()
        self.validate_contracts = False  # no hay DataFrame en esta stage
        self._repo = emociones_repo
        self._lookup = build_emotion_alias_lookup(emotion_ontology)
        self._version = agent_version

    def run_pending(self) -> int:
        """Normaliza emociones pendientes y devuelve el total procesado."""
        pending = self._repo.list_pending_normalization()
        if not pending:
            logger.info(f"[Stage:{self.NAME}] Nada pendiente.")
            return 0

        logger.info(f"[Stage:{self.NAME}] Normalizando {len(pending)} emociones.")
        for codigo, frase_idx, emocion_idx in pending:
            row = self._repo.get_emocion(codigo, frase_idx, emocion_idx)
            if row is None:
                continue
            tipo_raw = row.get("tipo_emocion") or ""
            canonico = self._lookup.get(tipo_raw.lower().strip())
            self._repo.set_normalized_emotion(
                codigo, frase_idx, emocion_idx,
                tipo_emocion_canonico=canonico,  # None si no matchea → queda NULL
                version=self._version,
            )
            self.metrics.record_item_ok()

        logger.info(f"[Stage:{self.NAME}] Completado: {len(pending)} procesadas.")
        return len(pending)


# ══════════════════════════════════════════════════════════════════════════════
#  Etapa caracterización
# ══════════════════════════════════════════════════════════════════════════════

class CharacterizerStage(Stage):
    """Caracteriza emociones individuales."""

    NAME = "characterizer"

    def __init__(
        self,
        backend: LLMBackend,
        discursos_repo: DiscursosRepository,
        frases_repo: FrasesRepository,
        emociones_repo: EmocionesRepository,
        heuristicas: str | None = None,
        agent_version: str | None = None,
        retry_config: RetryConfig | None = None,
        genre: Genre | None = None,
    ) -> None:
        super().__init__()
        self._backend = backend
        self._d_repo = discursos_repo
        self._f_repo = frases_repo
        self._e_repo = emociones_repo
        self._heuristicas = heuristicas
        self._version = agent_version
        self._retry_config = retry_config
        self._genre = genre

    def run_pending(self) -> int:
        """Procesa emociones pendientes y guarda caracterización."""
        pending = self._e_repo.list_pending_caracterizacion()
        if not pending:
            logger.info(f"[Stage:{self.NAME}] Nada pendiente.")
            return 0

        by_codigo: dict[str, list[tuple[int, int]]] = {}
        for codigo, frase_idx, emo_idx in pending:
            by_codigo.setdefault(codigo, []).append((frase_idx, emo_idx))

        total_ok = 0
        for codigo, items in by_codigo.items():
            input_data = self._d_repo.get_input(codigo) or {}
            meta = self._d_repo.get_payload(codigo, "metadata") or {}
            agent = CharacterizerAgent(
                self._backend,
                titulo=str(input_data.get("titulo", "")),
                tipo_discurso=str(meta.get("tipo_discurso", "")),
                heuristicas=self._heuristicas,
                retry_config=self._retry_config,
                genre=self._genre,
            )

            df_in = self._build_input_df(codigo, items)
            if df_in.empty:
                continue
            self._validate(EmocionExplodedContract, df_in, "entrada")

            try:
                df_out = agent.run(df_in)
            except Exception as e:
                logger.error(
                    f"[Stage:{self.NAME}] {codigo}: error inesperado: {e}"
                )
                for frase_idx, emo_idx in items:
                    self._e_repo.set_caracterizacion_error(
                        codigo, frase_idx, emo_idx, str(e)
                    )
                    self.metrics.record_item_failed()
                continue

            for _, row in df_out.iterrows():
                payload = self._extract_payload(row)
                frase_idx = int(row["frase_idx"])
                emo_idx = int(row["emocion_idx"])
                if payload is None:
                    self._e_repo.set_caracterizacion_error(
                        codigo, frase_idx, emo_idx,
                        "Backend error (ver logs)",
                    )
                    self.metrics.record_item_failed()
                    continue
                self._e_repo.set_caracterizacion(
                    codigo, frase_idx, emo_idx,
                    payload=payload,
                    version=self._version,
                )
                total_ok += 1
                self.metrics.record_item_ok()

        logger.info(f"[Stage:{self.NAME}] Completado: {total_ok} ok.")
        return total_ok

    def _build_input_df(
        self,
        codigo: str,
        items: list[tuple[int, int]],
    ) -> pd.DataFrame:
        """Construye DataFrame con emociones y frase de origen."""
        all_emociones = self._e_repo.list_emociones_of_discurso(codigo)
        index = {(e["frase_idx"], e["emocion_idx"]): e for e in all_emociones}

        rows: list[dict[str, Any]] = []
        for frase_idx, emo_idx in items:
            emo = index.get((frase_idx, emo_idx))
            if emo is None:
                continue
            frase_text = self._f_repo.get_frase(codigo, frase_idx) or ""
            rows.append({**emo, "frase": frase_text})
        return pd.DataFrame(rows)

    @staticmethod
    def _extract_payload(row: pd.Series) -> dict[str, Any] | None:
        """Extrae payload de caracterización desde una row."""
        if pd.isna(row.get("foria")):
            return None
        return {
            "foria": row.get("foria"),
            "foria_justificacion": row.get("foria_justificacion"),
            "dominancia": row.get("dominancia"),
            "dominancia_justificacion": row.get("dominancia_justificacion"),
            "intensidad": row.get("intensidad"),
            "intensidad_justificacion": row.get("intensidad_justificacion"),
            "fuente": row.get("fuente"),
            "tipo_fuente": row.get("tipo_fuente"),
            "fuente_justificacion": row.get("fuente_justificacion"),
            "duracion": row.get("duracion"),
            "duracion_justificacion": row.get("duracion_justificacion"),
            "modo_semiotizacion": row.get("modo_semiotizacion"),
            "modo_semiotizacion_justificacion": row.get("modo_semiotizacion_justificacion"),
            "modo_identificacion": row.get("modo_identificacion"),
            "modo_identificacion_justificacion": row.get("modo_identificacion_justificacion"),
            "tipo_atribucion": row.get("tipo_atribucion"),
            "tipo_atribucion_justificacion": row.get("tipo_atribucion_justificacion"),
        }


# ══════════════════════════════════════════════════════════════════════════════
#  EmotionsPass2Stage
# ══════════════════════════════════════════════════════════════════════════════

class EmotionsPass2Stage(Stage):
    """Pase 2 del análisis de emociones."""

    NAME = "emotions_pass2"
    STAGE_KEY = "emociones_pass2"

    def __init__(
        self,
        backend: LLMBackend,
        discursos_repo: DiscursosRepository,
        frases_repo: FrasesRepository,
        ontologia: str,
        heuristicas: str,
        configuraciones: str = "",
        rolling_window: int = 5,
        context_mode: Literal["rolling", "full"] = "rolling",
        agent_version: str | None = None,
        retry_config: RetryConfig | None = None,
        genre: Genre | None = None,
    ) -> None:
        super().__init__()
        self._backend = backend
        self._d_repo = discursos_repo
        self._f_repo = frases_repo
        self._ontologia = ontologia
        self._heuristicas = heuristicas
        self._configuraciones = configuraciones
        self._rolling_window = rolling_window
        self._context_mode = context_mode
        self._version = agent_version
        self._retry_config = retry_config
        self._genre = genre

    def run_pending(self) -> int:
        """Procesa frases pendientes con rolling/full summary."""
        all_pending = self._f_repo.list_pending(self.STAGE_KEY)  # type: ignore[arg-type]
        if not all_pending:
            logger.info(f"[Stage:{self.NAME}] Nada pendiente.")
            return 0

        by_codigo: dict[str, list[int]] = {}
        for codigo, unit_idx in all_pending:
            by_codigo.setdefault(codigo, []).append(unit_idx)

        logger.info(
            f"[Stage:{self.NAME}] Procesando {len(by_codigo)} discurso(s) "
            f"con {sum(len(v) for v in by_codigo.values())} frases pendientes."
        )

        total_ok = 0
        for codigo, pending_idxs in by_codigo.items():
            input_data = self._d_repo.get_input(codigo) or {}

            df_full = self._build_full_df_with_rolling(codigo)
            if df_full.empty:
                logger.info(
                    f"[Stage:{self.NAME}] {codigo}: sin pase 1 procesado, salteando"
                )
                continue

            df_pending = df_full[df_full["unit_idx"].isin(pending_idxs)].reset_index(drop=True)
            if df_pending.empty:
                continue
            self._validate(FraseConEmocionesContract, df_pending, "entrada")

            meta = self._d_repo.get_payload(codigo, "metadata") or {}
            enun = self._d_repo.get_payload(codigo, "enunciation") or {}
            agent = EmotionsAgentPass2(
                self._backend,
                ontologia=self._ontologia,
                heuristicas=self._heuristicas,
                configuraciones=self._configuraciones,
                titulo=str(input_data.get("titulo", "")),
                tipo_discurso=str(meta.get("tipo_discurso", "")),
                enunciador=str(enun.get("enunciador", "")),
                context_mode=self._context_mode,
                retry_config=self._retry_config,
                genre=self._genre,
            )

            try:
                df_out = agent.run(df_pending)
            except Exception as e:
                logger.error(
                    f"[Stage:{self.NAME}] {codigo}: error inesperado: {e}"
                )
                for idx in pending_idxs:
                    self._f_repo.set_error(
                        codigo, idx, self.STAGE_KEY, str(e)  # type: ignore[arg-type]
                    )
                    self.metrics.record_item_failed()
                continue

            for _, row in df_out.iterrows():
                idx = int(row["unit_idx"])
                emociones_str = row.get("emociones")
                if pd.isna(emociones_str):
                    self._f_repo.set_error(
                        codigo, idx, self.STAGE_KEY,  # type: ignore[arg-type]
                        "Backend error (ver logs del agente)",
                    )
                    self.metrics.record_item_failed()
                    continue
                try:
                    payload = json.loads(emociones_str)
                except (json.JSONDecodeError, TypeError):
                    self._f_repo.set_error(
                        codigo, idx, self.STAGE_KEY,  # type: ignore[arg-type]
                        "Output del agente no parseable como JSON",
                    )
                    self.metrics.record_item_failed()
                    continue
                self._f_repo.set_payload(
                    codigo, idx, self.STAGE_KEY,  # type: ignore[arg-type]
                    payload,
                    version=self._version,
                )
                total_ok += 1
                self.metrics.record_item_ok()

        logger.info(f"[Stage:{self.NAME}] Completado: {total_ok} frases ok.")
        return total_ok

    def _build_full_df_with_rolling(self, codigo: str) -> pd.DataFrame:
        """Construye DataFrame con frases y rolling summary."""
        all_frases = self._f_repo.list_frases_of_discurso(codigo)
        if not all_frases:
            return pd.DataFrame()

        rows: list[dict[str, Any]] = []
        any_pass1 = False
        for unit_idx, frase in all_frases:
            emos_pass1 = self._f_repo.get_payload(codigo, unit_idx, "emociones")
            actores = self._f_repo.get_payload(codigo, unit_idx, "actores")
            if emos_pass1 is not None:
                any_pass1 = True

            rows.append({
                "codigo": codigo,
                "unit_idx": unit_idx,
                "frase": frase,
                # `emociones` tiene que ser JSON string para que su parser
                # interno funcione.
                "emociones": (
                    json.dumps(emos_pass1, ensure_ascii=False)
                    if emos_pass1 is not None else None
                ),
                "actores": (
                    json.dumps(actores, ensure_ascii=False)
                    if actores is not None else None
                ),
            })

        if not any_pass1:
            return pd.DataFrame()

        df = pd.DataFrame(rows)
        if self._context_mode == "full":
            return compute_emotion_full_summary(df)
        return compute_emotion_rolling_summary(df, window=self._rolling_window)


# ══════════════════════════════════════════════════════════════════════════════
#  Etapa de análisis actancial
# ══════════════════════════════════════════════════════════════════════════════

class ActantsStage(Stage):
    """Analiza la configuración actancial de las emociones detectadas.

    Para cada emoción individual produce un payload con los cuatro
    componentes del dispositivo analítico: mediador, verificador
    normativo, verificador observacional y operador de modificación.

    Los componentes habilitados se controlan vía `enabled_components`;
    los excluidos se rellenan con un placeholder determinístico antes
    de la persistencia, manteniendo invariante la forma del JSON
    guardado en `emociones.actantes_payload`.

    La stage es opt-in: no forma parte del pipeline default y puede
    correrse a posteriori sobre runs existentes sin invalidar
    resultados previos.
    """

    NAME = "actants"

    def __init__(
        self,
        backend: LLMBackend,
        discursos_repo: DiscursosRepository,
        frases_repo: FrasesRepository,
        emociones_repo: EmocionesRepository,
        heuristicas: str | None = None,
        enabled_components: tuple[str, ...] = ACTANTS_COMPONENTS,
        agent_version: str | None = None,
        retry_config: RetryConfig | None = None,
        genre: Genre | None = None,
    ) -> None:
        super().__init__()
        self._backend = backend
        self._d_repo = discursos_repo
        self._f_repo = frases_repo
        self._e_repo = emociones_repo
        self._heuristicas = heuristicas
        self._enabled_components = enabled_components
        self._version = agent_version
        self._retry_config = retry_config
        self._genre = genre

    def run_pending(self) -> int:
        """Procesa emociones pendientes y guarda análisis actancial."""
        pending = self._e_repo.list_pending_actantes()
        if not pending:
            logger.info(f"[Stage:{self.NAME}] Nada pendiente.")
            return 0

        by_codigo: dict[str, list[tuple[int, int]]] = {}
        for codigo, frase_idx, emo_idx in pending:
            by_codigo.setdefault(codigo, []).append((frase_idx, emo_idx))

        logger.info(
            f"[Stage:{self.NAME}] Procesando {len(by_codigo)} discurso(s) "
            f"con {sum(len(v) for v in by_codigo.values())} emociones pendientes."
        )

        total_ok = 0
        for codigo, items in by_codigo.items():
            input_data = self._d_repo.get_input(codigo) or {}
            meta = self._d_repo.get_payload(codigo, "metadata") or {}
            agent = ActantsAgent(
                self._backend,
                titulo=str(input_data.get("titulo", "")),
                tipo_discurso=str(meta.get("tipo_discurso", "")),
                heuristicas=self._heuristicas,
                enabled_components=self._enabled_components,
                retry_config=self._retry_config,
                genre=self._genre,
            )

            df_in = self._build_input_df(codigo, items)
            if df_in.empty:
                continue
            self._validate(EmocionExplodedContract, df_in, "entrada")

            try:
                df_out = agent.run(df_in)
            except Exception as e:
                logger.error(
                    f"[Stage:{self.NAME}] {codigo}: error inesperado: {e}"
                )
                for frase_idx, emo_idx in items:
                    self._e_repo.set_actantes_error(
                        codigo, frase_idx, emo_idx, str(e)
                    )
                    self.metrics.record_item_failed()
                continue

            for _, row in df_out.iterrows():
                payload = self._extract_payload(row)
                frase_idx = int(row["frase_idx"])
                emo_idx = int(row["emocion_idx"])
                if payload is None:
                    self._e_repo.set_actantes_error(
                        codigo, frase_idx, emo_idx,
                        "Backend error (ver logs)",
                    )
                    self.metrics.record_item_failed()
                    continue
                self._e_repo.set_actantes(
                    codigo, frase_idx, emo_idx,
                    payload=payload,
                    version=self._version,
                )
                total_ok += 1
                self.metrics.record_item_ok()

        logger.info(f"[Stage:{self.NAME}] Completado: {total_ok} ok.")
        return total_ok

    def _build_input_df(
        self,
        codigo: str,
        items: list[tuple[int, int]],
    ) -> pd.DataFrame:
        """Construye DataFrame con emociones y frase de origen."""
        all_emociones = self._e_repo.list_emociones_of_discurso(codigo)
        index = {(e["frase_idx"], e["emocion_idx"]): e for e in all_emociones}

        rows: list[dict[str, Any]] = []
        for frase_idx, emo_idx in items:
            emo = index.get((frase_idx, emo_idx))
            if emo is None:
                continue
            frase_text = self._f_repo.get_frase(codigo, frase_idx) or ""
            rows.append({**emo, "frase": frase_text})
        return pd.DataFrame(rows)

    @staticmethod
    def _extract_payload(row: pd.Series) -> dict[str, Any] | None:
        """Extrae payload actancial estructurado desde una row."""
        if pd.isna(row.get("mediador_presente")):
            return None
        return {
            "mediador": {
                "presente": bool(row.get("mediador_presente")),
                "descripcion": _none_if_nan(row.get("mediador_descripcion")),
                "tipo": row.get("mediador_tipo"),
                "justificacion": row.get("mediador_justificacion"),
            },
            "verificador_normativo": {
                "presente": bool(row.get("verificador_normativo_presente")),
                "descripcion": _none_if_nan(row.get("verificador_normativo_descripcion")),
                "tipo": row.get("verificador_normativo_tipo"),
                "evaluacion": row.get("verificador_normativo_evaluacion"),
                "justificacion": row.get("verificador_normativo_justificacion"),
            },
            "verificador_observacional": {
                "presente": bool(row.get("verificador_observacional_presente")),
                "descripcion": _none_if_nan(row.get("verificador_observacional_descripcion")),
                "tipo": row.get("verificador_observacional_tipo"),
                "evaluacion": row.get("verificador_observacional_evaluacion"),
                "justificacion": row.get("verificador_observacional_justificacion"),
            },
            "operador_modificacion": {
                "presente": bool(row.get("operador_modificacion_presente")),
                "descripcion": _none_if_nan(row.get("operador_modificacion_descripcion")),
                "funcion": row.get("operador_modificacion_funcion"),
                "justificacion": row.get("operador_modificacion_justificacion"),
            },
        }


def _none_if_nan(value: Any) -> Any:
    """Convierte NaN (pandas) o None en None; preserva strings y resto."""
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    return value


# ══════════════════════════════════════════════════════════════════════════════
#  Judge
# ══════════════════════════════════════════════════════════════════════════════

class JudgeStage(Stage):
    """Juzga la coherencia de las caracterizaciones de emociones."""
 
    NAME = "judge"
 
    def __init__(
        self,
        backend: LLMBackend,
        discursos_repo: DiscursosRepository,
        frases_repo: FrasesRepository,
        emociones_repo: EmocionesRepository,
        judgments_repo: JudgmentsRepository,
        heuristicas: str | None = None,
        agent_version: str | None = None,
        retry_config: RetryConfig | None = None,
        genre: Genre | None = None,
    ) -> None:
        super().__init__()
        self._backend = backend
        self._d_repo = discursos_repo
        self._f_repo = frases_repo
        self._e_repo = emociones_repo
        self._j_repo = judgments_repo
        self._heuristicas = heuristicas
        self._version = agent_version
        self._retry_config = retry_config
        self._genre = genre
 
    def run_pending(self) -> int:
        """Procesa emociones caracterizadas y guarda veredictos."""
        pending = self._j_repo.list_pending()
        if not pending:
            logger.info(f"[Stage:{self.NAME}] Nada pendiente.")
            return 0
 
        by_codigo: dict[str, list[tuple[int, int]]] = {}
        for codigo, frase_idx, emo_idx in pending:
            by_codigo.setdefault(codigo, []).append((frase_idx, emo_idx))
 
        logger.info(
            f"[Stage:{self.NAME}] Procesando {len(by_codigo)} discurso(s) "
            f"con {sum(len(v) for v in by_codigo.values())} emociones pendientes."
        )
 
        total_ok = 0
        for codigo, items in by_codigo.items():
            input_data = self._d_repo.get_input(codigo) or {}
            meta = self._d_repo.get_payload(codigo, "metadata") or {}
            agent = JudgeAgent(
                self._backend,
                titulo=str(input_data.get("titulo", "")),
                tipo_discurso=str(meta.get("tipo_discurso", "")),
                heuristicas=self._heuristicas,
                retry_config=self._retry_config,
                genre=self._genre,
            )
 
            df_in = self._build_input_df(codigo, items)
            if df_in.empty:
                continue
 
            try:
                df_out = agent.run(df_in)
            except Exception as e:
                logger.error(
                    f"[Stage:{self.NAME}] {codigo}: error inesperado: {e}"
                )
                for frase_idx, emo_idx in items:
                    self._j_repo.set_error(codigo, frase_idx, emo_idx, str(e))
                    self.metrics.record_item_failed()
                continue
 
            for _, row in df_out.iterrows():
                frase_idx = int(row["frase_idx"])
                emo_idx = int(row["emocion_idx"])
                # Columnas del agente: coherente, issues, confianza.
                if pd.isna(row.get("coherente")):
                    self._j_repo.set_error(
                        codigo, frase_idx, emo_idx,
                        "Backend error (ver logs del agente)",
                    )
                    self.metrics.record_item_failed()
                    continue
                self._j_repo.set_judgment(
                    codigo, frase_idx, emo_idx,
                    coherente=bool(row["coherente"]),
                    issues=str(row["issues"]),
                    confianza=str(row["confianza"]),
                    version=self._version,
                )
                total_ok += 1
                self.metrics.record_item_ok()
 
        logger.info(f"[Stage:{self.NAME}] Completado: {total_ok} ok.")
        return total_ok
 
    def _build_input_df(
        self,
        codigo: str,
        items: list[tuple[int, int]],
    ) -> pd.DataFrame:
        """Construye DataFrame con emociones y caracterización para juicio."""
        all_emociones = self._e_repo.list_emociones_of_discurso(codigo)
        index = {(e["frase_idx"], e["emocion_idx"]): e for e in all_emociones}
 
        rows: list[dict[str, Any]] = []
        for frase_idx, emo_idx in items:
            emo = index.get((frase_idx, emo_idx))
            if emo is None:
                continue
            carac_raw = emo.get("caracterizacion_payload")
            if carac_raw is None:
                continue
            try:
                carac = json.loads(carac_raw)
            except (json.JSONDecodeError, TypeError):
                continue
 
            frase_text = self._f_repo.get_frase(codigo, frase_idx) or ""
            rows.append({
                **emo,
                "frase": frase_text,
                # Campos de caracterización desempaquetados desde el JSON embebido.
                "foria": carac.get("foria", ""),
                "dominancia": carac.get("dominancia", ""),
                "intensidad": carac.get("intensidad", ""),
                "fuente": carac.get("fuente", ""),
                "tipo_fuente": carac.get("tipo_fuente", ""),
                "duracion": carac.get("duracion", ""),
                "modo_semiotizacion": carac.get("modo_semiotizacion", ""),
                "modo_identificacion": carac.get("modo_identificacion", ""),
                "tipo_atribucion": carac.get("tipo_atribucion", ""),
            })
        df = pd.DataFrame(rows)
        self._validate(EmocionExplodedContract, df, "entrada")
        return df
