# ══════════════════════════════════════════════════════════════════════════════
#  emoparse.agents.summarizer
#
#  Agente de resumen de discursos.
#
#  Caso especial del pipeline: no hereda de BaseAgent porque no trabaja
#  con salida estructurada por schema, sino con texto libre en dos etapas:
#
#  1. Resumen por fragmento
#  2. Resumen global consolidado
#
#  Output:
#  - resumen_fragmentos: JSON string con lista de resúmenes parciales
#  - resumen_global: string con el resumen integrado final
#
#  Si existe una columna `chunks`, se utiliza como fuente de fragmentos.
#  En caso contrario, el contenido se divide automáticamente en chunks.
# ══════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

import json
from typing import Any

import pandas as pd
from loguru import logger

from emoparse.core.backend.base import LLMBackend
from emoparse.core.backend.exceptions import BackendError
from emoparse.core.prompts import summarizer as prompts
from emoparse.genres.base import Genre
from emoparse.pipeline.chunking import split_into_sentences


#: Tamaño objetivo de cada chunk en caracteres.
#: Se usa longitud de texto y no tokens para evitar acoplamiento con
#: tokenizers específicos del backend.
_DEFAULT_CHUNK_CHAR_LIMIT = 1500


class SummarizerAgent:
    """Agente de resumen en dos etapas.

    Genera primero resúmenes parciales por fragmento y luego un resumen
    global consolidado por discurso.

    Columnas de salida:
        - `resumen_fragmentos`: JSON string con lista de resúmenes parciales
        - `resumen_global`: resumen integrado final

    Si una llamada al backend falla, los campos correspondientes quedan en
    None sin interrumpir el procesamiento del resto del DataFrame.
    """

    NAME = "summarizer"
    OUTPUT_COLUMNS = ("resumen_fragmentos", "resumen_global")

    def __init__(
        self,
        backend: LLMBackend,
        retry_config: Any | None = None,
        chunk_char_limit: int = _DEFAULT_CHUNK_CHAR_LIMIT,
        genre: Genre | None = None,
    ) -> None:
        """
        Args:
            backend: Backend LLM utilizado para generar los resúmenes.
            retry_config: Configuración de reintentos delegada al backend.
            chunk_char_limit: Tamaño máximo de cada fragmento al dividir
                automáticamente el contenido.
            genre: Parámetro mantenido por consistencia con otros agentes del
                pipeline. Actualmente no modifica el comportamiento interno del
                summarizer.
        """
        self._backend = backend
        self._retry_config = retry_config
        self._chunk_char_limit = chunk_char_limit
        self._genre = genre

    # ── API pública: una llamada al LLM por fragmento o por global ───────────

    def summarize_fragment(self, fragment_text: str) -> str:
        """Genera el resumen de un fragmento.

        Propaga BackendError en caso de fallo del backend.
        """
        response = self._backend.generate(
            system=prompts.SYSTEM_FRAGMENTO,
            user=prompts.render_user_fragmento(fragmento=fragment_text),
        )
        return response.raw.strip()

    def summarize_global(
        self,
        titulo: str,
        fecha: str,
        resumenes_parciales: list[str],
    ) -> str:
        """Genera el resumen global a partir de resúmenes parciales.

        Propaga BackendError en caso de fallo del backend.
        """
        joined = "\n\n".join(
            f"[{i + 1}] {r}" for i, r in enumerate(resumenes_parciales)
        )
        response = self._backend.generate(
            system=prompts.SYSTEM_GLOBAL,
            user=prompts.render_user_global(
                titulo=titulo,
                fecha=fecha,
                resumenes_parciales=joined,
            ),
        )
        return response.raw.strip()

    # ── Procesamiento de DataFrame ───────────────────────────────────────────

    def run(self, df: pd.DataFrame) -> pd.DataFrame:
        """Procesa todos los discursos del DataFrame.

        Para cada discurso:
            1. Obtiene los chunks desde la columna `chunks` o desde `contenido`
            2. Genera un resumen parcial por fragmento
            3. Genera un resumen global consolidado
            4. Escribe `resumen_fragmentos` y `resumen_global`

        Si una llamada al backend falla, los campos correspondientes quedan en
        None y el procesamiento continúa con el resto de los discursos.
        """
        if df.empty:
            out = df.copy()
            for col in self.OUTPUT_COLUMNS:
                out[col] = pd.Series(dtype="object")
            return out

        results: list[dict[str, Any]] = []
        total = len(df)
        log_every = max(1, total // 10)

        for i, (_, row) in enumerate(df.iterrows()):
            codigo = str(row.get("codigo", f"row_{i}"))
            if (i + 1) % log_every == 0 or i == 0:
                logger.info(f"[{self.NAME}] {i + 1}/{total} ({codigo})")

            row_out: dict[str, Any] = row.to_dict()
            row_out["resumen_fragmentos"] = None
            row_out["resumen_global"] = None

            try:
                # Paso 1: chunks → parciales.
                chunks = self._get_chunks(row)
                if not chunks:
                    logger.warning(
                        f"[{self.NAME}] {codigo}: sin contenido para resumir"
                    )
                    results.append(row_out)
                    continue

                parciales = [self.summarize_fragment(ch) for ch in chunks]
                row_out["resumen_fragmentos"] = json.dumps(
                    parciales, ensure_ascii=False
                )

                # Paso 2: parciales → global. Si solo hay un parcial,
                # ese es el global (evita una llamada redundante).
                if len(parciales) == 1:
                    row_out["resumen_global"] = parciales[0]
                else:
                    titulo = str(row.get("titulo", codigo))
                    fecha = str(row.get("fecha", ""))
                    row_out["resumen_global"] = self.summarize_global(
                        titulo=titulo,
                        fecha=fecha,
                        resumenes_parciales=parciales,
                    )

            except BackendError as e:
                logger.warning(
                    f"[{self.NAME}] {codigo}: {type(e).__name__}: {e}"
                )

            results.append(row_out)

        return pd.DataFrame(results)

    # ── Chunking ─────────────────────────────────────────────────────────────

    def _get_chunks(self, row: pd.Series) -> list[str]:
        """Obtiene los chunks asociados a un discurso.

        Prioridad:
            1. Si existe la columna `chunks` y contiene una lista JSON válida,
            se utiliza esa información.
            2. En caso contrario, se divide `contenido` usando
            `_chunk_char_limit`.
        """
        # Caso 1: chunks pre-computados.
        chunks_raw = row.get("chunks")
        if chunks_raw and isinstance(chunks_raw, str):
            try:
                parsed = json.loads(chunks_raw)
                if isinstance(parsed, list) and all(isinstance(c, str) for c in parsed):
                    return [c for c in parsed if c.strip()]
            except json.JSONDecodeError:
                pass

        # Caso 2: partir contenido.
        contenido = str(row.get("contenido", "")).strip()
        if not contenido:
            return []
        return _split_into_chunks(contenido, self._chunk_char_limit)


# ══════════════════════════════════════════════════════════════════════════════
#  Helpers
# ══════════════════════════════════════════════════════════════════════════════

def _split_into_chunks(text: str, char_limit: int) -> list[str]:
    """Divide `text` en chunks de hasta `char_limit` caracteres.

    Estrategia:
        1. Divide inicialmente por párrafos (`\\n\\n`)
        2. Agrupa párrafos consecutivos hasta alcanzar el límite
        3. Si un párrafo individual supera el límite, lo subdivide por
        oraciones mediante `split_into_sentences`

    Garantía:
        Ningún chunk supera `char_limit`, salvo cuando una única oración ya
        excede ese tamaño. En ese caso se preserva como unidad completa para
        evitar cortes artificiales.
    """
    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
    if not paragraphs:
        return []

    # Expandir párrafos demasiado grandes en oraciones antes de agrupar.
    expanded: list[str] = []
    for p in paragraphs:
        if len(p) <= char_limit:
            expanded.append(p)
        else:
            # Subdividir por oraciones sin cortar unidades intermedias.
            sentences = split_into_sentences(p, max_chars=char_limit)
            if sentences:
                expanded.extend(sentences)
            else:
                # Fallback defensivo: preservar el párrafo original si el
                # splitter no produce resultados.
                expanded.append(p)

    chunks: list[str] = []
    current: list[str] = []
    current_len = 0

    for p in expanded:
        p_len = len(p)
        # Si excede el límite y ya existe contenido acumulado,
        # cerrar el chunk actual y comenzar uno nuevo.
        if current and current_len + p_len + 2 > char_limit:
            chunks.append("\n\n".join(current))
            current = [p]
            current_len = p_len
        else:
            current.append(p)
            current_len += p_len + 2  # +2 por el "\n\n"

    if current:
        chunks.append("\n\n".join(current))

    return chunks
