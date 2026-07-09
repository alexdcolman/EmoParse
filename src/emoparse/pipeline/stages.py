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
from emoparse.agents.deixis import DeixisAgent
from emoparse.agents.modalidad import ModalidadAgent
from emoparse.core.text import canonical_slug
from emoparse.pipeline.deixis import is_deictic, resolve_deictic_to_enunciador
from emoparse.pipeline.modalidad_nlp import ModalidadNLP
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
from emoparse.agents.semas import SemasAgent
from emoparse.core.backend.base import LLMBackend
from emoparse.core.backend.retry import RetryConfig
from emoparse.genres.base import Genre
from emoparse.knowledge.normalization import build_emotion_alias_lookup
from emoparse.storage.discursos import DiscursosRepository
from emoparse.storage.emociones import EmocionesRepository
from emoparse.storage.frases import FrasesRepository
from emoparse.storage.judgments import JudgmentsRepository
from emoparse.storage.menciones import MencionesRepository
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
        """Payload con enunciador, enunciatarios, auditorio y colectivos."""
        if pd.isna(row.get("enunciador")):
            return None
        # `enunciatarios`, `auditorio` y `colectivos_identificacion` ya son
        # strings JSON desde el agente.
        return {
            "enunciador": row.get("enunciador"),
            "enunciador_justificacion": row.get("enunciador_justificacion"),
            "enunciatarios": row.get("enunciatarios"),
            "auditorio": row.get("auditorio"),
            "colectivos_identificacion": row.get("colectivos_identificacion"),
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
#  EmotionsStage
# ══════════════════════════════════════════════════════════════════════════════

def _format_enunciatarios(raw: Any) -> str:
    """Extrae los nombres de los enunciatarios desde el payload de enunciation.

    El payload guarda `enunciatarios` como string JSON (lista de objetos con
    clave `actor`). Devuelve un listado compacto `a; b; c`, o cadena vacía si
    no hay datos.
    """
    if raw is None or (isinstance(raw, float) and pd.isna(raw)):
        return ""
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return ""
    else:
        parsed = raw
    if not isinstance(parsed, list):
        return ""
    nombres = [
        str(e.get("actor", "")).strip()
        for e in parsed
        if isinstance(e, dict) and str(e.get("actor", "")).strip()
    ]
    return "; ".join(nombres)


def _resumen_global(summ: dict | None, limit: int = 1500) -> str:
    """Resumen global del discurso (payload `summarizer`), truncado.

    Se inyecta como contexto de fondo en los prompts de emociones (pase 1 y 2).
    Vacío si no hay resumen: el template lo omite (`{% if resumen %}`).
    """
    r = str((summ or {}).get("resumen_global") or "").strip()
    return r[:limit] + "..." if len(r) > limit else r


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
        emotion_scope: tuple[str, ...] | None = None,
        agent_version: str | None = None,
        retry_config: RetryConfig | None = None,
        genre: Genre | None = None,
    ) -> None:
        super().__init__(backend, discursos_repo, frases_repo, agent_version, retry_config, genre)
        self._ontologia = ontologia
        self._heuristicas = heuristicas
        self._configuraciones = configuraciones
        self._emotion_scope = tuple(emotion_scope) if emotion_scope else None

    def _build_agent(
        self, input_data: dict[str, Any], codigo: str
    ) -> EmotionsAgent:
        """Construye EmotionsAgent con ontología y heurísticas."""
        meta = self._d_repo.get_payload(codigo, "metadata") or {}
        enun = self._d_repo.get_payload(codigo, "enunciation") or {}
        summ = self._d_repo.get_payload(codigo, "summarizer") or {}
        return EmotionsAgent(
            self._backend,
            ontologia=self._ontologia,
            heuristicas=self._heuristicas,
            configuraciones=self._configuraciones,
            titulo=str(input_data.get("titulo", "")),
            tipo_discurso=str(meta.get("tipo_discurso", "")),
            enunciador=str(enun.get("enunciador", "")),
            enunciatarios=_format_enunciatarios(enun.get("enunciatarios")),
            auditorio=_format_enunciatarios(enun.get("auditorio")),
            resumen=_resumen_global(summ),
            emotion_scope=self._emotion_scope,
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
#  Etapa de explosión de emociones detectadas en la tabla `emociones`
# ══════════════════════════════════════════════════════════════════════════════

class ExplodeEmotionsStage(Stage):
    """Explota emociones detectadas a la tabla `emociones`."""

    NAME = "explode_emotions"

    def __init__(
        self,
        discursos_repo: DiscursosRepository,
        frases_repo: FrasesRepository,
        emociones_repo: EmocionesRepository,
        menciones_repo: MencionesRepository | None = None,
        referentes_kb: dict[str, Any] | None = None,
    ) -> None:
        super().__init__()
        self._d_repo = discursos_repo
        self._f_repo = frases_repo
        self._e_repo = emociones_repo
        self._m_repo = menciones_repo
        self._referentes_kb = referentes_kb

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
        """Explota emociones de un discurso a filas individuales.

        Además, si hay repositorio de menciones, reconstruye la base de marcas
        discursivas del discurso (actor / experienciador / fuente) a partir de
        los mismos payloads ya leídos. Es el punto natural de materialización
        per-código; la derivación vive en `storage.menciones`.
        """
        frases = self._f_repo.list_frases_of_discurso(codigo)
        rows: list[dict[str, Any]] = []
        emociones_by_unit: dict[int, Any] = {}
        actores_by_unit: dict[int, Any] = {}
        for frase_idx, _frase_text in frases:
            if self._m_repo is not None:
                actores_by_unit[frase_idx] = self._f_repo.get_payload(
                    codigo, frase_idx, "actores"
                )
            emos_payload = self._select_emociones_payload(codigo, frase_idx)
            if not isinstance(emos_payload, list):
                continue
            emociones_by_unit[frase_idx] = emos_payload
            for emo_idx, emo in enumerate(emos_payload):
                if not isinstance(emo, dict):
                    continue
                rows.append({
                    "codigo": codigo,
                    "frase_idx": frase_idx,
                    "emocion_idx": emo_idx,
                    "experienciador": emo.get("experienciador", ""),
                    "experienciador_marca": emo.get("experienciador_marca", ""),
                    "tipo_emocion": emo.get("tipo_emocion", ""),
                    "modo_existencia": emo.get("modo_existencia", ""),
                    "fuente_marca": emo.get("fuente_marca", ""),
                    "fuente_inferencia": emo.get("fuente_inferencia", ""),
                    "tipo_configuracion": emo.get("tipo_configuracion"),
                })
        if rows:
            df_rows = pd.DataFrame(rows)
            self._validate(EmocionExplodedContract, df_rows, "salida")
            self._e_repo.upsert_emociones(rows)
        if self._m_repo is not None:
            self._m_repo.rebuild_for_codigo(
                codigo, actores_by_unit, emociones_by_unit
            )
            self._m_repo.propose_coref_equivalences(codigo)
            enun = self._d_repo.get_payload(codigo, "enunciation") or {}
            self._m_repo.add_deixis_suggestions(
                codigo, str(enun.get("enunciador", ""))
            )
            self._m_repo.propose_kb_equivalences(codigo, self._referentes_kb)
        return len(rows)

    def _select_emociones_payload(self, codigo: str, frase_idx: int) -> Any:
        """Devuelve la lectura de emociones a explotar para una frase.

        Prefiere el pase 2 cuando esa frase fue procesada por
        ``emotions_pass2`` (su payload existe, aunque sea una lista vacía:
        esa lista vacía es su veredicto refinado de que no hay emoción). Si
        el pase 2 no corrió para la frase —o falló, dejando el payload en
        NULL— cae al pase 1. Así el explode consume siempre la mejor lectura
        disponible sin obligar a correr el pase 2 ni depender del orden de
        las stages.
        """
        pass2 = self._f_repo.get_payload(codigo, frase_idx, "emociones_pass2")
        if isinstance(pass2, list):
            return pass2
        return self._f_repo.get_payload(codigo, frase_idx, "emociones")


# ══════════════════════════════════════════════════════════════════════════════
#  Etapa de resolución de deixis (LLM)
# ══════════════════════════════════════════════════════════════════════════════

def _parse_json_list(raw: Any) -> list[Any]:
    """Parsea un valor a lista JSON; devuelve [] ante cualquier problema."""
    if isinstance(raw, list):
        return raw
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return []
        return parsed if isinstance(parsed, list) else []
    return []


def _extract_enunciation_referentes(
    payload: dict[str, Any],
) -> tuple[str, tuple[str, ...], tuple[str, ...]]:
    """Extrae (enunciador, auditorio, colectivos) del payload de enunciation."""
    enunciador = str(payload.get("enunciador") or "").strip()
    auditorio = tuple(
        str(a.get("actor", "")).strip()
        for a in _parse_json_list(payload.get("auditorio"))
        if isinstance(a, dict) and str(a.get("actor", "")).strip()
    )
    colectivos = tuple(
        str(c.get("nombre", "")).strip()
        for c in _parse_json_list(payload.get("colectivos_identificacion"))
        if isinstance(c, dict) and str(c.get("nombre", "")).strip()
    )
    return enunciador, auditorio, colectivos


class DeixisStage(Stage):
    """Resuelve marcas deícticas a referentes concretos del discurso (vía LLM).

    Corre después de `explode_emotions` (necesita la base de marcas). Para
    cada discurso con marcas deícticas no resueltas: toma el enunciador, el
    auditorio y los colectivos del payload de enunciation, le pide al LLM la
    asignación (posiblemente múltiple) y la persiste como propuestas
    destildables en `mencion_canonico` (origin='deixis_llm', con su
    `deixis_tipo`). El canónico es siempre el referente CONCRETO, nunca el tipo.
    """

    NAME = "deixis"

    #: Cantidad de marcas deícticas por llamada al LLM (configurable vía
    #: genre.batch_size["deixis"]). Mantiene acotado el contexto y la salida.
    MARCAS_PER_CALL = 5
    #: Tope de caracteres del resumen inyectado como contexto.
    _RESUMEN_CHAR_LIMIT = 1500

    def __init__(
        self,
        backend: LLMBackend,
        discursos_repo: DiscursosRepository,
        menciones_repo: MencionesRepository,
        agent_version: str | None = None,
        retry_config: RetryConfig | None = None,
        genre: Genre | None = None,
        marcas_per_call: int | None = None,
    ) -> None:
        super().__init__()
        self.validate_contracts = False  # no hay contrato de DataFrame acá
        self._backend = backend
        self._d_repo = discursos_repo
        self._m_repo = menciones_repo
        self._version = agent_version
        self._retry_config = retry_config
        self._genre = genre
        n = marcas_per_call
        if n is None and genre is not None:
            n = genre.batch_size.get("deixis")
        self._marcas_per_call = max(1, int(n)) if n else self.MARCAS_PER_CALL

    def run_pending(self) -> int:
        """Resuelve la deixis de los discursos que aún no la tienen."""
        codigos = [
            c for c in self._d_repo.list_codigos()
            if not self._m_repo.has_deixis_llm(c)
        ]
        if not codigos:
            logger.info(f"[Stage:{self.NAME}] Nada pendiente.")
            return 0

        total = 0
        for codigo in codigos:
            total += self._resolve_for_codigo(codigo)
        logger.info(f"[Stage:{self.NAME}] {total} vínculos deícticos propuestos.")
        return total

    def _resumen_for(self, codigo: str) -> str:
        """Resumen del discurso para contexto: summarizer → fallback contenido."""
        summ = self._d_repo.get_payload(codigo, "summarizer") or {}
        resumen = str(summ.get("resumen_global") or "").strip()
        if not resumen:
            inp = self._d_repo.get_input(codigo) or {}
            resumen = str(inp.get("contenido") or "").strip()
        if len(resumen) > self._RESUMEN_CHAR_LIMIT:
            resumen = resumen[: self._RESUMEN_CHAR_LIMIT] + "..."
        return resumen

    def _resolve_for_codigo(self, codigo: str) -> int:
        enun = self._d_repo.get_payload(codigo, "enunciation") or {}
        enunciador, auditorio, colectivos = _extract_enunciation_referentes(enun)
        if not (enunciador or auditorio or colectivos):
            return 0

        # Pre-filtro determinista: solo marcas con deixis de 1ª/2ª persona.
        marca_ids: dict[str, list[int]] = {}
        for m in self._m_repo.list_marcas_for_deixis(codigo):
            marca = str(m["marca"])
            if is_deictic(marca):
                marca_ids.setdefault(marca.strip().lower(), []).append(int(m["id"]))
        if not marca_ids:
            return 0

        marcas_unicas = sorted({m for m in marca_ids})
        # Una fila por chunk de marcas: acota contexto y salida del LLM.
        n = self._marcas_per_call
        df_in = pd.DataFrame([
            {
                "codigo": codigo,
                "marcas": "\n".join(f"- {m}" for m in marcas_unicas[i:i + n]),
            }
            for i in range(0, len(marcas_unicas), n)
        ])

        agent = DeixisAgent(
            self._backend,
            enunciador=enunciador,
            auditorio=auditorio,
            colectivos=colectivos,
            resumen=self._resumen_for(codigo),
            retry_config=self._retry_config,
            genre=self._genre,
        )
        try:
            df_out = agent.run(df_in)
        except Exception as e:
            logger.error(f"[Stage:{self.NAME}] {codigo}: error inesperado: {e}")
            self.metrics.record_item_failed()
            return 0

        resoluciones: list[Any] = []
        for raw in df_out.get("deixis", []):
            if raw is None or (isinstance(raw, float) and pd.isna(raw)):
                continue
            try:
                parsed = json.loads(raw)
            except (json.JSONDecodeError, TypeError):
                continue
            if isinstance(parsed, list):
                resoluciones.extend(parsed)

        linked = 0
        for res in resoluciones:
            if not isinstance(res, dict):
                continue
            marca = str(res.get("marca", "")).strip().lower()
            ids = marca_ids.get(marca)
            if not ids:
                continue
            for ref in res.get("referentes") or []:
                if not isinstance(ref, dict):
                    continue
                tipo = str(ref.get("tipo_referente_deixis", "")).strip()
                nombre = str(ref.get("referente_deixis", "")).strip()
                canonical = canonical_slug(nombre)
                if not canonical or not tipo:
                    continue
                for mid in ids:
                    linked += self._m_repo.link_deixis(mid, canonical, tipo)
        logger.debug(
            f"[Stage:{self.NAME}] {codigo}: {len(marca_ids)} marcas candidatas, "
            f"{len(resoluciones)} resoluciones, {linked} vínculos."
        )
        for _ in range(linked):
            self.metrics.record_item_ok()
        return linked


class ModalidadStage(Stage):
    """Clasifica la MODALIDAD REFERENCIAL de cada vínculo marca→referente.

    Corre después de deixis/coref (necesita los vínculos en `mencion_canonico`).
    Pre-pass NLP (spaCy) para los casos claros (pronombres/verbos → referencia
    gramatical; nombres propios → designación); LLM solo para los ambiguos (SN de
    nombre común, que puede ser designación o identificación inferencial).
    Persiste `modalidad`, `naturaleza` y `modalidad_origin` ('nlp'|'llm') por
    vínculo. Opt-in. Si `use_llm=False` o no hay backend, corre NLP-only y
    persiste el guess tentativo del NLP.
    """

    NAME = "modalidad"
    MARCAS_PER_CALL = 8
    _RESUMEN_CHAR_LIMIT = 1500
    _VALID_MOD = {
        "designacion", "referencia_gramatical", "identificacion_inferencial",
    }
    _VALID_NAT = {"persona", "colectivo", "institucion", "objeto_proceso", "otro"}

    def __init__(
        self,
        discursos_repo: DiscursosRepository,
        menciones_repo: MencionesRepository,
        backend: LLMBackend | None = None,
        use_llm: bool = True,
        nlp_model: str | None = None,
        agent_version: str | None = None,
        retry_config: RetryConfig | None = None,
        genre: Genre | None = None,
        marcas_per_call: int | None = None,
    ) -> None:
        super().__init__()
        self.validate_contracts = False
        self._d_repo = discursos_repo
        self._m_repo = menciones_repo
        self._backend = backend
        self._use_llm = bool(use_llm) and backend is not None
        self._version = agent_version
        self._retry_config = retry_config
        self._genre = genre
        self._nlp = ModalidadNLP(nlp_model)
        n = marcas_per_call
        if n is None and genre is not None:
            n = genre.batch_size.get("modalidad")
        self._marcas_per_call = max(1, int(n)) if n else self.MARCAS_PER_CALL

    def run_pending(self) -> int:
        total = 0
        for codigo in self._d_repo.list_codigos():
            total += self._classify_for_codigo(codigo)
        logger.info(f"[Stage:{self.NAME}] {total} vínculos clasificados.")
        return total

    def _resumen_for(self, codigo: str) -> str:
        summ = self._d_repo.get_payload(codigo, "summarizer") or {}
        resumen = str(summ.get("resumen_global") or "").strip()
        if not resumen:
            inp = self._d_repo.get_input(codigo) or {}
            resumen = str(inp.get("contenido") or "").strip()
        if len(resumen) > self._RESUMEN_CHAR_LIMIT:
            resumen = resumen[: self._RESUMEN_CHAR_LIMIT] + "..."
        return resumen

    def _classify_for_codigo(self, codigo: str) -> int:
        links = self._m_repo.list_links_for_modalidad(codigo)
        if not links:
            return 0

        nlp_guess: dict[tuple[int, str], Any] = {}
        ambiguous: list[dict[str, Any]] = []
        done = 0
        for lk in links:
            g = self._nlp.classify(str(lk["marca"]), str(lk.get("frase") or ""))
            key = (int(lk["mencion_id"]), str(lk["canonical_id"]))
            nlp_guess[key] = g
            if g.confident:
                self._m_repo.set_modalidad(
                    key[0], key[1], g.modalidad, g.naturaleza, "nlp"
                )
                done += 1
                self.metrics.record_item_ok()
            else:
                ambiguous.append(lk)

        if not ambiguous:
            return done

        if not self._use_llm:
            for lk in ambiguous:
                key = (int(lk["mencion_id"]), str(lk["canonical_id"]))
                g = nlp_guess[key]
                self._m_repo.set_modalidad(
                    key[0], key[1], g.modalidad, g.naturaleza, "nlp"
                )
                done += 1
                self.metrics.record_item_ok()
            return done

        return done + self._classify_llm(codigo, ambiguous, nlp_guess)

    def _classify_llm(
        self,
        codigo: str,
        ambiguous: list[dict[str, Any]],
        nlp_guess: dict[tuple[int, str], Any],
    ) -> int:
        # Índice (marca_lower, canonical) → [mencion_id] para el match-back.
        index: dict[tuple[str, str], list[int]] = {}
        for lk in ambiguous:
            k = (str(lk["marca"]).strip().lower(), str(lk["canonical_id"]))
            index.setdefault(k, []).append(int(lk["mencion_id"]))

        # Ítems únicos (marca, referente, frase) para el prompt.
        seen: set[tuple[str, str]] = set()
        items: list[dict[str, Any]] = []
        for lk in ambiguous:
            k = (str(lk["marca"]).strip().lower(), str(lk["canonical_id"]))
            if k in seen:
                continue
            seen.add(k)
            items.append(lk)

        n = self._marcas_per_call
        rows = [
            {
                "codigo": codigo,
                "vinculos": "\n".join(
                    f'- marca: "{c["marca"]}" · referente: {c["canonical_id"]} '
                    f'· frase: "{str(c.get("frase") or "").strip()}"'
                    for c in items[i:i + n]
                ),
            }
            for i in range(0, len(items), n)
        ]
        agent = ModalidadAgent(
            self._backend,
            resumen=self._resumen_for(codigo),
            retry_config=self._retry_config,
            genre=self._genre,
        )
        try:
            df_out = agent.run(pd.DataFrame(rows))
        except Exception as e:
            logger.error(f"[Stage:{self.NAME}] {codigo}: error LLM: {e}")
            df_out = pd.DataFrame()

        clasif: list[Any] = []
        for raw in df_out.get("modalidad", []) if not df_out.empty else []:
            if raw is None or (isinstance(raw, float) and pd.isna(raw)):
                continue
            try:
                parsed = json.loads(raw)
            except (json.JSONDecodeError, TypeError):
                continue
            if isinstance(parsed, list):
                clasif.extend(parsed)

        resolved: set[tuple[int, str]] = set()
        done = 0
        for c in clasif:
            if not isinstance(c, dict):
                continue
            marca = str(c.get("marca", "")).strip().lower()
            ref_raw = str(c.get("referente", "")).strip()
            mod = str(c.get("modalidad", "")).strip()
            nat = str(c.get("naturaleza", "")).strip()
            mod = mod if mod in self._VALID_MOD else None
            nat = nat if nat in self._VALID_NAT else None
            # Match-back: por (marca, canonical). El referente vuelve como el
            # slug que le pasamos; por robustez probamos también su slug.
            for cand in (ref_raw, canonical_slug(ref_raw)):
                mids = index.get((marca, cand))
                if mids:
                    canonical = cand
                    break
            else:
                # Si la marca es única entre los ambiguos, resolvés igual.
                marca_keys = [k for k in index if k[0] == marca]
                if len(marca_keys) == 1:
                    canonical = marca_keys[0][1]
                    mids = index[marca_keys[0]]
                else:
                    continue
            for mid in mids:
                self._m_repo.set_modalidad(mid, canonical, mod, nat, "llm")
                resolved.add((mid, canonical))
                done += 1
                self.metrics.record_item_ok()

        # Ambiguos que el LLM no resolvió → fallback al guess del NLP.
        for lk in ambiguous:
            key = (int(lk["mencion_id"]), str(lk["canonical_id"]))
            if key in resolved:
                continue
            g = nlp_guess[key]
            self._m_repo.set_modalidad(key[0], key[1], g.modalidad, g.naturaleza, "nlp")
            done += 1
        return done


# ══════════════════════════════════════════════════════════════════════════════
#  Etapa normalización de emociones
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
#  Etapa de caracterización
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

        exp_map = self._e_repo.resolve_canonico_map(
            codigo, "experienciador", "experienciador_marca"
        )
        fte_map = self._e_repo.resolve_canonico_map(codigo, "fuente", "fuente_marca")
        rows: list[dict[str, Any]] = []
        for frase_idx, emo_idx in items:
            emo = index.get((frase_idx, emo_idx))
            if emo is None:
                continue
            frase_text = self._f_repo.get_frase(codigo, frase_idx) or ""
            row = {**emo, "frase": frase_text}
            row["experienciador"] = _effective_experiencer(emo, exp_map)
            row["fuente_inferencia"] = _effective_fuente(emo, fte_map)
            rows.append(row)
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
            "duracion": row.get("duracion"),
            "duracion_justificacion": row.get("duracion_justificacion"),
            "tipo_atribucion": row.get("tipo_atribucion"),
            "tipo_atribucion_justificacion": row.get("tipo_atribucion_justificacion"),
            "temporalidad": row.get("temporalidad"),
            "temporalidad_justificacion": row.get("temporalidad_justificacion"),
            "aspecto": row.get("aspecto"),
            "aspecto_justificacion": row.get("aspecto_justificacion"),
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
        rolling_window: int = 3,
        context_mode: Literal["rolling", "full"] = "rolling",
        # "full" da más contexto de continuidad para detectar escaladas, a costa de prompt más largo
        emotion_scope: tuple[str, ...] | None = None,
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
        self._emotion_scope = tuple(emotion_scope) if emotion_scope else None
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
            summ = self._d_repo.get_payload(codigo, "summarizer") or {}
            agent = EmotionsAgentPass2(
                self._backend,
                ontologia=self._ontologia,
                heuristicas=self._heuristicas,
                configuraciones=self._configuraciones,
                titulo=str(input_data.get("titulo", "")),
                tipo_discurso=str(meta.get("tipo_discurso", "")),
                enunciador=str(enun.get("enunciador", "")),
                enunciatarios=_format_enunciatarios(enun.get("enunciatarios")),
                auditorio=_format_enunciatarios(enun.get("auditorio")),
                resumen=_resumen_global(summ),
                emotion_scope=self._emotion_scope,
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

    La stage no forma parte del pipeline default y puede
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

        exp_map = self._e_repo.resolve_canonico_map(
            codigo, "experienciador", "experienciador_marca"
        )
        fte_map = self._e_repo.resolve_canonico_map(codigo, "fuente", "fuente_marca")
        rows: list[dict[str, Any]] = []
        for frase_idx, emo_idx in items:
            emo = index.get((frase_idx, emo_idx))
            if emo is None:
                continue
            frase_text = self._f_repo.get_frase(codigo, frase_idx) or ""
            row = {**emo, "frase": frase_text}
            row["experienciador"] = _effective_experiencer(emo, exp_map)
            row["fuente_inferencia"] = _effective_fuente(emo, fte_map)
            rows.append(row)
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
            "polaridad": {
                "negada": bool(row.get("polaridad_negada")),
                "tipo": row.get("polaridad_tipo"),
                "justificacion": row.get("polaridad_justificacion"),
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


def _effective_experiencer(
    emo: dict[str, Any],
    canon_map: dict[tuple[int, int], list[str]] | None = None,
) -> str:
    """Experienciador efectivo para las stages downstream.

    Orden de preferencia: (1) ``experienciador_canonico`` por emoción (commit de
    la revisión o atribución por emoción); (2) el canónico resuelto desde las
    marcas ↔ referentes (`canon_map`), que refleja las ediciones de la tab
    Referentes; (3) el crudo ``experienciador``. Así la revisión humana propaga a
    characterizer/actants/judge sin que esas stages conozcan la KB ni el overlay.
    """
    canon = emo.get("experienciador_canonico")
    canon = str(canon).strip() if canon is not None else ""
    if canon:
        return canon
    resolved = _from_canon_map(emo, canon_map)
    return resolved or str(emo.get("experienciador", "") or "")


def _effective_fuente(
    emo: dict[str, Any],
    canon_map: dict[tuple[int, int], list[str]] | None = None,
) -> str:
    """Fuente efectiva para las stages downstream.

    Orden de preferencia: (1) ``fuente_canonico`` por emoción; (2) el canónico
    resuelto desde las marcas ↔ referentes (refleja la tab Referentes); (3) el
    crudo ``fuente_inferencia``.
    """
    canon = emo.get("fuente_canonico")
    canon = str(canon).strip() if canon is not None else ""
    if canon:
        return canon
    resolved = _from_canon_map(emo, canon_map)
    return resolved or str(emo.get("fuente_inferencia", "") or "")


def _from_canon_map(
    emo: dict[str, Any],
    canon_map: dict[tuple[int, int], list[str]] | None,
) -> str:
    """Une los canónicos resueltos para la emoción, o '' si no hay."""
    if not canon_map:
        return ""
    try:
        key = (int(emo["frase_idx"]), int(emo["emocion_idx"]))
    except (KeyError, TypeError, ValueError):
        return ""
    return "; ".join(canon_map.get(key, []))


#: Radio de la ventana de frases (previas/posteriores) que recibe el juez.
_JUDGE_WINDOW = 1


def _parse_json_safe(raw: Any) -> dict[str, Any]:
    """json.loads tolerante: devuelve {} ante nulo o error."""
    if not raw:
        return {}
    if isinstance(raw, dict):
        return raw
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return {}
    return data if isinstance(data, dict) else {}


def _resumen_global(summarizer_payload: dict[str, Any]) -> str:
    """Extrae el resumen global del payload de summarizer (tolerante a claves)."""
    if not isinstance(summarizer_payload, dict):
        return ""
    for k in ("resumen_global", "resumen", "global", "summary"):
        v = summarizer_payload.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip()
    return ""


def _format_enunciacion_for_judge(enun: dict[str, Any]) -> str:
    """Bloque de contexto enunciativo para el system del juez.

    Formatea SOLO enunciador y auditorio (los enunciatarios y colectivos se
    omiten para acotar el contexto y las decisiones del juez).
    """
    if not isinstance(enun, dict) or not enun:
        return ""
    lines: list[str] = []
    enunciador = enun.get("enunciador")
    if isinstance(enunciador, dict) and enunciador.get("actor"):
        lines.append(f"  Enunciador: {enunciador['actor']}")

    def _names(items: Any, *keys: str) -> str:
        out: list[str] = []
        if isinstance(items, list):
            for it in items:
                if isinstance(it, dict):
                    for k in keys:
                        if it.get(k):
                            out.append(str(it[k]))
                            break
        return "; ".join(out)

    auditorio = _names(enun.get("auditorio"), "actor")
    if auditorio:
        lines.append(f"  Auditorio: {auditorio}")
    return "\n".join(lines)


def _format_actantes_for_judge(actantes: dict[str, Any]) -> str:
    """Resumen compacto de los actantes presentes, para el prompt del juez."""
    if not isinstance(actantes, dict) or not actantes:
        return ""
    lines: list[str] = []
    for key in (
        "mediador",
        "verificador_normativo",
        "verificador_observacional",
        "operador_modificacion",
    ):
        sub = actantes.get(key)
        if isinstance(sub, dict) and sub.get("presente"):
            attr = sub.get("funcion") or sub.get("tipo") or ""
            evalu = sub.get("evaluacion")
            extra = f", evaluacion={evalu}" if evalu and evalu != "sin_evaluacion" else ""
            lines.append(f"    {key}: {attr}{extra}")
    pol = actantes.get("polaridad")
    if isinstance(pol, dict):
        lines.append(f"    polaridad: {pol.get('tipo', 'afirmada')}")
    return "\n".join(lines)


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
        ontologia: str = "",
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
        self._ontologia = ontologia
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
            summ = self._d_repo.get_payload(codigo, "summarizer") or {}
            enun = self._d_repo.get_payload(codigo, "enunciation") or {}
            agent = JudgeAgent(
                self._backend,
                titulo=str(input_data.get("titulo", "")),
                tipo_discurso=str(meta.get("tipo_discurso", "")),
                heuristicas=self._heuristicas,
                ontologia=self._ontologia,
                resumen=_resumen_global(summ) or None,
                enunciacion=_format_enunciacion_for_judge(enun) or None,
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
                sug = row.get("sugerencias")
                self._j_repo.set_judgment(
                    codigo, frase_idx, emo_idx,
                    coherente=bool(row["coherente"]),
                    issues=str(row["issues"]),
                    confianza=str(row["confianza"]),
                    sugerencias=sug if isinstance(sug, list) else [],
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
        exp_map = self._e_repo.resolve_canonico_map(
            codigo, "experienciador", "experienciador_marca"
        )
        fte_map = self._e_repo.resolve_canonico_map(codigo, "fuente", "fuente_marca")

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
            prev_ctx, post_ctx = self._frase_window(codigo, frase_idx)
            actantes = _parse_json_safe(emo.get("actantes_payload"))
            rows.append({
                **emo,
                "frase": frase_text,
                "ventana_previa": prev_ctx,
                "ventana_posterior": post_ctx,
                "experienciador": _effective_experiencer(emo, exp_map),
                "fuente_inferencia": _effective_fuente(emo, fte_map),
                # Del characterizer, el juez solo revisa la temporalidad.
                "temporalidad": carac.get("temporalidad", ""),
                "actantes_texto": _format_actantes_for_judge(actantes),
            })
        df = pd.DataFrame(rows)
        self._validate(EmocionExplodedContract, df, "entrada")
        return df

    def _frase_window(
        self,
        codigo: str,
        frase_idx: int,
        radius: int = _JUDGE_WINDOW,
    ) -> tuple[str, str]:
        """Texto de las frases previas y posteriores (ventana móvil)."""
        prev_parts: list[str] = []
        for j in range(frase_idx - radius, frase_idx):
            txt = self._f_repo.get_frase(codigo, j)
            if txt:
                prev_parts.append(f"    [#{j}] {txt}")
        post_parts: list[str] = []
        for j in range(frase_idx + 1, frase_idx + radius + 1):
            txt = self._f_repo.get_frase(codigo, j)
            if txt:
                post_parts.append(f"    [#{j}] {txt}")
        return "\n".join(prev_parts), "\n".join(post_parts)


# ══════════════════════════════════════════════════════════════════════════════
#  SemasStage — asignación de semas a referentes canónicos
# ══════════════════════════════════════════════════════════════════════════════

def _format_semas_vocabulario(vocab: dict[str, Any]) -> str:
    """Formatea el vocabulario de semas por dimensión para el prompt."""
    dims = vocab.get("dimensiones") or {}
    lines: list[str] = []
    for dim, info in dims.items():
        if not isinstance(info, dict):
            continue
        valores = ", ".join(str(v) for v in (info.get("valores") or []))
        desc = info.get("descripcion", "")
        line = f"- {dim}: {valores}"
        if desc:
            line += f"  ({desc})"
        lines.append(line)
    return "\n".join(lines)


def _semas_allowed(vocab: dict[str, Any]) -> set[str]:
    """Conjunto de semas válidos del vocabulario."""
    return {str(s).strip().lower() for s in (vocab.get("semas") or [])}


class SemasStage(Stage):
    """Asigna semas a cada referente canónico vía LLM, normalizados al vocabulario."""

    NAME = "semas"

    def __init__(
        self,
        backend: LLMBackend,
        menciones_repo: MencionesRepository,
        semas_vocab: dict[str, Any] | None = None,
        titulo: str = "",
        tipo_discurso: str = "",
        agent_version: str | None = None,
        retry_config: RetryConfig | None = None,
        genre: Genre | None = None,
    ) -> None:
        super().__init__()
        self._backend = backend
        self._m_repo = menciones_repo
        self._vocab = semas_vocab or {}
        self._titulo = titulo
        self._tipo_discurso = tipo_discurso
        self._version = agent_version
        self._retry_config = retry_config
        self._genre = genre

    def run_pending(self) -> int:
        """Propone semas para los referentes que aún no tienen ninguno."""
        ya = self._m_repo.canonicos_con_semas()
        pendientes = [
            c for c in self._m_repo.list_canonicos()
            if c["canonical_id"] not in ya
        ]
        if not pendientes:
            logger.info(f"[Stage:{self.NAME}] Nada pendiente.")
            return 0

        allowed = _semas_allowed(self._vocab)
        vocab_str = _format_semas_vocabulario(self._vocab)
        df = pd.DataFrame([
            {
                "canonical_id": c["canonical_id"],
                "display": c["canonical_id"],
                "marcas": c["marcas"],
            }
            for c in pendientes
        ])

        agent = SemasAgent(
            self._backend,
            vocab_str,
            titulo=self._titulo,
            tipo_discurso=self._tipo_discurso,
            retry_config=self._retry_config,
            genre=self._genre,
        )
        out = agent.run(df)

        total = 0
        for _, row in out.iterrows():
            raw = row.get("semas")
            if not raw:
                continue
            try:
                semas = json.loads(raw)
            except (json.JSONDecodeError, TypeError):
                continue
            if not isinstance(semas, list):
                continue
            total += self._m_repo.propose_semas(
                str(row["canonical_id"]),
                [str(s) for s in semas],
                allowed=allowed,
                origin="llm",
            )
        logger.info(
            f"[Stage:{self.NAME}] {len(pendientes)} referentes, "
            f"{total} semas propuestos."
        )
        return total
