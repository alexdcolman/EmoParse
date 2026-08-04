# ══════════════════════════════════════════════════════════════════════════════
#  emoparse.pipeline.stages
#
#  Etapas del pipeline.
# ══════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

import json
import re
import threading
from abc import ABC, abstractmethod
from collections import Counter
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Literal

import pandas as pd
import pandera.pandas as pa
from loguru import logger

from emoparse.agents.actants import ACTANTS_COMPONENTS, ActantsAgent
from emoparse.agents.actors import ActorsAgent
from emoparse.agents.characterizer import CharacterizerAgent
from emoparse.agents.deixis import DeixisAgent
from emoparse.agents.emotions import (
    EmotionsAgent,
    compute_emotion_full_summary,
    compute_emotion_rolling_summary,
    sanitize_emocion,
)
from emoparse.agents.emotions_pass2 import EmotionsAgentPass2
from emoparse.agents.enunciation import format_repertorio_kb
from emoparse.agents.judge import JudgeAgent
from emoparse.agents.modalidad import ModalidadAgent
from emoparse.agents.semas import SemasAgent
from emoparse.core.backend.base import LLMBackend
from emoparse.core.backend.retry import RetryConfig
from emoparse.core.text import canonical_slug
from emoparse.genres.base import Genre
from emoparse.genres.enunciator import resolve_from_input_field
from emoparse.knowledge.normalization import build_emotion_normalization_lookup
from emoparse.pipeline.contracts import (
    DiscursoInputContract,
    EmocionExplodedContract,
    FraseConActoresContract,
    FraseConEmocionesContract,
    FraseInputContract,
)
from emoparse.pipeline.contracts import (
    validate as validate_contract,
)
from emoparse.pipeline.deixis import (
    is_deictic,
    resolver_rol_enunciativo,
)
from emoparse.pipeline.emoji_lexicon import resolve_emoji_afecto
from emoparse.pipeline.emoji_rachas import (
    Racha,
    agrupar_rachas,
    marcar_racha,
    payload_repeticion,
)
from emoparse.pipeline.genre_context import GenreContextProvider
from emoparse.pipeline.modalidad_nlp import ModalidadNLP
from emoparse.pipeline.progress import ProgressReporter
from emoparse.pipeline.reply_context import reply_target
from emoparse.pipeline.technoparse import (
    TecnoEntidad,
    menciones_handles,
    parse_texto,
)
from emoparse.storage.discursos import DiscursosRepository
from emoparse.storage.emociones import EmocionesRepository
from emoparse.storage.frases import FrasesRepository
from emoparse.storage.hashtags import HashtagsRepository
from emoparse.storage.judgments import JudgmentsRepository
from emoparse.storage.menciones import MencionesRepository
from emoparse.storage.metrics import StageMetricsAccumulator
from emoparse.storage.posts import PostsRepository
from emoparse.storage.referencia import (
    canonicos_de_override,
    primer_canonico,
    split_coordinacion,
)
from emoparse.storage.tecno import TecnoRepository


class Stage(ABC):
    """Etapa abstracta del pipeline."""

    NAME: str

    def __init__(self) -> None:
        self.metrics = StageMetricsAccumulator()
        self.validate_contracts: bool = True
        self.progress = ProgressReporter(getattr(type(self), "NAME", "stage"))
        self._selector_scope: frozenset[str] | None = None

    def set_selector_scope(self, codigos: frozenset[str] | None) -> None:
        """Fija el alcance por discurso para esta ejecución de la stage."""
        self._selector_scope = codigos

    def _scope_codes(self, codigos: list[str]) -> list[str]:
        """Filtra códigos según el selector dinámico vigente."""
        if self._selector_scope is None:
            return codigos
        return [codigo for codigo in codigos if codigo in self._selector_scope]

    def _scope_tuples(self, rows: list[tuple[Any, ...]]) -> list[tuple[Any, ...]]:
        """Filtra tuplas cuyo primer elemento es el código de discurso."""
        if self._selector_scope is None:
            return rows
        return [row for row in rows if str(row[0]) in self._selector_scope]

    def _scope_records(
        self,
        rows: list[dict[str, Any]],
        key: str = "codigo",
    ) -> list[dict[str, Any]]:
        """Filtra registros por una clave que identifica el discurso/post."""
        if self._selector_scope is None:
            return rows
        return [row for row in rows if str(row.get(key, "")) in self._selector_scope]

    def _validate(
        self,
        contract: type[pa.DataFrameModel],
        df: pd.DataFrame,
        label: str = "",
    ) -> pd.DataFrame:
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
        codigos = self._scope_codes(
            self._repo.list_pending(self.STAGE_KEY)  # type: ignore[arg-type]
        )
        if not codigos:
            logger.info(f"[Stage:{self.NAME}] Nada pendiente.")
            return 0

        ok = 0
        for codigo in self.progress.track(codigos, "discursos"):
            row_dict = self._prepare_row(codigo)
            if row_dict is None:
                continue
            ok += self._process_one(codigo, row_dict)

        logger.info(
            f"[Stage:{self.NAME}] Completado: {ok}/{len(codigos)} ok, "
            f"{len(codigos) - ok} con error."
        )
        return ok

    def _prepare_row(self, codigo: str) -> dict[str, Any] | None:
        """Input del discurso aumentado por la stage, o None si no hay input."""
        input_data = self._repo.get_input(codigo)
        if input_data is None:
            logger.warning(f"[Stage:{self.NAME}] {codigo}: sin input en DB, salteando")
            return None
        return self._augment_input(codigo, {"codigo": codigo, **input_data})

    def _process_one(self, codigo: str, row_dict: dict[str, Any]) -> int:
        """Corre el agente sobre un discurso ya preparado. Devuelve 1 si ok."""
        # DF de 1 fila para reutilizar la API run() del agente.
        df_in = pd.DataFrame([row_dict])
        self._validate(DiscursoInputContract, df_in, "entrada")

        try:
            df_out = self._agent.run(df_in)
        except Exception as e:
            logger.error(f"[Stage:{self.NAME}] {codigo}: error inesperado: {e}")
            self._repo.set_error(codigo, self.STAGE_KEY, str(e))  # type: ignore[arg-type]
            self.metrics.record_item_failed()
            return 0

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
            return 0

        self._repo.set_payload(
            codigo,
            self.STAGE_KEY,  # type: ignore[arg-type]
            payload,
            version=self._version,
        )
        self.metrics.record_item_ok()
        return 1

    def _augment_input(self, codigo: str, row_dict: dict[str, Any]) -> dict[str, Any]:
        """Hook para enriquecer el input antes de construir el DF del agente.

        Por defecto no hace nada; las subclases pueden agregar columnas
        derivadas (p. ej. el enunciador fijado en `EnunciationStage`).
        """
        return row_dict

    @abstractmethod
    def _extract_payload(self, row: pd.Series) -> dict[str, Any] | None:
        """Extrae payload desde una row del agente."""


class SummarizerStage(_DiscursoStage):
    NAME = "summarizer"
    STAGE_KEY = "summarizer"

    def __init__(
        self,
        agent: Any,
        discursos_repo: DiscursosRepository,
        agent_version: str | None = None,
        genre_context_provider: GenreContextProvider | None = None,
    ) -> None:
        super().__init__(agent, discursos_repo, agent_version=agent_version)
        self._genre_context = genre_context_provider

    def _augment_input(self, codigo: str, row_dict: dict[str, Any]) -> dict[str, Any]:
        return _inject_genre_context(
            row_dict,
            stage="summarizer",
            provider=self._genre_context,
        )

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

    def __init__(
        self,
        agent: Any,
        discursos_repo: DiscursosRepository,
        agent_version: str | None = None,
        posts_repo: Any | None = None,
        embed_context_provider: Any | None = None,
        hilo_context_provider: Any | None = None,
        genre_context_provider: GenreContextProvider | None = None,
    ) -> None:
        super().__init__(agent, discursos_repo, agent_version=agent_version)
        self._posts_repo = posts_repo
        self._embed_ctx = embed_context_provider
        self._hilo_ctx = hilo_context_provider
        self._genre_context = genre_context_provider

    def _augment_input(self, codigo: str, row_dict: dict[str, Any]) -> dict[str, Any]:
        row_dict = _contexto_cuenta(codigo, row_dict, self._posts_repo, self._embed_ctx)
        row_dict = _inject_contexto_hilo(codigo, row_dict, self._hilo_ctx)
        return _inject_genre_context(
            row_dict,
            stage="metadata",
            provider=self._genre_context,
        )

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
    """Identifica la estructura enunciativa, con el enunciador resuelto antes.

    La identificación del enunciador es un sub-paso previo, simétrico entre
    géneros: determinista desde la cuenta autora cuando el género declara
    `enunciador_from_handle` (funciona igual con corpus seudonimizados, el
    alias es estable por cuenta), o vía `EnunciatorIdAgent` (prompt mínimo,
    modelo configurable) en los géneros clásicos. El enunciador fijado se
    propaga al prompt principal, que solo identifica enunciatarios, auditorio
    y colectivos; la KB de enunciación aporta el repertorio conocido de ese
    enunciador como contexto (estabilidad por cuenta sin propagación dura).
    En géneros con `auditorio_predeterminado`, el auditorio se construye de
    forma determinista desde el dispositivo (seguidores, hashtags, menciones).
    """

    NAME = "enunciation"
    STAGE_KEY = "enunciation"

    def __init__(
        self,
        agent: Any,
        discursos_repo: DiscursosRepository,
        agent_version: str | None = None,
        enunciator_agent: Any | None = None,
        genre: Genre | None = None,
        enunciacion_kb: dict[str, Any] | None = None,
        posts_repo: Any | None = None,
        embed_context_provider: Any | None = None,
        hilo_context_provider: Any | None = None,
        enunciator_release: Any | None = None,
        genre_context_provider: GenreContextProvider | None = None,
    ) -> None:
        super().__init__(agent, discursos_repo, agent_version=agent_version)
        self._enunciator_agent = enunciator_agent
        self._genre = genre
        self._enunciacion_kb = enunciacion_kb or {}
        self._posts_repo = posts_repo
        self._embed_ctx = embed_context_provider
        self._hilo_ctx = hilo_context_provider
        self._enunciator_release = enunciator_release
        self._genre_context = genre_context_provider

    def run_pending(self) -> int:
        """Procesa en dos fases para no sostener dos modelos en VRAM.

        Fase 1: prepara el input de TODOS los pendientes (resuelve el
        enunciador con el sub-paso, que puede usar un modelo propio). Fase 2:
        corre el análisis principal. Entre fases, si el runner pasó un
        callback de liberación, se descarga el modelo del sub-paso: los dos
        modelos nunca conviven durante la fase larga.
        """
        codigos = self._scope_codes(
            self._repo.list_pending(self.STAGE_KEY)  # type: ignore[arg-type]
        )
        if not codigos:
            logger.info(f"[Stage:{self.NAME}] Nada pendiente.")
            return 0

        logger.info(
            f"[Stage:{self.NAME}] Procesando {len(codigos)} discurso(s) "
            "(fase 1: enunciadores; fase 2: análisis principal)."
        )
        preparados: list[tuple[str, dict[str, Any]]] = []
        for codigo in codigos:
            row_dict = self._prepare_row(codigo)
            if row_dict is not None:
                preparados.append((codigo, row_dict))

        if self._enunciator_release is not None:
            try:
                self._enunciator_release()
            except Exception as e:
                logger.warning(
                    f"[Stage:{self.NAME}] No se pudo liberar el modelo del "
                    f"sub-paso de enunciador: {e}"
                )

        ok = 0
        for codigo, row_dict in self.progress.track(preparados, "discursos"):
            ok += self._process_one(codigo, row_dict)

        logger.info(
            f"[Stage:{self.NAME}] Completado: {ok}/{len(codigos)} ok, "
            f"{len(codigos) - ok} con error."
        )
        return ok

    def _augment_input(self, codigo: str, row_dict: dict[str, Any]) -> dict[str, Any]:
        # El tipo de discurso lo resuelve metadata (corre antes): habilita al
        # agente a listar en el prompt los roles enunciativos de ese tipo (más
        # los transversales) y a descartar post-hoc los que no correspondan.
        meta = self._repo.get_payload(codigo, "metadata")
        if isinstance(meta, dict) and meta.get("tipo_discurso"):
            row_dict["tipo_discurso"] = meta["tipo_discurso"]
        # Los campos de la cuenta autora no viajan en el input del discurso:
        # se hidratan desde posts/autores ANTES de resolver enunciador y
        # auditorio (codigo == post_id en el género tuit).
        _hidratar_desde_posts(codigo, row_dict, self._posts_repo)
        enunciador, justificacion = self._resolver_enunciador(codigo, row_dict)
        if enunciador and enunciador.lower() != "no identificado":
            row_dict["enunciador_fijado"] = enunciador
            if justificacion:
                row_dict["enunciador_fijado_justificacion"] = justificacion
            repertorio = format_repertorio_kb(
                (self._enunciacion_kb.get("enunciadores") or {}).get(canonical_slug(enunciador))
            )
            if repertorio:
                row_dict["repertorio_kb"] = repertorio
        if self._genre is not None and self._genre.auditorio_predeterminado:
            row_dict["auditorio_fijo"] = json.dumps(
                _auditorio_predeterminado(row_dict), ensure_ascii=False
            )
            resolved_reply_target = reply_target(codigo, self._posts_repo)
            if resolved_reply_target is not None:
                row_dict["reply_target_fijo"] = json.dumps(
                    resolved_reply_target, ensure_ascii=False
                )
        row_dict = _contexto_cuenta(codigo, row_dict, self._posts_repo, self._embed_ctx)
        row_dict = _inject_contexto_hilo(codigo, row_dict, self._hilo_ctx)
        return _inject_genre_context(
            row_dict,
            stage="enunciation",
            provider=self._genre_context,
        )

    def _resolver_enunciador(self, codigo: str, row_dict: dict[str, Any]) -> tuple[str, str]:
        """Devuelve (enunciador, justificacion) fijados, o ('', '')."""
        if self._genre is not None and self._genre.enunciador_from_input_field:
            campo = self._genre.enunciador_from_input_field
            referente, justificacion = resolve_from_input_field(row_dict, campo)
            if referente:
                return referente, justificacion
            logger.warning(
                f"[Stage:{self.NAME}] {codigo}: el campo determinista "
                f"'{campo}' no contiene referentes; se infiere por LLM."
            )

        if self._genre is not None and self._genre.enunciador_from_handle:
            # El handle tiene prioridad sobre el display: es único por cuenta
            # (el display puede repetirse entre usuarios y rompería el
            # agrupamiento canónico). Los campos viven en el input JSON.
            handle = _campo_input(row_dict, "autor_handle").lstrip("@")
            display = _campo_input(row_dict, "autor_display")
            if handle or display:
                enunciador = f"@{handle}" if handle else display
                justificacion = "Cuenta autora del post" + (
                    f" ({display})." if handle and display else "."
                )
                return enunciador, justificacion
            logger.warning(
                f"[Stage:{self.NAME}] {codigo}: sin autor_handle ni "
                "autor_display en el input; el referente se infiere por LLM."
            )
            return "", ""
        if self._enunciator_agent is None:
            return "", ""
        try:
            df_out = self._enunciator_agent.run(pd.DataFrame([dict(row_dict)]))
            row = df_out.iloc[0]
            valor = row.get("enunciador_fijado")
            if valor is None or (isinstance(valor, float) and pd.isna(valor)):
                return "", ""
            return (
                str(valor).strip(),
                str(row.get("enunciador_fijado_justificacion") or "").strip(),
            )
        except Exception as e:
            logger.warning(
                f"[Stage:{self.NAME}] {codigo}: sub-paso de identificación "
                f"del enunciador falló ({e}); se infiere en el paso principal."
            )
            return "", ""

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


def _input_dict(row_dict: dict[str, Any]) -> dict[str, Any]:
    """Payload del input original del discurso, tolerante al formato.

    Los campos del CSV/JSONL de origen (autor_handle, autor_display, fecha…)
    no son columnas de `discursos`: viven en el JSON de la columna `input`.
    Devuelve {} si falta o es ilegible.
    """
    raw = row_dict.get("input")
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str) and raw.strip():
        try:
            parsed = json.loads(raw)
            return parsed if isinstance(parsed, dict) else {}
        except json.JSONDecodeError:
            return {}
    return {}


def _campo_input(row_dict: dict[str, Any], campo: str) -> str:
    """Un campo del post: columna directa primero, input JSON después."""
    directo = str(row_dict.get(campo) or "").strip()
    if directo:
        return directo
    return str(_input_dict(row_dict).get(campo) or "").strip()


def _hidratar_desde_posts(
    codigo: str,
    row_dict: dict[str, Any],
    posts_repo: Any | None,
) -> dict[str, Any]:
    """Completa autor_handle/autor_display/contenido desde `posts`/`autores`.

    El input de `discursos` derivado de un corpus de posts no incluye los
    campos de la cuenta autora: la fuente de verdad es la tabla `posts`
    (autor_handle es NOT NULL ahí; codigo == post_id en el género tuit) y el
    display vive en `autores`. Idempotente: solo completa lo que falta.
    """
    # En inputs de ingestas previas el handle viajaba bajo la clave `autor`
    # (sin `autor_handle`): se toma de ahí antes de consultar la DB.
    if not _campo_input(row_dict, "autor_handle"):
        autor = _campo_input(row_dict, "autor")
        if autor:
            row_dict["autor_handle"] = autor
    if posts_repo is None:
        return row_dict
    if not _campo_input(row_dict, "autor_handle") or not _campo_input(row_dict, "contenido"):
        try:
            post = posts_repo.get_post(codigo)
        except Exception:
            post = None
        if post is not None:
            if not _campo_input(row_dict, "autor_handle"):
                row_dict["autor_handle"] = str(post.get("autor_handle") or "")
            if not _campo_input(row_dict, "contenido"):
                row_dict["contenido"] = str(post.get("texto") or "")
    handle = _campo_input(row_dict, "autor_handle").lstrip("@")
    if handle and not _campo_input(row_dict, "autor_display"):
        try:
            autor = posts_repo.get_autor(handle)
        except Exception:
            autor = None
        display = str((autor or {}).get("display_name") or "").strip()
        if display:
            row_dict["autor_display"] = display
    return row_dict


def _contexto_cuenta(
    codigo: str,
    row_dict: dict[str, Any],
    posts_repo: Any | None,
    embed_ctx: Any | None,
) -> dict[str, Any]:
    """Suma bio de la cuenta autora y adjuntos del post al input, si hay.

    La bio contextualiza (cuentas periodísticas, institucionales) sin forzar
    inferencias; los adjuntos vienen del provider de embed (opt-in). Ambos
    campos son opcionales: los templates los omiten si faltan.
    """
    if posts_repo is not None:
        _hidratar_desde_posts(codigo, row_dict, posts_repo)
        handle = _campo_input(row_dict, "autor_handle").lstrip("@")
        if handle:
            try:
                autor = posts_repo.get_autor(handle)
            except Exception:
                autor = None
            bio = str((autor or {}).get("bio") or "").strip()
            if bio:
                row_dict["autor_bio"] = bio[:600]
    if embed_ctx is not None:
        try:
            adjuntos = embed_ctx(codigo)
        except Exception:
            adjuntos = None
        if adjuntos:
            row_dict["adjuntos"] = adjuntos
    return row_dict


def _inject_contexto_hilo(
    codigo: str,
    row_dict: dict[str, Any],
    hilo_ctx: Any | None,
) -> dict[str, Any]:
    """Suma el contexto conversacional del post al input, si el provider existe.

    Campo opcional (`contexto_hilo`): los templates de metadata y enunciation
    lo omiten si falta. En géneros no conversacionales el provider es None y
    no se paga costo alguno."""
    if hilo_ctx is None:
        return row_dict
    try:
        contexto = hilo_ctx(codigo)
    except Exception:
        contexto = None
    if contexto:
        row_dict["contexto_hilo"] = contexto
    return row_dict


def _inject_genre_context(
    row_dict: dict[str, Any],
    *,
    stage: Literal["summarizer", "metadata", "enunciation"],
    provider: GenreContextProvider | None,
) -> dict[str, Any]:
    """Suma bloques declarados por el género para una stage de discurso."""
    if provider is None:
        return row_dict
    contexto = provider.render(stage, row_dict)
    if contexto:
        row_dict["contexto_genero"] = contexto
    return row_dict


def _auditorio_predeterminado(row_dict: dict[str, Any]) -> list[dict[str, str]]:
    """Auditorio determinista de un post, desde el dispositivo.

    Tres categorías, sin inferencia: seguidores de la cuenta (siempre), un
    auditorio por hashtag presente (nunca combinados en uno solo) y un
    destinatario directo por cuenta mencionada (excluida la propia).
    """
    handle = _campo_input(row_dict, "autor_handle").lstrip("@")
    cuenta = f"@{handle}" if handle else "la cuenta"
    entries: list[dict[str, str]] = [
        {
            "actor": f"seguidores de {cuenta}",
            "justificacion": "Auditorio estructural de la cuenta autora.",
        }
    ]
    entidades = parse_texto(_campo_input(row_dict, "contenido"))
    vistos: set[str] = set()
    for ent in entidades:
        if ent.tipo != "hashtag":
            continue
        tag = str(ent.valor_norm or ent.valor).lstrip("#")
        if tag and tag.lower() not in vistos:
            vistos.add(tag.lower())
            entries.append(
                {
                    "actor": f"usuarios que navegan #{tag}",
                    "justificacion": f"Conversación pública del hashtag #{tag}.",
                }
            )
    vistos = set()
    for m in menciones_handles(entidades):
        h = str(m.valor_norm or m.valor).lstrip("@")
        if h and h.lower() not in vistos and h.lower() != handle.lower():
            vistos.add(h.lower())
            entries.append(
                {
                    "actor": f"@{h}",
                    "justificacion": "Destinatario directo por mención.",
                }
            )
    return entries


# ══════════════════════════════════════════════════════════════════════════════
#  Etapas a nivel frase
# ══════════════════════════════════════════════════════════════════════════════


class _FraseStage(Stage):
    """Base para etapas que procesan frases.

    `parallel` > 1 procesa varios discursos en simultáneo (un agente por
    discurso, como siempre). Pensado para backends servidor (llama-server,
    LM Studio) con continuous batching: la inferencia va en paralelo y la
    persistencia se serializa bajo lock. Con el backend in-process de
    llama.cpp debe quedar en 1 (un solo modelo en memoria, llamadas
    bloqueantes); el runner lo fuerza.
    """

    STAGE_KEY: str  # "actores" | "emociones"

    #: Discursos procesados en simultáneo. Lo asigna el runner según
    #: `pipeline.parallel` y el tipo de backend de la stage; 1 = secuencial.
    parallel: int = 1

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
        self._persist_lock = threading.Lock()

    def run_pending(self) -> int:
        """Procesa frases pendientes agrupadas por discurso."""
        all_pending = self._scope_tuples(
            self._f_repo.list_pending(self.STAGE_KEY)  # type: ignore[arg-type]
        )
        if not all_pending:
            logger.info(f"[Stage:{self.NAME}] Nada pendiente.")
            return 0

        by_codigo: dict[str, list[int]] = {}
        for codigo, unit_idx in all_pending:
            by_codigo.setdefault(codigo, []).append(unit_idx)

        logger.info(
            f"[Stage:{self.NAME}] Procesando {len(by_codigo)} discurso(s) "
            f"con {sum(len(v) for v in by_codigo.values())} frases pendientes"
            + (f" (parallel={self.parallel})." if self.parallel > 1 else ".")
        )

        total_ok = 0
        self.progress.start(sum(len(v) for v in by_codigo.values()), "frases")
        if self.parallel <= 1:
            for codigo, pending_idxs in by_codigo.items():
                total_ok += self._process_codigo(codigo, pending_idxs)
        else:
            with ThreadPoolExecutor(max_workers=self.parallel) as pool:
                futures = {
                    pool.submit(self._process_codigo, codigo, idxs): codigo
                    for codigo, idxs in by_codigo.items()
                }
                for future in as_completed(futures):
                    total_ok += future.result()
        self.progress.finish()

        logger.info(f"[Stage:{self.NAME}] Completado: {total_ok} frases ok.")
        return total_ok

    def _process_codigo(self, codigo: str, pending_idxs: list[int]) -> int:
        """Procesa un discurso completo. Thread-safe: la inferencia corre
        fuera del lock; persistencia y métricas, adentro."""
        input_data = self._d_repo.get_input(codigo) or {}

        agent = self._build_agent(input_data, codigo)

        df_in = self._build_input_df(codigo, pending_idxs)
        if df_in.empty:
            return 0
        self._validate(self._input_contract(), df_in, "entrada")

        try:
            df_out = agent.run(df_in)
        except Exception as e:
            logger.error(f"[Stage:{self.NAME}] {codigo}: error inesperado: {e}")
            with self._persist_lock:
                for idx in pending_idxs:
                    self._f_repo.set_error(
                        codigo,
                        idx,
                        self.STAGE_KEY,
                        str(e),  # type: ignore[arg-type]
                    )
                    self.metrics.record_item_failed()
            return 0

        ok = 0
        with self._persist_lock:
            for _, row in df_out.iterrows():
                idx = int(row["unit_idx"])
                payload_raw = self._extract_payload(row)
                if payload_raw is None:
                    self._f_repo.set_error(
                        codigo,
                        idx,
                        self.STAGE_KEY,  # type: ignore[arg-type]
                        "Backend error (ver logs del agente)",
                    )
                    self.metrics.record_item_failed()
                    continue
                self._f_repo.set_payload(
                    codigo,
                    idx,
                    self.STAGE_KEY,  # type: ignore[arg-type]
                    payload_raw,
                    version=self._version,
                )
                ok += 1
                self.metrics.record_item_ok()
        self.progress.advance(len(pending_idxs))
        return ok

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
            rows.append(
                {
                    "codigo": codigo,
                    "unit_idx": idx,
                    "frase": frase,
                }
            )
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

    def _build_agent(self, input_data: dict[str, Any], codigo: str) -> ActorsAgent:
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


def _resumen_global(summ: dict[str, Any] | None, limit: int = 1500) -> str:
    """Resumen global del discurso (payload `summarizer`), truncado.

    Tolerante a la clave con que el summarizer lo haya guardado. Se inyecta
    como contexto de fondo en los prompts de emociones (pases 1 y 2) y del
    juez. Vacío si no hay resumen: el template omite la sección
    (`{% if resumen %}`).
    """
    if not isinstance(summ, dict):
        return ""
    for clave in ("resumen_global", "resumen", "global", "summary"):
        valor = summ.get(clave)
        if isinstance(valor, str) and valor.strip():
            texto = valor.strip()
            return texto[:limit] + "..." if len(texto) > limit else texto
    return ""


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
        heuristicas: str,
        configuraciones: str = "",
        modos_existencia: str = "",
        emotion_scope: tuple[str, ...] | None = None,
        agent_version: str | None = None,
        retry_config: RetryConfig | None = None,
        genre: Genre | None = None,
        hilo_context_provider: Callable[[str], str | None] | None = None,
        tecno_context_provider: Callable[[str, int], str | None] | None = None,
        media_context_provider: Callable[[str], str | None] | None = None,
        genre_context_provider: GenreContextProvider | None = None,
    ) -> None:
        super().__init__(backend, discursos_repo, frases_repo, agent_version, retry_config, genre)
        self._heuristicas = heuristicas
        self._configuraciones = configuraciones
        self._modos_existencia = modos_existencia
        self._emotion_scope = tuple(emotion_scope) if emotion_scope else None
        # Providers opcionales de contexto para discurso nativo digital:
        # hilo (cadena de posts padre + cita), tecno (tecnolingüísticos
        # extraídos) y media (descripciones de vision_describe).
        # Deterministas; se inyectan como columnas del DF.
        self._hilo_ctx = hilo_context_provider
        self._tecno_ctx = tecno_context_provider
        self._media_ctx = media_context_provider
        self._genre_context = genre_context_provider

    def _build_agent(self, input_data: dict[str, Any], codigo: str) -> EmotionsAgent:
        """Construye EmotionsAgent con modos, configuraciones y heurísticas."""
        meta = self._d_repo.get_payload(codigo, "metadata") or {}
        enun = self._d_repo.get_payload(codigo, "enunciation") or {}
        summ = self._d_repo.get_payload(codigo, "summarizer") or {}
        contexto_genero = (
            self._genre_context.render("emotions", input_data)
            if self._genre_context is not None
            else None
        )
        return EmotionsAgent(
            self._backend,
            heuristicas=self._heuristicas,
            configuraciones=self._configuraciones,
            titulo=str(input_data.get("titulo", "")),
            tipo_discurso=str(meta.get("tipo_discurso", "")),
            enunciador=str(enun.get("enunciador", "")),
            enunciatarios=_format_enunciatarios(enun.get("enunciatarios")),
            auditorio=_format_enunciatarios(enun.get("auditorio")),
            resumen=_resumen_global(summ),
            contexto_genero=contexto_genero or "",
            modos_existencia=self._modos_existencia,
            emotion_scope=self._emotion_scope,
            retry_config=self._retry_config,
            genre=self._genre,
        )

    def _build_input_df(
        self,
        codigo: str,
        unit_idxs: list[int],
    ) -> pd.DataFrame:
        """Construye DataFrame con frases, actores y contexto opcional."""
        contexto_hilo = self._hilo_ctx(codigo) if self._hilo_ctx else None
        media_desc = self._media_ctx(codigo) if self._media_ctx else None
        rows: list[dict[str, Any]] = []
        for idx in unit_idxs:
            frase = self._f_repo.get_frase(codigo, idx)
            if frase is None:
                continue
            actores = self._f_repo.get_payload(codigo, idx, "actores")
            actores_str = json.dumps(actores, ensure_ascii=False) if actores is not None else None
            row: dict[str, Any] = {
                "codigo": codigo,
                "unit_idx": idx,
                "frase": frase,
                "actores": actores_str,
            }
            if contexto_hilo:
                row["contexto_hilo"] = contexto_hilo
            if self._tecno_ctx is not None:
                tecno = self._tecno_ctx(codigo, idx)
                if tecno:
                    row["tecno"] = tecno
            if media_desc:
                row["media_desc"] = media_desc
            rows.append(row)
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

#: Posesivo anafórico en el segundo término de una coordinación
#: ("Carlitos y su círculo cercano").
_POSESIVO_RE = re.compile(r"^(?:su|sus)\s+(.+)$", re.IGNORECASE)


def _resolver_posesivo(parte: str, antecedente: str) -> str:
    """Expande un posesivo anafórico contra el primer término coordinado.

    "Carlitos y su círculo cercano" se parte en "Carlitos" y "su círculo
    cercano"; el segundo, aislado, no designa a nadie. Se reescribe como
    "círculo cercano de Carlitos" para que sea un referente autónomo. Solo
    afecta a la INFERENCIA: la marca es transcripción literal de la unidad
    y nunca se reescribe.
    """
    m = _POSESIVO_RE.match(parte.strip())
    antecedente = antecedente.strip()
    if not m or not antecedente:
        return parte
    return f"{m.group(1).strip()} de {antecedente}"


def _desdoblar_emociones(emos: list[Any]) -> list[Any]:
    """Garantiza una emoción por experienciador.

    Respaldo determinístico del contrato del prompt: si el modelo devolvió
    igual un experienciador coordinado ("Macri y Milei"), la emoción se
    desdobla en una entrada por entidad, alineando la marca cuando la
    partición de marca e inferencia coinciden en cantidad. El modo de
    existencia se conserva en cada copia.

    La fuente NO se parte: una emoción tiene un experienciador, pero su fuente
    puede combinar entidades ("libertarios, radicales y macristas" desencadena
    una sola emoción). Los referentes de esa fuente los resuelve la capa de
    marcas, sin multiplicar filas.

    Cuando la marca no acompaña la partición —el caso habitual, porque la
    entidad compuesta suele estar en la inferencia y no en el texto—, todas
    las copias comparten la misma marca y la resolución marca↔referente no
    puede distinguirlas: colapsarían en un solo referente. Para eso cada copia
    se lleva su propio `experienciador_canonico` por emoción (de origen
    automático), que prima sobre esa resolución.
    """
    out: list[Any] = []
    for emo in emos:
        if not isinstance(emo, dict):
            out.append(emo)
            continue
        # Red de seguridad: el agente ya sanea, pero el explode también
        # consume payloads de runs anteriores.
        emo = sanitize_emocion(emo)
        exp = str(emo.get("experienciador") or "").strip()
        exp_parts = _partes_distintas(_expandir_posesivos(split_coordinacion(exp)))
        if len(exp_parts) < 2:
            out.append(emo)
            continue
        marca_parts = split_coordinacion(str(emo.get("experienciador_marca") or "").strip())
        aligned = marca_parts if len(marca_parts) == len(exp_parts) else None
        for k, parte in enumerate(exp_parts):
            nuevo = dict(emo)
            nuevo["experienciador"] = parte
            if aligned:
                nuevo["experienciador_marca"] = aligned[k]
            else:
                nuevo["experienciador_canonico"] = canonical_slug(parte)
            out.append(nuevo)
    return _dedupe_emociones(out)


def _resolver_roles_enunciativos(
    emos: list[Any],
    enunciador: str,
    auditorio: tuple[str, ...],
) -> list[Any]:
    """Sustituye las etiquetas de rol enunciativo por el referente que las ocupa.

    El modelo devuelve a veces "el enunciador" o "los enunciatarios" en los
    campos de inferencia, que piden un referente concreto. La sustitución es
    determinista y por discurso: sale de la estructura enunciativa ya
    identificada, sin costo de prompt. Solo toca la inferencia; la marca es
    transcripción literal de la unidad y nunca se reescribe.
    """
    if not (enunciador or auditorio):
        return emos
    for emo in emos:
        if not isinstance(emo, dict):
            continue
        for campo in ("experienciador", "fuente_inferencia"):
            referente = resolver_rol_enunciativo(
                str(emo.get(campo) or ""), enunciador, list(auditorio)
            )
            if referente:
                emo[campo] = referente
    return emos


def _expandir_posesivos(partes: list[str]) -> list[str]:
    """Resuelve los posesivos anafóricos de una coordinación ya partida."""
    if len(partes) < 2:
        return partes
    antecedente = partes[0]
    return [partes[0]] + [_resolver_posesivo(p, antecedente) for p in partes[1:]]


def _partes_distintas(partes: list[str]) -> list[str]:
    """Filtra las partes de un split que colapsan al mismo referente.

    "la audiencia / los lectores de la nota" puede partirse en formas que
    resuelven al mismo canónico: si tras el slug quedan menos de dos
    referentes distintos, no hay coordinación real y no se desdobla.
    """
    vistos: set[str] = set()
    out: list[str] = []
    for parte in partes:
        slug = canonical_slug(parte) or parte.strip().lower()
        if slug and slug not in vistos:
            vistos.add(slug)
            out.append(parte)
    return out


def _dedupe_emociones(emos: list[Any]) -> list[Any]:
    """Descarta emociones exactamente duplicadas dentro de la misma frase.

    Dos entradas son duplicados si coinciden tipo, experienciador, fuente y
    modo de existencia (por slug, no por forma superficial): una emoción por
    experienciador implica también que no haya dos filas idénticas del mismo
    simulacro.
    """
    vistos: set[tuple[str, str, str, str]] = set()
    out: list[Any] = []
    for emo in emos:
        if not isinstance(emo, dict):
            out.append(emo)
            continue
        clave = (
            str(emo.get("tipo_emocion") or "").strip().lower(),
            canonical_slug(str(emo.get("experienciador") or "")),
            canonical_slug(str(emo.get("fuente_inferencia") or "")),
            str(emo.get("modo_existencia") or "").strip().lower(),
        )
        if clave in vistos:
            continue
        vistos.add(clave)
        out.append(emo)
    return out


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
        codigos = self._scope_codes(self._d_repo.list_codigos())
        total = 0
        for codigo in self.progress.track(codigos, "discursos"):
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
        enun = self._d_repo.get_payload(codigo, "enunciation") or {}
        enunciador, auditorio, _ = _extract_enunciation_referentes(enun)
        rows: list[dict[str, Any]] = []
        emociones_by_unit: dict[int, Any] = {}
        actores_by_unit: dict[int, Any] = {}
        for frase_idx, _frase_text in frases:
            if self._m_repo is not None:
                actores_by_unit[frase_idx] = self._f_repo.get_payload(codigo, frase_idx, "actores")
            emos_payload = self._select_emociones_payload(codigo, frase_idx)
            if not isinstance(emos_payload, list):
                continue
            emos_payload = _resolver_roles_enunciativos(emos_payload, enunciador, auditorio)
            emos_payload = _desdoblar_emociones(emos_payload)
            emociones_by_unit[frase_idx] = emos_payload
            for emo_idx, emo in enumerate(emos_payload):
                if not isinstance(emo, dict):
                    continue
                rows.append(
                    {
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
                        # Presentes solo cuando el desdoblamiento tuvo que fijar
                        # el referente por emoción (la marca no lo distingue).
                        "experienciador_canonico": emo.get("experienciador_canonico"),
                        "fuente_canonico": emo.get("fuente_canonico"),
                    }
                )
        if rows:
            df_rows = pd.DataFrame(rows)
            self._validate(EmocionExplodedContract, df_rows, "salida")
            self._e_repo.upsert_emociones(rows)
        if self._m_repo is not None:
            self._m_repo.rebuild_for_codigo(codigo, actores_by_unit, emociones_by_unit)
            self._m_repo.propose_coref_equivalences(codigo)
            self._m_repo.add_deixis_suggestions(codigo, enunciador)
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
#  Etapa de parsing tecnodiscursivo (determinista, sin LLM)
# ══════════════════════════════════════════════════════════════════════════════


class TechnoparseStage(Stage):
    """Extrae los tecnolingüísticos de cada unidad y los persiste.

    Determinista y sin LLM: hashtags (con función sintáctica), menciones
    (@handles, con posición), URLs, emojis y tecnografismos van a
    `tecno_entidades` con sus offsets; el texto de la unidad no se altera.
    Cada @handle siembra además una marca en `menciones` con vínculo
    canónico aceptado (designación determinista), de modo que la base de
    referentes arranca poblada antes de cualquier inferencia.
    """

    NAME = "technoparse"

    def __init__(
        self,
        discursos_repo: DiscursosRepository,
        frases_repo: FrasesRepository,
        tecno_repo: TecnoRepository,
        menciones_repo: MencionesRepository | None = None,
        naturaleza_by_handle: dict[str, str] | None = None,
    ) -> None:
        super().__init__()
        self._d_repo = discursos_repo
        self._f_repo = frases_repo
        self._t_repo = tecno_repo
        self._m_repo = menciones_repo
        self._naturaleza = naturaleza_by_handle or {}

    def run_pending(self) -> int:
        """Procesa todas las unidades del corpus (recomputación idempotente)."""
        codigos = self._scope_codes(self._d_repo.list_codigos())
        total = 0
        for codigo in self.progress.track(codigos, "discursos"):
            total += self._parse_codigo(codigo)
        if total > 0:
            logger.info(
                f"[Stage:{self.NAME}] Extraídas {total} entidades "
                f"tecnodiscursivas en {len(codigos)} discursos."
            )
        return total

    def _parse_codigo(self, codigo: str) -> int:
        """Extrae y persiste las entidades de un discurso."""
        frases = self._f_repo.list_frases_of_discurso(codigo)
        rows: list[dict[str, Any]] = []
        seeds: list[dict[str, Any]] = []
        for unit_idx, texto in frases:
            entidades = parse_texto(str(texto or ""))
            rows.extend(_entidad_row(unit_idx, e) for e in entidades)
            for m in menciones_handles(entidades):
                seeds.append(
                    {
                        "unit_idx": unit_idx,
                        "marca": m.valor,
                        "handle": m.valor_norm,
                    }
                )
        self._t_repo.replace_for_codigo(codigo, rows)
        if self._m_repo is not None and seeds:
            self._m_repo.seed_technoparse(codigo, seeds, self._naturaleza)
        self.metrics.record_item_ok()
        return len(rows)


def _entidad_row(unit_idx: int, entidad: TecnoEntidad) -> dict[str, Any]:
    """Convierte una TecnoEntidad a fila persistible."""
    return {
        "unit_idx": unit_idx,
        "tipo": entidad.tipo,
        "valor": entidad.valor,
        "valor_norm": entidad.valor_norm,
        "inicio": entidad.inicio,
        "fin": entidad.fin,
        "extra": entidad.extra,
    }


# ══════════════════════════════════════════════════════════════════════════════
#  Etapa de reframing (redocumentación: citas y reposts con comentario)
# ══════════════════════════════════════════════════════════════════════════════


class ReframingStage(Stage):
    """Clasifica la operación de recontextualización de posts que citan.

    Opera a nivel post (no frase): junta cada citador con su citado (si fue
    capturado) y procesa todo el corpus en batches de un solo agente, dado
    que el par citador/citado es autocontenido. Persiste en `posts`.
    """

    NAME = "reframing"

    def __init__(
        self,
        backend: LLMBackend,
        posts_repo: PostsRepository,
        heuristicas: str | None = None,
        agent_version: str | None = None,
        retry_config: RetryConfig | None = None,
        genre: Genre | None = None,
        emociones_provider: Callable[[str], str | None] | None = None,
    ) -> None:
        super().__init__()
        self._backend = backend
        self._p_repo = posts_repo
        self._heuristicas = heuristicas
        self._version = agent_version
        self._retry_config = retry_config
        self._genre = genre
        # Emociones ya detectadas en el post citado. Opcional: si las stages
        # de emociones no corrieron, el agente vuelve a leerlas del texto.
        self._emociones = emociones_provider

    def run_pending(self) -> int:
        """Procesa los posts citadores pendientes."""
        from emoparse.agents.reframing import ReframingAgent

        pendientes = self._scope_records(self._p_repo.list_pending_reframing(), key="post_id")
        if not pendientes:
            logger.info(f"[Stage:{self.NAME}] Nada pendiente.")
            return 0

        rows: list[dict[str, Any]] = []
        for post in pendientes:
            citado_id = post.get("cita_a") or post.get("reposteo_a")
            citado = self._p_repo.get_post(str(citado_id)) if citado_id else None
            # Si el citado no fue muestreado, el propio citador trae una copia
            # de lo que cita: sin esto, la mayoría de las citas se clasifican
            # con el texto citado en blanco.
            embebido = post.get("cita_embebida")
            if citado is not None:
                evidencia = "en_corpus"
                texto_citado = str(citado.get("texto") or "")
                autor_citado = str(citado.get("autor_handle") or "?")
            elif isinstance(embebido, dict):
                evidencia = "embebida"
                texto_citado = embebido["texto"]
                autor_citado = embebido["autor_handle"]
            else:
                evidencia = "ausente"
                texto_citado = "(no capturado)"
                autor_citado = "?"
            # Las emociones solo existen para lo que es unidad del corpus: una
            # copia embebida no pasó por la stage `emotions`.
            emociones_citadas = ""
            if citado is not None and self._emociones is not None:
                emociones_citadas = self._emociones(str(citado["post_id"])) or ""
            rows.append(
                {
                    "codigo": str(post["post_id"]),
                    "unit_idx": 0,
                    "texto": str(post.get("texto") or ""),
                    "autor": str(post.get("autor_handle") or "?"),
                    "operatoria": "cita" if post.get("cita_a") else "repost_comentado",
                    "texto_citado": texto_citado,
                    "autor_citado": autor_citado,
                    "emociones_citadas": emociones_citadas,
                    # Sobre qué se clasificó, dicho por el código y no inferido:
                    # el análisis puede filtrar o ponderar por calidad de
                    # evidencia en vez de tratar todas las citas por igual.
                    "evidencia_citada": evidencia,
                }
            )

        logger.info(f"[Stage:{self.NAME}] Procesando {len(rows)} post(s) citadores.")
        agent = ReframingAgent(
            self._backend,
            heuristicas=self._heuristicas,
            retry_config=self._retry_config,
            genre=self._genre,
        )
        df_in = pd.DataFrame(rows)
        self.progress.start(len(rows), "posts")
        agent.on_progress = self.progress.advance
        try:
            df_out = agent.run(df_in)
        except Exception as e:
            logger.error(f"[Stage:{self.NAME}] Error inesperado: {e}")
            for r in rows:
                self._p_repo.set_reframing_error(r["codigo"], str(e))
                self.metrics.record_item_failed()
            return 0

        total_ok = 0
        for _, row in df_out.iterrows():
            post_id = str(row["codigo"])
            raw = row.get("reframing")
            payload = _parse_json_cell(raw)
            if payload is None:
                # El agente deja el motivo en su columna reservada cuando
                # rechaza un batch: sin esto el estado del run dice "backend
                # error" para cualquier causa y no se sabe qué reintentar.
                motivo = str(row.get(agent.ERROR_COLUMN) or "Backend error (ver logs del agente)")
                self._p_repo.set_reframing_error(post_id, motivo)
                self.metrics.record_item_failed()
                continue
            payload["evidencia_citada"] = str(row.get("evidencia_citada") or "ausente")
            self._p_repo.set_reframing(post_id, payload, version=self._version)
            total_ok += 1
            self.metrics.record_item_ok()

        logger.info(f"[Stage:{self.NAME}] Completado: {total_ok} post(s) ok.")
        return total_ok


# ══════════════════════════════════════════════════════════════════════════════
#  Etapa de afecto de emojis (híbrida: léxico primero, LLM para ambiguos)
# ══════════════════════════════════════════════════════════════════════════════


class EmojiAffectStage(Stage):
    """Resuelve la contribución afectiva de los emojis del corpus.

    Híbrida al estilo de `modalidad`: el léxico de emojis resuelve sin LLM
    los usos inequívocos; los ambiguos (o no cubiertos) van al agente en
    batch, si hay backend configurado. Sin backend, degrada a léxico-only.
    El resultado se registra en `tecno_entidades.extra['afecto']`.
    """

    NAME = "emoji_affect"

    def __init__(
        self,
        tecno_repo: TecnoRepository,
        emoji_lexicon: dict[str, Any] | None = None,
        backend: LLMBackend | None = None,
        heuristicas: str | None = None,
        agent_version: str | None = None,
        retry_config: RetryConfig | None = None,
        genre: Genre | None = None,
    ) -> None:
        super().__init__()
        self._t_repo = tecno_repo
        self._lexicon = (emoji_lexicon or {}).get("emojis", {})
        self._backend = backend
        self._heuristicas = heuristicas
        self._version = agent_version
        self._retry_config = retry_config
        self._genre = genre

    def run_pending(self) -> int:
        """Resuelve los usos de emoji pendientes (léxico y, si hay, LLM)."""
        pendientes = self._scope_records(self._t_repo.list_emojis_sin_afecto())
        if not pendientes:
            logger.info(f"[Stage:{self.NAME}] Nada pendiente.")
            return 0

        # La unidad de análisis es la racha, no la ocurrencia: 🤣🤣🤣 es un
        # gesto intensificado y se resuelve una vez. Dos rachas del mismo
        # emoji en el mismo post siguen siendo dos usos independientes.
        rachas = agrupar_rachas(pendientes)
        logger.info(f"[Stage:{self.NAME}] {len(pendientes)} uso(s) en {len(rachas)} racha(s).")

        resueltos = 0
        ambiguas: list[Racha] = []
        # El progreso mide rachas (el trabajo real); las métricas siguen
        # contando entidades, que es la unidad del estado del run.
        self.progress.start(len(rachas), "rachas de emoji")
        for racha in rachas:
            self.progress.advance()
            afecto = resolve_emoji_afecto(self._lexicon, racha.emoji)
            if afecto is None:
                ambiguas.append(racha)
                continue
            resueltos += self._persistir(racha, afecto)
        self.progress.finish()

        logger.info(
            f"[Stage:{self.NAME}] Léxico: {resueltos} uso(s) resueltos, "
            f"{len(ambiguas)} racha(s) ambigua(s)."
        )
        if not ambiguas:
            return resueltos
        if self._backend is None:
            logger.info(
                f"[Stage:{self.NAME}] Sin backend configurado: las ambiguas "
                "quedan sin resolver (léxico-only)."
            )
            return resueltos

        resueltos += self._resolver_con_llm(ambiguas)
        return resueltos

    def _persistir(self, racha: Racha, afecto: dict[str, Any]) -> int:
        """Anota el afecto de la racha en cada una de sus ocurrencias."""
        for orden, uso in enumerate(racha.usos):
            self._t_repo.set_extra_keys(
                int(uso["id"]),
                {
                    "afecto": afecto,
                    "repeticion": payload_repeticion(racha, orden),
                },
            )
            self.metrics.record_item_ok()
        return racha.n

    def _marcar_error(self, racha: Racha, motivo: str) -> None:
        """Registra el motivo del fallo en cada ocurrencia de la racha."""
        for uso in racha.usos:
            if motivo:
                self._t_repo.set_extra_key(int(uso["id"]), "afecto_error", motivo[:300])
            self.metrics.record_item_failed()

    def _resolver_con_llm(self, rachas: list[Racha]) -> int:
        """Desambigua en contexto con el agente batch, una fila por racha."""
        from emoparse.agents.emoji_affect import EmojiAffectAgent

        rows = []
        for idx, racha in enumerate(rachas):
            prior = self._lexicon.get(racha.emoji)
            prior_str = ""
            if isinstance(prior, dict):
                cands = "/".join(prior.get("candidatos", []))
                prior_str = f"candidatos: {cands}; foria: {prior.get('foria')}"
            rows.append(
                {
                    "codigo": racha.codigo,
                    "unit_idx": racha.unit_idx,
                    "racha_idx": idx,
                    "emoji": racha.emoji,
                    "repeticiones": racha.n,
                    # El post va con la racha delimitada: sin la marca, dos usos
                    # del mismo emoji en el mismo post son unidades idénticas.
                    "frase": marcar_racha(racha.frase, racha.inicio, racha.fin),
                    "prior": prior_str,
                }
            )
        agent = EmojiAffectAgent(
            self._backend,
            heuristicas=self._heuristicas,
            retry_config=self._retry_config,
            genre=self._genre,
        )
        self.progress.start(len(rows), "rachas ambiguas")
        agent.on_progress = self.progress.advance
        try:
            df_out = agent.run(pd.DataFrame(rows))
        except Exception as e:
            logger.error(f"[Stage:{self.NAME}] Error inesperado: {e}")
            for racha in rachas:
                self._marcar_error(racha, str(e))
            return 0
        finally:
            self.progress.finish()

        ok = 0
        for _, row in df_out.iterrows():
            racha = rachas[int(row["racha_idx"])]
            payload = _parse_json_cell(row.get("afecto"))
            if payload is None:
                # Un batch rechazado deja el motivo en la fila: se persiste
                # junto a la entidad para que el estado del run lo cuente
                # como error y no como algo que nunca se intentó.
                self._marcar_error(racha, str(row.get(agent.ERROR_COLUMN) or ""))
                continue
            payload["origin"] = "llm"
            payload["version"] = self._version
            ok += self._persistir(racha, payload)
        logger.info(f"[Stage:{self.NAME}] LLM: {ok} uso(s) resueltos.")
        return ok


# ══════════════════════════════════════════════════════════════════════════════
#  Etapa de semiótica de hashtags (nivel corpus)
# ══════════════════════════════════════════════════════════════════════════════


class HashtagSemioticsStage(Stage):
    """Caracteriza los hashtags frecuentes del corpus con muestras de uso."""

    NAME = "hashtag_semiotics"

    def __init__(
        self,
        backend: LLMBackend,
        tecno_repo: TecnoRepository,
        hashtags_repo: HashtagsRepository,
        min_usos: int = 1,
        heuristicas: str | None = None,
        agent_version: str | None = None,
        retry_config: RetryConfig | None = None,
        genre: Genre | None = None,
    ) -> None:
        super().__init__()
        self._backend = backend
        self._t_repo = tecno_repo
        self._h_repo = hashtags_repo
        self._min_usos = min_usos
        self._heuristicas = heuristicas
        self._version = agent_version
        self._retry_config = retry_config
        self._genre = genre

    def run_pending(self) -> int:
        """Analiza los usos pendientes y agrega la caracterización por hashtag.

        Un hashtag no funciona siempre igual: el análisis es por uso (cada
        post donde aparece), con las funciones ya identificadas del mismo
        hashtag como contexto creciente entre batches (economiza la
        re-derivación de la tipología). La fila de la tabla `hashtags` se
        deriva por agregación de los usos, sin un pase LLM adicional.
        """
        from emoparse.agents.hashtag_semiotics import HashtagSemioticsAgent

        counts = self._t_repo.top_valores("hashtag", limit=10_000)
        if counts:
            self._h_repo.sync_counts(counts)
        # Un hashtag de un solo uso también funciona en ese post: la
        # caracterización a nivel corpus se deriva por agregación, así que
        # dejarlo afuera pierde el uso, no solo el promedio.
        candidatos = [(v, n) for v, n in counts if n >= self._min_usos]
        if not candidatos:
            logger.info(f"[Stage:{self.NAME}] Nada pendiente.")
            return 0

        agent = HashtagSemioticsAgent(
            self._backend,
            heuristicas=self._heuristicas,
            retry_config=self._retry_config,
            genre=self._genre,
        )
        total_ok = 0
        analizados = 0
        for valor_norm, n_usos in self.progress.track(candidatos, "hashtags"):
            usos = self._t_repo.list_usos_hashtag_sin_funcion(valor_norm)
            if not usos:
                continue
            analizados += 1
            previos = self._t_repo.analisis_usos_hashtag(valor_norm)
            funciones = Counter(
                str(p.get("funcion") or "").strip()
                for p in previos
                if str(p.get("funcion") or "").strip()
            )
            error: str | None = None
            for start in range(0, len(usos), agent.BATCH_SIZE):
                chunk = usos[start : start + agent.BATCH_SIZE]
                rows = [
                    {
                        "codigo": str(u["codigo"]),
                        "unit_idx": int(u["unit_idx"]),
                        "entidad_id": int(u["id"]),
                        "hashtag": valor_norm,
                        "n_usos": int(n_usos),
                        "uso_texto": str(u.get("frase") or ""),
                        "funciones_previas": _format_funciones(funciones),
                    }
                    for u in chunk
                ]
                try:
                    df_out = agent.run(pd.DataFrame(rows))
                except Exception as e:
                    error = str(e)
                    break
                for _, row in df_out.iterrows():
                    payload = _parse_json_cell(row.get("analisis"))
                    if payload is None:
                        self.metrics.record_item_failed()
                        continue
                    self._t_repo.set_extra_key(int(row["entidad_id"]), "funcion", payload)
                    f = str(payload.get("funcion") or "").strip()
                    if f:
                        funciones[f] += 1
                    total_ok += 1
                    self.metrics.record_item_ok()
            if error is not None:
                logger.error(f"[Stage:{self.NAME}] #{valor_norm}: error inesperado: {error}")
                self._h_repo.set_analisis_error(valor_norm, error)
                self.metrics.record_item_failed()
                continue
            todos = self._t_repo.analisis_usos_hashtag(valor_norm)
            if todos:
                self._h_repo.set_analisis(
                    valor_norm,
                    _agregar_analisis_hashtag(todos),
                    version=self._version,
                )

        logger.info(
            f"[Stage:{self.NAME}] Completado: {total_ok} uso(s) analizados "
            f"en {analizados} hashtag(s) (umbral: {self._min_usos} usos)."
        )
        return total_ok


def _format_funciones(funciones: Counter[str]) -> str:
    """Formatea el conteo de funciones ya identificadas para el prompt."""
    if not funciones:
        return ""
    return "\n".join(f"- {f} ({n})" for f, n in funciones.most_common())


def _agregar_analisis_hashtag(usos: list[dict[str, Any]]) -> dict[str, Any]:
    """Deriva la caracterización a nivel corpus desde los análisis por uso.

    Función dominante: la moda si concentra al menos la mitad de los usos;
    'mixto' si no hay dominante clara. El acoplamiento representativo se toma
    de los usos de la función dominante; con función mixta se marca como
    heterogéneo. El payload conserva la distribución completa para la UI.
    """
    funciones: Counter = Counter()
    forias: Counter = Counter()
    for u in usos:
        f = str(u.get("funcion") or "").strip()
        if f:
            funciones[f] += 1
        fo = str(u.get("foria_entorno") or "").strip()
        if fo:
            forias[fo] += 1
    total = sum(funciones.values())
    if total:
        dominante, n_dom = funciones.most_common(1)[0]
        funcion = dominante if n_dom * 2 >= total or len(funciones) == 1 else "mixto"
    else:
        funcion, dominante = "mixto", ""
    foria = forias.most_common(1)[0][0] if forias else "indeterminado"

    if funcion == "mixto":
        acoplamiento = "heterogéneo (ver usos)"
    else:
        acoplamiento = "sin acoplamiento discernible"
        for u in usos:
            if str(u.get("funcion") or "").strip() != dominante:
                continue
            a = str(u.get("acoplamiento") or "").strip()
            if a and a.lower() != "sin acoplamiento discernible":
                acoplamiento = a
                break
    dist = ", ".join(f"{f} ({n})" for f, n in funciones.most_common())
    justificacion = (
        f"Derivada de {total} uso(s) analizados. Funciones: {dist}."
        if total
        else "Sin usos analizados."
    )
    return {
        "modo": "agregado_por_uso",
        "n_usos_analizados": total,
        "funciones": dict(funciones),
        "forias": dict(forias),
        "funcion": funcion,
        "acoplamiento": acoplamiento,
        "foria_entorno": foria,
        "justificacion": justificacion,
    }


class TecnoUsageStage(Stage):
    """Caracteriza el uso en contexto de menciones, tecnografismos y URLs.

    Opera a nivel unidad (post): junta cada post con sus menciones,
    tecnografismos y URLs pendientes y los procesa en batches. El resultado se
    registra por entidad en `tecno_entidades.extra['uso']`.
    """

    NAME = "tecno_usage"

    def __init__(
        self,
        backend: LLMBackend,
        tecno_repo: TecnoRepository,
        heuristicas: str | None = None,
        agent_version: str | None = None,
        retry_config: RetryConfig | None = None,
        genre: Genre | None = None,
    ) -> None:
        super().__init__()
        self._backend = backend
        self._t_repo = tecno_repo
        self._heuristicas = heuristicas
        self._version = agent_version
        self._retry_config = retry_config
        self._genre = genre

    def run_pending(self) -> int:
        """Analiza las unidades con menciones/tecnografismos pendientes."""
        from emoparse.agents.tecno_usage import TecnoUsageAgent

        unidades = self._scope_records(self._t_repo.list_unidades_con_tecno_sin_uso())
        if not unidades:
            logger.info(f"[Stage:{self.NAME}] Nada pendiente.")
            return 0

        rows = []
        for u in unidades:
            lineas = []
            for e in u["entidades"]:
                extra = e.get("extra") or {}
                tipo = str(e["tipo"])
                if tipo == "url":
                    dominio = str(e.get("valor_norm") or "").strip()
                    attr = f"dominio: {dominio}" if dominio else ""
                else:
                    attr = str(extra.get("posicion") or extra.get("subtipo") or "")
                lineas.append(f"- {e['valor']} ({tipo}" + (f", {attr})" if attr else ")"))
            rows.append(
                {
                    "codigo": u["codigo"],
                    "unit_idx": int(u["unit_idx"]),
                    "uso_texto": u["frase"],
                    "entidades_txt": "\n".join(lineas),
                }
            )

        logger.info(
            f"[Stage:{self.NAME}] Procesando {len(rows)} unidad(es) con "
            "menciones, tecnografismos o URLs."
        )
        agent = TecnoUsageAgent(
            self._backend,
            heuristicas=self._heuristicas,
            retry_config=self._retry_config,
            genre=self._genre,
        )
        self.progress.start(len(rows), "posts")
        agent.on_progress = self.progress.advance
        try:
            df_out = agent.run(pd.DataFrame(rows))
        except Exception as e:
            logger.error(f"[Stage:{self.NAME}] Error inesperado: {e}")
            for _ in rows:
                self.metrics.record_item_failed()
            return 0
        finally:
            self.progress.finish()

        por_unidad = {(u["codigo"], int(u["unit_idx"])): list(u["entidades"]) for u in unidades}
        total_ok = 0
        for _, row in df_out.iterrows():
            usos = _parse_json_list_cell(row.get("usos"))
            if usos is None:
                self.metrics.record_item_failed()
                continue
            entidades = por_unidad.get((str(row["codigo"]), int(row["unit_idx"])), [])
            asignados: set[int] = set()
            for uso in usos:
                if not isinstance(uso, dict):
                    continue
                ent = _match_entidad(str(uso.get("valor") or ""), entidades, asignados)
                if ent is None:
                    continue
                self._t_repo.set_extra_key(
                    int(ent["id"]),
                    "uso",
                    {
                        "uso": uso.get("uso"),
                        "justificacion": uso.get("justificacion"),
                    },
                )
                asignados.add(int(ent["id"]))
            total_ok += 1
            self.metrics.record_item_ok()

        logger.info(f"[Stage:{self.NAME}] Completado: {total_ok} unidad(es) ok.")
        return total_ok


def _match_entidad(
    valor: str,
    entidades: list[dict[str, Any]],
    asignados: set[int],
) -> dict[str, Any] | None:
    """Encuentra la entidad de la unidad correspondiente a un valor devuelto.

    Match exacto primero; casefold como fallback (los modelos a veces
    normalizan mayúsculas). Nunca reasigna una entidad ya asignada.
    """
    valor = valor.strip()
    if not valor:
        return None
    for e in entidades:
        if int(e["id"]) not in asignados and str(e["valor"]) == valor:
            return e
    vf = valor.casefold()
    for e in entidades:
        if int(e["id"]) not in asignados and str(e["valor"]).casefold() == vf:
            return e
    return None


def _parse_json_list_cell(raw: Any) -> list[Any] | None:
    """Parsea una celda JSON de lista (None si falta o es ilegible)."""
    if raw is None or (isinstance(raw, float) and pd.isna(raw)):
        return None
    if isinstance(raw, list):
        return raw
    try:
        parsed = json.loads(str(raw))
    except (json.JSONDecodeError, TypeError):
        return None
    return parsed if isinstance(parsed, list) else None


def _parse_json_cell(raw: Any) -> dict[str, Any] | None:
    """Parsea una celda JSON de salida de agente (None si falta o es ilegible)."""
    if raw is None or (isinstance(raw, float) and pd.isna(raw)):
        return None
    if isinstance(raw, dict):
        return raw
    try:
        parsed = json.loads(str(raw))
    except (json.JSONDecodeError, TypeError):
        return None
    return parsed if isinstance(parsed, dict) else None


# ══════════════════════════════════════════════════════════════════════════════
#  Etapa de descripción multimodal (vision_describe)
# ══════════════════════════════════════════════════════════════════════════════


class VisionDescribeStage(Stage):
    """Describe las imágenes adjuntas a posts con un modelo de visión.

    Llama al backend directamente (una imagen por request; los VLM no
    baten bien imágenes en batch) con schema estricto `VisionSchema`.
    Requiere un backend multimodal: llama_server lanzado con --mmproj.
    La descripción se persiste en `media` y alimenta como contexto a las
    stages de análisis emocional (el post se analiza como enunciado
    compuesto texto+imagen).
    """

    NAME = "vision_describe"

    def __init__(
        self,
        backend: LLMBackend,
        posts_repo: PostsRepository,
        agent_version: str | None = None,
        genre: Genre | None = None,
    ) -> None:
        super().__init__()
        self._backend = backend
        self._p_repo = posts_repo
        self._version = agent_version
        self._genre = genre

    def run_pending(self) -> int:
        """Describe los adjuntos pendientes."""
        from emoparse.core.prompts import vision_describe as prompts
        from emoparse.core.schemas import VisionSchema

        pendientes = self._scope_records(
            self._p_repo.list_media_pending_descripcion(), key="post_id"
        )
        if not pendientes:
            logger.info(f"[Stage:{self.NAME}] Nada pendiente.")
            return 0
        system = prompts.render_system()
        total_ok = 0
        for media in self.progress.track(pendientes, "imágenes"):
            media_id = int(media["id"])
            imagen = media.get("path_local") or media.get("url")
            user = prompts.render_user(
                texto_post=str(media.get("post_texto") or ""),
                alt_text=media.get("alt_text") or None,
            )
            try:
                response = self._backend.generate(
                    system=system,
                    user=user,
                    schema=VisionSchema,
                    images=[str(imagen)],
                )
            except Exception as e:
                logger.error(f"[Stage:{self.NAME}] media {media_id}: {e}")
                self._p_repo.set_media_descripcion_error(media_id, str(e))
                self.metrics.record_item_failed()
                continue
            if response.parsed is None:
                self._p_repo.set_media_descripcion_error(media_id, "Respuesta sin payload parseado")
                self.metrics.record_item_failed()
                continue
            self._p_repo.set_media_descripcion(
                media_id, response.parsed.model_dump(), version=self._version
            )
            total_ok += 1
            self.metrics.record_item_ok()

        logger.info(f"[Stage:{self.NAME}] Completado: {total_ok} imagen(es) ok.")
        return total_ok


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
        codigos = self._scope_codes(
            [c for c in self._d_repo.list_codigos() if not self._m_repo.has_deixis_llm(c)]
        )
        if not codigos:
            logger.info(f"[Stage:{self.NAME}] Nada pendiente.")
            return 0

        total = 0
        for codigo in self.progress.track(codigos, "discursos"):
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
        df_in = pd.DataFrame(
            [
                {
                    "codigo": codigo,
                    "marcas": "\n".join(f"- {m}" for m in marcas_unicas[i : i + n]),
                }
                for i in range(0, len(marcas_unicas), n)
            ]
        )

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
        "designacion",
        "referencia_gramatical",
        "identificacion_inferencial",
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
        codigos = self._scope_codes(self._d_repo.list_codigos())
        for codigo in self.progress.track(codigos, "discursos"):
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
                self._m_repo.set_modalidad(key[0], key[1], g.modalidad, g.naturaleza, "nlp")
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
                self._m_repo.set_modalidad(key[0], key[1], g.modalidad, g.naturaleza, "nlp")
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
                    for c in items[i : i + n]
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
    """Mapea texto libre del LLM a un canónico mediante el catálogo ex post.

    El catálogo no participa en la detección ni en ningún prompt. Opera sobre
    filas de ``emociones`` ya persistidas; si una etiqueta no está cubierta,
    deja ``tipo_emocion_canonico`` en NULL (sin error).

    Stage determinística, sin LLM, idempotente: re-ejecutar solo procesa
    las filas aún pendientes.
    """

    NAME = "normalize_emotions"

    def __init__(
        self,
        emociones_repo: EmocionesRepository,
        normalization_catalog: dict[str, Any],
        agent_version: str | None = None,
    ) -> None:
        super().__init__()
        self.validate_contracts = False  # no hay DataFrame en esta stage
        self._repo = emociones_repo
        self._lookup = build_emotion_normalization_lookup(normalization_catalog)
        self._version = agent_version

    def run_pending(self) -> int:
        """Normaliza emociones pendientes y devuelve el total procesado."""
        pending = self._scope_tuples(self._repo.list_pending_normalization())
        if not pending:
            logger.info(f"[Stage:{self.NAME}] Nada pendiente.")
            return 0

        for codigo, frase_idx, emocion_idx in self.progress.track(pending, "emociones"):
            row = self._repo.get_emocion(codigo, frase_idx, emocion_idx)
            if row is None:
                continue
            tipo_raw = row.get("tipo_emocion") or ""
            canonico = self._lookup.get(tipo_raw.lower().strip())
            self._repo.set_normalized_emotion(
                codigo,
                frase_idx,
                emocion_idx,
                tipo_emocion_canonico=canonico,  # None si no matchea → queda NULL
                version=self._version,
            )
            self.metrics.record_item_ok()

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
        pending = self._scope_tuples(self._e_repo.list_pending_caracterizacion())
        if not pending:
            logger.info(f"[Stage:{self.NAME}] Nada pendiente.")
            return 0

        by_codigo: dict[str, list[tuple[int, int]]] = {}
        for codigo, frase_idx, emo_idx in pending:
            by_codigo.setdefault(codigo, []).append((frase_idx, emo_idx))

        total_ok = 0
        self.progress.start(len(pending), "emociones")
        for codigo, items in by_codigo.items():
            self.progress.advance(len(items))
            input_data = self._d_repo.get_input(codigo) or {}
            meta = self._d_repo.get_payload(codigo, "metadata") or {}
            enun = self._d_repo.get_payload(codigo, "enunciation") or {}
            agent = CharacterizerAgent(
                self._backend,
                titulo=str(input_data.get("titulo", "")),
                tipo_discurso=str(meta.get("tipo_discurso", "")),
                enunciador=str(enun.get("enunciador", "")),
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
                logger.error(f"[Stage:{self.NAME}] {codigo}: error inesperado: {e}")
                for frase_idx, emo_idx in items:
                    self._e_repo.set_caracterizacion_error(codigo, frase_idx, emo_idx, str(e))
                    self.metrics.record_item_failed()
                continue

            for _, row in df_out.iterrows():
                payload = self._extract_payload(row)
                frase_idx = int(row["frase_idx"])
                emo_idx = int(row["emocion_idx"])
                if payload is None:
                    self._e_repo.set_caracterizacion_error(
                        codigo,
                        frase_idx,
                        emo_idx,
                        "Backend error (ver logs)",
                    )
                    self.metrics.record_item_failed()
                    continue
                self._e_repo.set_caracterizacion(
                    codigo,
                    frase_idx,
                    emo_idx,
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
        fte_map = self._e_repo.resolve_canonicos_map(codigo, "fuente", "fuente_marca")
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

    #: Discursos procesados en simultáneo. Lo fija el runner según
    #: `pipeline.parallel` y el tipo de backend; 1 = secuencial (in-process).
    parallel: int = 1

    def __init__(
        self,
        backend: LLMBackend,
        discursos_repo: DiscursosRepository,
        frases_repo: FrasesRepository,
        heuristicas: str,
        configuraciones: str = "",
        modos_existencia: str = "",
        rolling_window: int = 3,
        context_mode: Literal["rolling", "full"] = "rolling",
        # "full" da más contexto de continuidad para detectar escaladas, a costa de prompt más largo
        emotion_scope: tuple[str, ...] | None = None,
        agent_version: str | None = None,
        retry_config: RetryConfig | None = None,
        genre: Genre | None = None,
        hilo_emotion_context_provider: Callable[[str], str | None] | None = None,
        hilo_context_provider: Callable[[str], str | None] | None = None,
        tecno_context_provider: Callable[[str, int], str | None] | None = None,
        media_context_provider: Callable[[str], str | None] | None = None,
    ) -> None:
        super().__init__()
        self._backend = backend
        self._d_repo = discursos_repo
        self._f_repo = frases_repo
        self._heuristicas = heuristicas
        self._configuraciones = configuraciones
        self._modos_existencia = modos_existencia
        self._rolling_window = rolling_window
        self._context_mode = context_mode
        self._emotion_scope = tuple(emotion_scope) if emotion_scope else None
        self._version = agent_version
        self._retry_config = retry_config
        self._genre = genre
        # Provider opcional para géneros conversacionales (context_unit
        # 'hilo'): emociones que el pase 1 detectó en los posts padre,
        # inyectadas en `emotion_rolling` (con una frase por discurso, el
        # rolling intra-discurso es vacío).
        self._hilo_emotion_ctx = hilo_emotion_context_provider
        # Mismos providers de contexto que el pase 1 (texto del hilo,
        # tecnolingüísticos, media): el explode prioriza el pase 2, así que
        # este tiene que ver al menos el mismo contexto de desambiguación
        # que el pase 1 para no deshacer sus desambiguaciones.
        self._hilo_ctx = hilo_context_provider
        self._tecno_ctx = tecno_context_provider
        self._media_ctx = media_context_provider
        # Persistencia bajo lock cuando se procesa en paralelo por discurso.
        self._persist_lock = threading.Lock()

    def run_pending(self) -> int:
        """Procesa frases pendientes con rolling/full summary.

        Paraleliza por discurso cuando `self.parallel > 1` (que el runner fija
        según `pipeline.parallel` y el tipo de backend), con la misma
        semántica que el pase 1: un agente por discurso, persistencia bajo
        lock. Con backend in-process el runner lo deja en 1.
        """
        all_pending = self._scope_tuples(
            self._f_repo.list_pending(self.STAGE_KEY)  # type: ignore[arg-type]
        )
        if not all_pending:
            logger.info(f"[Stage:{self.NAME}] Nada pendiente.")
            return 0

        by_codigo: dict[str, list[int]] = {}
        for codigo, unit_idx in all_pending:
            by_codigo.setdefault(codigo, []).append(unit_idx)

        logger.info(
            f"[Stage:{self.NAME}] Procesando {len(by_codigo)} discurso(s) "
            f"con {sum(len(v) for v in by_codigo.values())} frases pendientes"
            + (f" (parallel={self.parallel})." if self.parallel > 1 else ".")
        )

        total_ok = 0
        self.progress.start(sum(len(v) for v in by_codigo.values()), "frases")
        if self.parallel <= 1:
            for codigo, pending_idxs in by_codigo.items():
                total_ok += self._process_codigo(codigo, pending_idxs)
        else:
            with ThreadPoolExecutor(max_workers=self.parallel) as pool:
                futures = {
                    pool.submit(self._process_codigo, codigo, idxs): codigo
                    for codigo, idxs in by_codigo.items()
                }
                for future in as_completed(futures):
                    total_ok += future.result()
        self.progress.finish()

        logger.info(f"[Stage:{self.NAME}] Completado: {total_ok} frases ok.")
        return total_ok

    def _process_codigo(self, codigo: str, pending_idxs: list[int]) -> int:
        """Corre el pase 2 sobre las frases pendientes de un discurso."""
        input_data = self._d_repo.get_input(codigo) or {}

        df_full = self._build_full_df_with_rolling(codigo)
        if df_full.empty:
            logger.info(f"[Stage:{self.NAME}] {codigo}: sin pase 1 procesado, salteando")
            return 0

        df_pending = df_full[df_full["unit_idx"].isin(pending_idxs)].reset_index(drop=True)
        if df_pending.empty:
            return 0
        self._validate(FraseConEmocionesContract, df_pending, "entrada")

        meta = self._d_repo.get_payload(codigo, "metadata") or {}
        enun = self._d_repo.get_payload(codigo, "enunciation") or {}
        summ = self._d_repo.get_payload(codigo, "summarizer") or {}
        agent = EmotionsAgentPass2(
            self._backend,
            heuristicas=self._heuristicas,
            configuraciones=self._configuraciones,
            titulo=str(input_data.get("titulo", "")),
            tipo_discurso=str(meta.get("tipo_discurso", "")),
            enunciador=str(enun.get("enunciador", "")),
            enunciatarios=_format_enunciatarios(enun.get("enunciatarios")),
            auditorio=_format_enunciatarios(enun.get("auditorio")),
            resumen=_resumen_global(summ),
            modos_existencia=self._modos_existencia,
            emotion_scope=self._emotion_scope,
            context_mode=self._context_mode,
            retry_config=self._retry_config,
            genre=self._genre,
        )

        try:
            df_out = agent.run(df_pending)
        except Exception as e:
            logger.error(f"[Stage:{self.NAME}] {codigo}: error inesperado: {e}")
            with self._persist_lock:
                for idx in pending_idxs:
                    self._f_repo.set_error(
                        codigo,
                        idx,
                        self.STAGE_KEY,
                        str(e),  # type: ignore[arg-type]
                    )
                    self.metrics.record_item_failed()
            return 0

        total_ok = 0
        with self._persist_lock:
            for _, row in df_out.iterrows():
                idx = int(row["unit_idx"])
                emociones_str = row.get("emociones")
                if pd.isna(emociones_str):
                    self._f_repo.set_error(
                        codigo,
                        idx,
                        self.STAGE_KEY,  # type: ignore[arg-type]
                        "Backend error (ver logs del agente)",
                    )
                    self.metrics.record_item_failed()
                    continue
                try:
                    payload = json.loads(emociones_str)
                except (json.JSONDecodeError, TypeError):
                    self._f_repo.set_error(
                        codigo,
                        idx,
                        self.STAGE_KEY,  # type: ignore[arg-type]
                        "Output del agente no parseable como JSON",
                    )
                    self.metrics.record_item_failed()
                    continue
                self._f_repo.set_payload(
                    codigo,
                    idx,
                    self.STAGE_KEY,  # type: ignore[arg-type]
                    payload,
                    version=self._version,
                )
                total_ok += 1
                self.metrics.record_item_ok()
        return total_ok

    def _build_full_df_with_rolling(self, codigo: str) -> pd.DataFrame:
        """Construye DataFrame con frases, rolling summary y contexto opcional."""
        all_frases = self._f_repo.list_frases_of_discurso(codigo)
        if not all_frases:
            return pd.DataFrame()

        contexto_hilo = self._hilo_ctx(codigo) if self._hilo_ctx else None
        media_desc = self._media_ctx(codigo) if self._media_ctx else None
        rows: list[dict[str, Any]] = []
        any_pass1 = False
        for unit_idx, frase in all_frases:
            emos_pass1 = self._f_repo.get_payload(codigo, unit_idx, "emociones")
            actores = self._f_repo.get_payload(codigo, unit_idx, "actores")
            if emos_pass1 is not None:
                any_pass1 = True

            row: dict[str, Any] = {
                "codigo": codigo,
                "unit_idx": unit_idx,
                "frase": frase,
                # `emociones` tiene que ser JSON string para que su parser
                # interno funcione.
                "emociones": (
                    json.dumps(emos_pass1, ensure_ascii=False) if emos_pass1 is not None else None
                ),
                "actores": (
                    json.dumps(actores, ensure_ascii=False) if actores is not None else None
                ),
            }
            if contexto_hilo:
                row["contexto_hilo"] = contexto_hilo
            if self._tecno_ctx is not None:
                tecno = self._tecno_ctx(codigo, unit_idx)
                if tecno:
                    row["tecno"] = tecno
            if media_desc:
                row["media_desc"] = media_desc
            rows.append(row)

        if not any_pass1:
            return pd.DataFrame()

        df = pd.DataFrame(rows)
        if self._context_mode == "full":
            df = compute_emotion_full_summary(df)
        else:
            df = compute_emotion_rolling_summary(df, window=self._rolling_window)
        return self._merge_hilo_emotion_context(codigo, df)

    def _merge_hilo_emotion_context(self, codigo: str, df: pd.DataFrame) -> pd.DataFrame:
        """Antepone al rolling las emociones detectadas en los posts padre.

        Solo actúa si hay provider de hilo configurado y el post tiene
        padres con emociones del pase 1. Cuando el rolling intra-discurso es
        el placeholder vacío (caso típico del género tuit: una frase por
        discurso), lo reemplaza; si trae contenido, lo conserva a
        continuación del contexto del hilo.
        """
        if self._hilo_emotion_ctx is None or df.empty:
            return df
        ctx = self._hilo_emotion_ctx(codigo)
        if not ctx:
            return df

        def _merge(valor: Any) -> str:
            s = (
                ""
                if valor is None or (isinstance(valor, float) and pd.isna(valor))
                else str(valor).strip()
            )
            if not s or s.startswith("(sin emociones previas"):
                return ctx
            return f"{ctx}\n{s}"

        df = df.copy()
        df["emotion_rolling"] = df["emotion_rolling"].map(_merge)
        return df


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
        pending = self._scope_tuples(self._e_repo.list_pending_actantes())
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
        self.progress.start(len(pending), "emociones")
        for codigo, items in by_codigo.items():
            self.progress.advance(len(items))
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
                logger.error(f"[Stage:{self.NAME}] {codigo}: error inesperado: {e}")
                for frase_idx, emo_idx in items:
                    self._e_repo.set_actantes_error(codigo, frase_idx, emo_idx, str(e))
                    self.metrics.record_item_failed()
                continue

            for _, row in df_out.iterrows():
                payload = self._extract_payload(row)
                frase_idx = int(row["frase_idx"])
                emo_idx = int(row["emocion_idx"])
                if payload is None:
                    self._e_repo.set_actantes_error(
                        codigo,
                        frase_idx,
                        emo_idx,
                        "Backend error (ver logs)",
                    )
                    self.metrics.record_item_failed()
                    continue
                self._e_repo.set_actantes(
                    codigo,
                    frase_idx,
                    emo_idx,
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
        fte_map = self._e_repo.resolve_canonicos_map(codigo, "fuente", "fuente_marca")
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
    canon_map: dict[tuple[int, int], str] | None = None,
) -> str:
    """Experienciador efectivo para las stages downstream.

    Orden de preferencia: (1) ``experienciador_canonico`` por emoción (commit de
    la revisión o atribución por emoción); (2) el canónico resuelto desde las
    marcas ↔ referentes (`canon_map`), que refleja las ediciones de la tab
    Referentes; (3) el crudo ``experienciador``. Así la revisión humana propaga a
    characterizer/actants/judge sin que esas stages conozcan la KB ni el overlay.
    """
    canon = primer_canonico(emo.get("experienciador_canonico"))
    if canon:
        return canon
    resolved = _from_canon_map(emo, canon_map)
    return resolved or str(emo.get("experienciador", "") or "")


def _effective_fuente(
    emo: dict[str, Any],
    canon_map: dict[tuple[int, int], list[str]] | None = None,
) -> str:
    """Fuente efectiva para las stages downstream.

    Orden de preferencia: (1) ``fuente_canonico`` por emoción; (2) los
    canónicos resueltos desde las marcas ↔ referentes (refleja la tab
    Referentes); (3) el crudo ``fuente_inferencia``. A diferencia del
    experienciador, la fuente puede combinar entidades: se pasan todas.
    """
    canon = canonicos_de_override(emo.get("fuente_canonico"))
    if canon:
        return "; ".join(canon)
    resolved = _from_canonicos_map(emo, canon_map)
    return resolved or str(emo.get("fuente_inferencia", "") or "")


def _from_canonicos_map(
    emo: dict[str, Any],
    canon_map: dict[tuple[int, int], list[str]] | None,
) -> str:
    """Canónicos resueltos para la emoción, unidos, o '' si no hay."""
    if not canon_map:
        return ""
    try:
        key = (int(emo["frase_idx"]), int(emo["emocion_idx"]))
    except (KeyError, TypeError, ValueError):
        return ""
    return "; ".join(canon_map.get(key, []))


def _from_canon_map(
    emo: dict[str, Any],
    canon_map: dict[tuple[int, int], str] | None,
) -> str:
    """Canónico resuelto para la emoción, o '' si no hay.

    El mapa trae un referente por emoción: una emoción tiene un solo
    experienciador (y una sola fuente). Cuando una marca resuelve a varios
    referentes, el desdoblamiento (revisión, aceptación de deixis) materializa
    una emoción por referente antes de llegar acá.
    """
    if not canon_map:
        return ""
    try:
        key = (int(emo["frase_idx"]), int(emo["emocion_idx"]))
    except (KeyError, TypeError, ValueError):
        return ""
    return canon_map.get(key, "")


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
        agent_version: str | None = None,
        retry_config: RetryConfig | None = None,
        genre: Genre | None = None,
        hilo_context_provider: Callable[[str], str | None] | None = None,
        reframing_provider: Callable[[str], str | None] | None = None,
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
        # Para discurso nativo digital: la ventana previa del juez es la
        # conversación (posts padre + cita), donde viven el retome, el
        # discurso ajeno y la ironía que el juez detecta; el reframing (si
        # corrió) explicita la operación de recontextualización.
        self._hilo_ctx = hilo_context_provider
        self._reframing = reframing_provider

    def run_pending(self) -> int:
        """Procesa emociones caracterizadas y guarda veredictos."""
        pending = self._scope_tuples(self._j_repo.list_pending())
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
        self.progress.start(len(pending), "emociones")
        for codigo, items in by_codigo.items():
            self.progress.advance(len(items))
            input_data = self._d_repo.get_input(codigo) or {}
            meta = self._d_repo.get_payload(codigo, "metadata") or {}
            summ = self._d_repo.get_payload(codigo, "summarizer") or {}
            enun = self._d_repo.get_payload(codigo, "enunciation") or {}
            agent = JudgeAgent(
                self._backend,
                titulo=str(input_data.get("titulo", "")),
                tipo_discurso=str(meta.get("tipo_discurso", "")),
                heuristicas=self._heuristicas,
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
                logger.error(f"[Stage:{self.NAME}] {codigo}: error inesperado: {e}")
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
                        codigo,
                        frase_idx,
                        emo_idx,
                        "Backend error (ver logs del agente)",
                    )
                    self.metrics.record_item_failed()
                    continue
                sug = row.get("sugerencias")
                self._j_repo.set_judgment(
                    codigo,
                    frase_idx,
                    emo_idx,
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
        fte_map = self._e_repo.resolve_canonicos_map(codigo, "fuente", "fuente_marca")

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
            if self._hilo_ctx is not None:
                hilo = self._hilo_ctx(codigo)
                partes = [p for p in (hilo, prev_ctx) if p]
                if self._reframing is not None:
                    reframing_ctx = self._reframing(codigo)
                    if reframing_ctx:
                        partes.append(reframing_ctx)
                prev_ctx = "\n".join(partes)
            actantes = _parse_json_safe(emo.get("actantes_payload"))
            rows.append(
                {
                    **emo,
                    "frase": frase_text,
                    "ventana_previa": prev_ctx,
                    "ventana_posterior": post_ctx,
                    "experienciador": _effective_experiencer(emo, exp_map),
                    "fuente_inferencia": _effective_fuente(emo, fte_map),
                    # Del characterizer, el juez solo revisa la temporalidad.
                    "temporalidad": carac.get("temporalidad", ""),
                    "actantes_texto": _format_actantes_for_judge(actantes),
                }
            )
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
        """Propone semas para referentes aún no barridos por la stage."""
        ya = self._m_repo.canonicos_semas_procesados()
        codigos = set(self._selector_scope) if self._selector_scope is not None else None
        pendientes = [
            c for c in self._m_repo.list_canonicos(codigos=codigos) if c["canonical_id"] not in ya
        ]
        if not pendientes:
            logger.info(f"[Stage:{self.NAME}] Nada pendiente.")
            return 0

        allowed = _semas_allowed(self._vocab)
        vocab_str = _format_semas_vocabulario(self._vocab)
        df = pd.DataFrame(
            [
                {
                    "canonical_id": c["canonical_id"],
                    "display": c["canonical_id"],
                    "marcas": c["marcas"],
                }
                for c in pendientes
            ]
        )

        agent = SemasAgent(
            self._backend,
            vocab_str,
            titulo=self._titulo,
            tipo_discurso=self._tipo_discurso,
            retry_config=self._retry_config,
            genre=self._genre,
        )
        agent.on_progress = self.progress.advance
        self.progress.start(len(pendientes), "referentes")
        out = agent.run(df)
        self.progress.finish()

        total = 0
        for _, row in out.iterrows():
            canonical_id = str(row["canonical_id"])
            error = str(row.get("semas_error") or "").strip()
            if error:
                self._m_repo.mark_semas_processed(
                    canonical_id,
                    version=self._version,
                    error=error,
                )
                continue

            raw = row.get("semas")
            try:
                semas = json.loads(raw) if raw else []
            except (json.JSONDecodeError, TypeError):
                self._m_repo.mark_semas_processed(
                    canonical_id,
                    version=self._version,
                    error="salida de semas inválida",
                )
                continue
            if not isinstance(semas, list):
                self._m_repo.mark_semas_processed(
                    canonical_id,
                    version=self._version,
                    error="salida de semas no es una lista",
                )
                continue
            total += self._m_repo.propose_semas(
                canonical_id,
                [str(s) for s in semas],
                allowed=allowed,
                origin="llm",
            )
            self._m_repo.mark_semas_processed(
                canonical_id,
                version=self._version,
            )
        logger.info(f"[Stage:{self.NAME}] {len(pendientes)} referentes, {total} semas propuestos.")
        return total
