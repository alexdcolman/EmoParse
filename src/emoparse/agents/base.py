# ══════════════════════════════════════════════════════════════════════════════
#  emoparse.agents.base
#
#  Clases base para agentes LLM del pipeline.
#
#  BaseAgent:
#      procesa una fila por llamada al backend.
#
#  BaseBatchAgent:
#      procesa múltiples filas por llamada, correlacionando resultados
#      mediante `unit_idx`.
#
#  Ambas clases definen el flujo común de:
#      construir prompts, ejecutar generación estructurada, mapear la
#      respuesta a columnas del DataFrame y preservar filas fallidas
#      sin interrumpir el procesamiento.
# ══════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, ClassVar, Generic, TypeVar

import pandas as pd
from loguru import logger
from pydantic import BaseModel

from emoparse.core.backend.base import LLMBackend
from emoparse.core.backend.exceptions import BackendError
from emoparse.core.backend.retry import RetryConfig, retry_with_backoff

#: Schema Pydantic esperado como salida del agente.
ResultT = TypeVar("ResultT", bound=BaseModel)


# ══════════════════════════════════════════════════════════════════════════════
#  BaseAgent — una llamada al LLM por fila del DF
# ══════════════════════════════════════════════════════════════════════════════

class BaseAgent(ABC, Generic[ResultT]):
    """Clase base para agentes que procesan un DataFrame fila por fila.

    Cada fila genera una llamada independiente al backend LLM. La subclase
    define el schema esperado, la construcción de prompts y el mapeo de la
    respuesta a columnas de salida.

    Convenciones de subclase:
        - Definir `NAME`, `SCHEMA` y `OUTPUT_COLUMNS`.
        - Implementar `_build_system()`, `_build_user(row)` y
        `_map_to_columns(parsed, row)`.
    """

    #: Identificador del agente (logging, métricas).
    NAME: ClassVar[str]

    #: Schema Pydantic de la respuesta del LLM.
    SCHEMA: ClassVar[type[BaseModel]]

    #: Columnas que agrega al DF de salida.
    OUTPUT_COLUMNS: ClassVar[tuple[str, ...]]

    # ── Inicialización ───────────────────────────────────────────────────────

    def __init__(
        self,
        backend: LLMBackend,
        retry_config: RetryConfig | None = None,
    ) -> None:
        """
        Args:
            backend:
                Backend LLM que implementa el contrato de generación.
            retry_config:
                Política de reintentos para errores transitorios del backend.
                Si es None, no se realizan reintentos.
        """
        self._backend = backend
        self._retry_config = retry_config
        # El system prompt se construye una vez y permanece estable durante
        # todo el procesamiento. Las subclases pueden preparar previamente
        # los datos necesarios en su propio __init__.
        self._system = self._build_system()

    # ── Métodos que las subclases DEBEN implementar ──────────────────────────

    @abstractmethod
    def _build_system(self) -> str:
        """Construye el system prompt estable del agente.

        Se ejecuta una vez en `__init__` y no depende de la fila procesada.
        Configuración, ontologías o contexto fijo del run deben resolverse aquí.
        """

    @abstractmethod
    def _build_user(self, row: pd.Series) -> str:
        """Construye el user prompt para una fila."""

    @abstractmethod
    def _map_to_columns(
        self,
        parsed: BaseModel,
        row: pd.Series,
    ) -> dict[str, Any]:
        """Mapea la respuesta parseada del LLM a columnas de salida.

        El dict devuelto debe contener exactamente las claves definidas en
        `OUTPUT_COLUMNS`. `row` se incluye por si el mapeo requiere datos
        de la fila original.
        """

    # ── API pública ──────────────────────────────────────────────────────────

    def process_unit(self, row: pd.Series) -> ResultT:
        """Procesa una fila individual y devuelve el resultado parseado.

        Este método no captura errores del backend: cualquier excepción se
        propaga al caller.

        Returns:
            Instancia validada de `SCHEMA`.

        Raises:
            BackendError:
                Si falla la generación o la validación estructurada.
        """
        def _call() -> ResultT:
            user = self._build_user(row)
            response = self._backend.generate(
                system=self._system,
                user=user,
                schema=self.SCHEMA,
            )
            if not isinstance(response.parsed, self.SCHEMA):
                raise BackendError(
                    f"Backend devolvió response sin parsed (alias={response.model_alias}, "
                    f"parsed={response.parsed!r})"
                )
            return response.parsed  # type: ignore[return-value]

        if self._retry_config is not None:
            return retry_with_backoff(_call, self._retry_config)
        return _call()

    def run(self, df: pd.DataFrame) -> pd.DataFrame:
        """Procesa todas las filas y devuelve un DataFrame enriquecido.

        Las filas exitosas reciben valores en `OUTPUT_COLUMNS`. Si una fila
        falla, esas columnas quedan en None. El número y el orden de filas
        se preservan siempre.
        """
        if df.empty:
            # Mantener el contrato: incluso si el DataFrame está vacío,
            # las columnas de salida deben existir.
            out = df.copy()
            for col in self.OUTPUT_COLUMNS:
                out[col] = pd.Series(dtype="object")
            return out

        results: list[dict[str, Any]] = []
        total = len(df)
        # Loggear progreso cada 10% (al menos 1 cada vuelta para DFs chicos).
        log_every = max(1, total // 10)

        for i, (_, row) in enumerate(df.iterrows()):
            codigo = str(row.get("codigo", f"row_{i}"))
            if (i + 1) % log_every == 0 or i == 0:
                logger.info(f"[{self.NAME}] {i + 1}/{total} ({codigo})")

            row_out: dict[str, Any] = row.to_dict()

            try:
                parsed = self.process_unit(row)
                row_out.update(self._map_to_columns(parsed, row))
            except BackendError as e:
                logger.warning(
                    f"[{self.NAME}] {codigo}: {type(e).__name__}: {e}"
                )
                # None → NaN en columnas object, distinguible de
                # "no identificado" que es decisión del modelo.
                for col in self.OUTPUT_COLUMNS:
                    row_out[col] = None

            results.append(row_out)

        return pd.DataFrame(results)


# ══════════════════════════════════════════════════════════════════════════════
#  BaseBatchAgent — una llamada al LLM por GRUPO de N filas
# ══════════════════════════════════════════════════════════════════════════════

# El item de batch tiene la forma {unit_idx: int, <payload>: ...}.
# Python no deja imponer eso vía typing, se deja como contrato
# documentado y validado en runtime.

class BaseBatchAgent(ABC, Generic[ResultT]):
    """Clase base para agentes que procesan múltiples filas por llamada.

    Cada batch se envía como un conjunto de unidades numeradas [0..N-1].
    El backend devuelve una colección de items con `unit_idx`, que permite
    correlacionar cada resultado con su fila original.

    La clase valida cobertura del response, preserva filas faltantes con
    None y descarta índices inválidos sin interrumpir el procesamiento.
    """

    NAME: ClassVar[str]
    SCHEMA: ClassVar[type[BaseModel]]
    OUTPUT_COLUMNS: ClassVar[tuple[str, ...]]
    BATCH_SIZE: ClassVar[int]

    # ── Inicialización ───────────────────────────────────────────────────────

    def __init__(
        self,
        backend: LLMBackend,
        retry_config: RetryConfig | None = None,
    ) -> None:
        self._backend = backend
        self._retry_config = retry_config
        self._system = self._build_system()

    # ── Métodos que las subclases deben implementar ──────────────────────────

    @abstractmethod
    def _build_system(self) -> str:
        """System prompt; estable durante el run."""

    @abstractmethod
    def _build_user(self, batch: pd.DataFrame) -> str:
        """Construye el user prompt del batch.

        Las unidades deben numerarse localmente en el rango [0..N-1], ya que
        el backend responderá utilizando `unit_idx` para la correlación.
        """

    @abstractmethod
    def _map_item_to_columns(
        self,
        item: BaseModel,
        row: pd.Series,
    ) -> dict[str, Any]:
        """Mapea un item del batch response a columnas para una fila.

        `item` representa la respuesta correspondiente a una unidad y `row`
        es la fila original asociada a su `unit_idx`.
        """

    # ── API pública ──────────────────────────────────────────────────────────

    def run(self, df: pd.DataFrame) -> pd.DataFrame:
        """Procesa el DF en batches de BATCH_SIZE filas."""
        if df.empty:
            out = df.copy()
            for col in self.OUTPUT_COLUMNS:
                out[col] = pd.Series(dtype="object")
            return out

        # Reset de índice para que iloc[0..N-1] coincida con unit_idx.
        # Se guarda el índice original como columna temporal para
        # poder restaurarlo al final si el llamador depende de él.
        df_reset = df.reset_index(drop=False).rename(
            columns={"index": "__orig_index"}
        )

        results: list[dict[str, Any]] = []
        total = len(df_reset)
        n_batches = (total + self.BATCH_SIZE - 1) // self.BATCH_SIZE

        for batch_i in range(n_batches):
            start = batch_i * self.BATCH_SIZE
            end = min(start + self.BATCH_SIZE, total)
            batch = df_reset.iloc[start:end].reset_index(drop=True)
            batch_size = len(batch)

            logger.info(
                f"[{self.NAME}] batch {batch_i + 1}/{n_batches} "
                f"(filas {start + 1}-{end} de {total})"
            )

            # Mapeo entre unit_idx local del batch y fila original.
            unit_idx_to_row: dict[int, pd.Series] = {
                i: batch.iloc[i] for i in range(batch_size)
            }

            # Inicializar todas las filas como "fallidas" — las exitosas
            # se actualizan después.
            row_outputs: dict[int, dict[str, Any]] = {}
            for i in range(batch_size):
                row_dict = batch.iloc[i].to_dict()
                for col in self.OUTPUT_COLUMNS:
                    row_dict[col] = None
                row_outputs[i] = row_dict

            try:
                user = self._build_user(batch)

                def _call_backend() -> Any:
                    response = self._backend.generate(
                        system=self._system,
                        user=user,
                        schema=self.SCHEMA,
                    )
                    if not isinstance(response.parsed, self.SCHEMA):
                        raise BackendError(
                            f"Backend devolvió response sin parsed (alias={response.model_alias})"
                        )
                    return response.parsed

                if self._retry_config is not None:
                    parsed = retry_with_backoff(_call_backend, self._retry_config)
                else:
                    parsed = _call_backend()

                # `parsed` es un RootModel[List[BatchItem]].
                # Acceso al list interno: .root en RootModel v2.
                items = parsed.root  # type: ignore[attr-defined]
                self._apply_batch_items(
                    items=items,
                    unit_idx_to_row=unit_idx_to_row,
                    row_outputs=row_outputs,
                    batch_size=batch_size,
                )

            except BackendError as e:
                # El batch entero falla → todas las filas del batch
                # quedan con None en OUTPUT_COLUMNS (ya inicializadas así).
                logger.warning(
                    f"[{self.NAME}] batch {batch_i + 1}/{n_batches} falló: "
                    f"{type(e).__name__}: {e}"
                )

            # Recolectar resultados del batch en orden.
            for i in range(batch_size):
                results.append(row_outputs[i])

        # Restaurar orden original del input.
        out_df = pd.DataFrame(results).sort_values("__orig_index")
        out_df = out_df.drop(columns=["__orig_index"]).reset_index(drop=True)
        return out_df

    # ── Helper: validación de cobertura del batch response ───────────────────

    def _apply_batch_items(
        self,
        items: list[BaseModel],
        unit_idx_to_row: dict[int, pd.Series],
        row_outputs: dict[int, dict[str, Any]],
        batch_size: int,
    ) -> None:
        """Aplica los items del response batch sobre `row_outputs`.

        Los `unit_idx` fuera de rango se descartan, los duplicados generan
        warning y los faltantes permanecen con None.
        """
        seen: set[int] = set()
        for item in items:
            # Sanity: el schema debería garantizar que item tiene unit_idx,
            # pero si una subclase usa un schema raro, es preferible un error
            # claro en lugar de AttributeError.
            unit_idx = getattr(item, "unit_idx", None)
            if not isinstance(unit_idx, int):
                logger.warning(
                    f"[{self.NAME}] Item del batch sin unit_idx int "
                    f"(item={item!r}). Descartado."
                )
                continue

            if unit_idx < 0 or unit_idx >= batch_size:
                logger.warning(
                    f"[{self.NAME}] unit_idx={unit_idx} fuera de rango "
                    f"[0, {batch_size}). Descartado."
                )
                continue

            if unit_idx in seen:
                logger.warning(
                    f"[{self.NAME}] unit_idx={unit_idx} duplicado en el "
                    "batch response. Sobreescribiendo (último gana)."
                )
            seen.add(unit_idx)

            row = unit_idx_to_row[unit_idx]
            row_outputs[unit_idx].update(self._map_item_to_columns(item, row))

        missing = set(range(batch_size)) - seen
        if missing:
            if len(missing) == batch_size:
                logger.warning(
                    f"[{self.NAME}] Batch response NO cubrió ningún "
                    f"unit_idx esperado. Toda la batch queda en None."
                )
            else:
                logger.info(
                    f"[{self.NAME}] Batch response no cubrió "
                    f"{sorted(missing)}; esas filas quedan en None."
                )
