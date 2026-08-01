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
from typing import Any, Callable, ClassVar, Generic, TypeVar

import pandas as pd
from loguru import logger
from pydantic import BaseModel

from emoparse.core.backend.base import LLMBackend
from emoparse.core.backend.exceptions import (
    BackendError,
    ContextLengthExceededError,
)
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
        #: Callback opcional que la stage engancha para llevar el avance
        #: cuando le delega el corpus entero al agente en una sola llamada.
        #: Recibe la cantidad de filas resueltas.
        self.on_progress: Callable[[int], None] | None = None
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
        # Sin callback de la stage el avance se loguea cada 10%; con callback
        # lo reporta ella. Una sola fila no informa nada: el "1/1" repetido de
        # las stages que llaman al agente por discurso solo tapa el avance.
        log_every = max(1, total // 10)

        for i, (_, row) in enumerate(df.iterrows()):
            codigo = str(row.get("codigo", f"row_{i}"))
            if self.on_progress is not None:
                self.on_progress(1)
            elif total > 1 and ((i + 1) % log_every == 0 or i == 0):
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

    #: Columna reservada donde el agente deja el motivo por el que una fila
    #: quedó sin resolver. No es una columna de salida del schema: la stage la
    #: lee para persistir el error y no la escribe como resultado.
    ERROR_COLUMN: ClassVar[str] = "_agente_error"

    #: Qué hacer ante un ancla que no coincide. Ver `_anchor`.

    #: En False (por defecto) el desajuste se registra y el item se aplica
    #: igual: el ancla depende de que el modelo sepa producirla, y una
    #: verificación no comprobada no puede bloquear el pipeline. Se pone en
    #: True cuando el log muestra que el modelo la produce bien.
    ANCHOR_STRICT: ClassVar[bool] = False

    def __init__(
        self,
        backend: LLMBackend,
        retry_config: RetryConfig | None = None,
    ) -> None:
        self._backend = backend
        self._retry_config = retry_config
        #: Callback opcional de avance; lo engancha la stage (ver BaseAgent).
        self.on_progress: Callable[[int], None] | None = None
        self._system = self._build_system()

    # ── Métodos que las subclases deben implementar ──────────────────────────

    def _anchor(self, row: pd.Series) -> str | None:
        """Valor que el modelo debe repetir en `ancla` para esta fila.

        Habilita la verificación de correspondencia entre la respuesta y la
        unidad: `unit_idx` garantiza que el modelo numeró bien, no que haya
        escrito sobre la unidad que numeró. Devolver None (el default)
        desactiva la verificación, para los agentes cuyo schema no declara
        `ancla`.

        **Debe ser único dentro del batch**, o no distingue nada: si dos
        unidades comparten ancla —dos posts de la misma cuenta, por ejemplo—
        el cruce entre ellas pasa inadvertido. El mismo valor tiene que
        aparecer en el prompt que arma `_build_user`, así que conviene que
        este método sea la única fuente de ambos.
        """
        return None

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

            if self.on_progress is None and n_batches > 1:
                logger.info(
                    f"[{self.NAME}] batch {batch_i + 1}/{n_batches} "
                    f"(filas {start + 1}-{end} de {total})"
                )
            results.extend(
                self._process_batch(batch, split_on_overflow=True)
            )
            if self.on_progress is not None:
                self.on_progress(end - start)

        # Restaurar orden original del input.
        out_df = pd.DataFrame(results).sort_values("__orig_index")
        out_df = out_df.drop(columns=["__orig_index"]).reset_index(drop=True)
        return out_df

    def _process_batch(
        self,
        batch: pd.DataFrame,
        *,
        split_on_overflow: bool,
    ) -> list[dict[str, Any]]:
        """Procesa un batch y devuelve una fila de salida por unidad, en orden.

        Ante `ContextLengthExceededError` —error permanente que el retry con
        backoff no reintenta— y si `split_on_overflow` es True, el batch se
        parte una sola vez por la mitad y cada mitad se reintenta ya sin volver
        a partir. Recupera las unidades que hoy se pierden en bloque cuando el
        batch no cierra el JSON. Con un batch de una sola unidad no hay dónde
        partir: la unidad se marca fallida, como antes.
        """
        batch = batch.reset_index(drop=True)
        batch_size = len(batch)

        unit_idx_to_row: dict[int, pd.Series] = {
            i: batch.iloc[i] for i in range(batch_size)
        }
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
                    max_items=batch_size,
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

            items = parsed.root  # type: ignore[attr-defined]
            self._apply_batch_items(
                items=items,
                unit_idx_to_row=unit_idx_to_row,
                row_outputs=row_outputs,
                batch_size=batch_size,
            )

        except ContextLengthExceededError as e:
            if split_on_overflow and batch_size > 1:
                mid = batch_size // 2
                logger.warning(
                    f"[{self.NAME}] batch de {batch_size} excedió el contexto; "
                    f"reintento partido en {mid}+{batch_size - mid} (una vez)."
                )
                out = self._process_batch(
                    batch.iloc[:mid], split_on_overflow=False
                )
                out += self._process_batch(
                    batch.iloc[mid:], split_on_overflow=False
                )
                return out
            logger.warning(
                f"[{self.NAME}] batch de {batch_size} falló: "
                f"{type(e).__name__}: {e}"
            )

        except BackendError as e:
            # El batch entero falla → todas las filas quedan con None en
            # OUTPUT_COLUMNS (ya inicializadas así).
            logger.warning(
                f"[{self.NAME}] batch de {batch_size} falló: "
                f"{type(e).__name__}: {e}"
            )

        return [row_outputs[i] for i in range(batch_size)]

    # ── Helper: validación de cobertura del batch response ───────────────────

    def _apply_batch_items(
        self,
        items: list[BaseModel],
        unit_idx_to_row: dict[int, pd.Series],
        row_outputs: dict[int, dict[str, Any]],
        batch_size: int,
    ) -> None:
        """Aplica los items del batch response sobre `row_outputs`.

        Cada item se asigna a su fila por el `unit_idx` que él mismo declara,
        nunca por la posición en que el modelo lo listó: el orden de la
        respuesta no es información, y tratarlo como tal reordena el batch y
        produce atribuciones cruzadas (la clasificación de una unidad escrita
        sobre otra), que es un error indetectable aguas abajo.

        - `unit_idx == {0..N-1}` → biyección esperada: se asigna por `unit_idx`.
        - `unit_idx == {1..N}`   → el modelo 1-indexó: se corrige la etiqueta
          (`unit_idx - 1`), que sigue siendo asignar por índice declarado.
        - cualquier otra cosa    → batch no confiable. No se adivina: las filas
          quedan en None → re-pending → las reintenta `emoparse retry`.

        Si el agente implementa `_anchor`, además se verifica que cada item
        repita el ancla de su fila. Con `ANCHOR_STRICT`, un solo desajuste
        rechaza el batch entero: el cruce de contenidos es una permutación,
        así que si una unidad está mal atribuida las demás no son confiables.
        """
        idxs = [getattr(it, "unit_idx", None) for it in items]
        all_int = len(idxs) == batch_size and all(
            isinstance(x, int) for x in idxs
        )
        perfect = all_int and sorted(idxs) == list(range(batch_size))
        off_by_one = all_int and sorted(idxs) == list(range(1, batch_size + 1))

        if perfect:
            pares = [(int(it.unit_idx), it) for it in items]  # type: ignore[attr-defined]
        elif off_by_one:
            logger.debug(
                f"[{self.NAME}] unit_idx 1-indexado ({idxs}); corrijo la "
                "etiqueta y asigno por índice declarado."
            )
            pares = [(int(it.unit_idx) - 1, it) for it in items]  # type: ignore[attr-defined]
        else:
            self._rechazar_batch(
                row_outputs,
                f"unit_idx no confiable (recibidos={idxs}, "
                f"batch_size={batch_size})",
            )
            return

        anclas = {
            j: _normalizar_ancla(self._anchor(row))
            for j, row in unit_idx_to_row.items()
        }
        presentes = [a for a in anclas.values() if a]
        if presentes and len(set(presentes)) < len(presentes):
            # Sin unicidad el ancla no distingue unidades: decirlo es mejor
            # que verificar de mentira y dar por buena una atribución cruzada.
            logger.warning(
                "[{}] anclas repetidas en el batch ({}): la verificación de "
                "correspondencia queda sin efecto para esas unidades.",
                self.NAME,
                sorted(presentes),
            )
        desajustes = [
            (j, anclas[j], _normalizar_ancla(getattr(item, "ancla", None)))
            for j, item in pares
            if not _anclas_coinciden(
                anclas[j], _normalizar_ancla(getattr(item, "ancla", None))
            )
        ]
        if desajustes:
            detalle = "; ".join(
                f"unidad {j}: esperaba '{esp}', recibí '{rec}'"
                for j, esp, rec in desajustes
            )
            if self.ANCHOR_STRICT:
                self._rechazar_batch(
                    row_outputs,
                    f"ancla no coincide ({detalle})",
                )
                return
            # Sin modo estricto el desajuste se informa pero no frena: puede
            # ser que el modelo no esté produciendo el ancla, no que haya
            # cruzado los contenidos, y no hay cómo distinguirlo desde acá.
            logger.warning(
                "[{}] ancla no coincide ({}). Se aplica igual: revisá el "
                "detalle antes de activar ANCHOR_STRICT.",
                self.NAME,
                detalle,
            )

        for j, item in pares:
            row_outputs[j].update(
                self._map_item_to_columns(item, unit_idx_to_row[j])
            )

    def _rechazar_batch(
        self, row_outputs: dict[int, dict[str, Any]], motivo: str,
    ) -> None:
        """Descarta el batch entero dejando rastro en las filas y en el log."""
        logger.error(
            "[{}] batch RECHAZADO: {}. Las filas quedan sin resolver para "
            "reintento.",
            self.NAME,
            motivo,
        )
        # Sin esta marca el rechazo no deja rastro en la DB: las filas vuelven
        # a pendiente y el estado del run informa cero errores aunque el log
        # haya gritado. La stage decide si la persiste.
        for salida in row_outputs.values():
            salida[self.ERROR_COLUMN] = f"batch rechazado: {motivo}"


def _anclas_coinciden(esperada: str, recibida: str) -> bool:
    """Compara dos anclas normalizadas, tolerando abreviaciones del modelo.

    Si falta cualquiera de los dos lados no hay verificación posible, y
    tratar eso como cruce sería inventar un error.
    """
    if not esperada or not recibida:
        return True
    return (
        esperada == recibida
        or esperada in recibida
        or recibida in esperada
    )


def _normalizar_ancla(valor: Any) -> str:
    """Normaliza un ancla para compararla (sin @, sin caso, sin espacios)."""
    if valor is None:
        return ""
    return str(valor).strip().lstrip("@").casefold()
