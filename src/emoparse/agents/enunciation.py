# ══════════════════════════════════════════════════════════════════════════════
#  emoparse.agents.enunciation
#
#  Agente de análisis enunciativo.
# ══════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

import json
from typing import Any

import pandas as pd

from emoparse.agents.base import BaseAgent
from emoparse.core.backend.base import LLMBackend
from emoparse.core.prompts import enunciation as prompts
from emoparse.core.schemas import EnunciacionSchema
from emoparse.genres.base import Genre
from emoparse.genres.schema_factory import enunciacion_schema


class EnunciationAgent(BaseAgent[EnunciacionSchema]):
    """Identifica la estructura enunciativa de un discurso.

    Procesa una unidad completa por llamada y agrega tres columnas:

        - `enunciador`
        - `enunciador_justificacion`
        - `enunciatarios` (JSON serializado)
    """

    NAME = "enunciation"
    # Schema por defecto. Si se pasa genre, la instancia puede
    # reemplazarlo por una versión restringida a los roles válidos
    # de ese género discursivo.
    SCHEMA = EnunciacionSchema
    OUTPUT_COLUMNS = (
        "enunciador",
        "enunciador_justificacion",
        "enunciatarios",
    )

    def __init__(
        self,
        backend: LLMBackend,
        diccionario_tipos: dict[str, Any],
        heuristicas: str | None = None,
        retry_config: Any | None = None,
        genre: Genre | None = None,
    ) -> None:
        """
        Args:
            backend: Backend LLM utilizado para generación estructurada.
            diccionario_tipos: Diccionario de tipos discursivos utilizado
                en el system prompt.
            heuristicas: Reglas heurísticas para identificación de
                estructura enunciativa. Si None, no se inyectan en el
                system prompt.
            retry_config: Política de reintentos ante errores transitorios.
            genre: Configuración opcional de género discursivo. Si se
                provee, restringe los roles enunciativos válidos del schema.
        """
        self._diccionario_str = json.dumps(
            diccionario_tipos, ensure_ascii=False, indent=2
        )
        self._heuristicas = heuristicas
        self._genre = genre

        # Si se define genre, reemplazar el schema antes de llamar a
        # super().__init__, para que la clase base use la versión correcta
        # durante la inicialización.
        if genre is not None:
            self.SCHEMA = enunciacion_schema(genre)  # type: ignore[misc]

        super().__init__(backend, retry_config=retry_config)

    # ── Hooks de BaseAgent ───────────────────────────────────────────────────

    def _build_system(self) -> str:
        return prompts.render_system(
            diccionario=self._diccionario_str,
            heuristicas=self._heuristicas,
        )

    def _build_user(self, row: pd.Series) -> str:
        codigo = str(row["codigo"])
        resumen = _resolve_resumen(row)
        fragmentos = _extract_fragments(row)
        return prompts.render_user(
            codigo=codigo,
            resumen=resumen,
            fragmentos=fragmentos,
        )

    def _map_to_columns(
        self,
        parsed: EnunciacionSchema,
        row: pd.Series,
    ) -> dict[str, Any]:
        # Serialización JSON para mantener compatibilidad tabular.
        # ensure_ascii=False preserva texto en español.
        enunciatarios_json = json.dumps(
            [e.model_dump() for e in parsed.enunciatarios],
            ensure_ascii=False,
        )
        return {
            "enunciador": parsed.enunciador.actor,
            "enunciador_justificacion": parsed.enunciador.justificacion,
            "enunciatarios": enunciatarios_json,
        }


# ══════════════════════════════════════════════════════════════════════════════
#  Helpers de resolución de contexto textual
# ══════════════════════════════════════════════════════════════════════════════

#: Límite máximo de caracteres usado como fallback cuando no existe
#: un resumen previo disponible.
_CONTENIDO_FALLBACK_CHAR_LIMIT = 4000


def _resolve_resumen(row: pd.Series) -> str:
    """Obtiene el resumen textual principal del discurso.

    Prioriza la columna `resumen_global`. Si no está disponible,
    utiliza una versión truncada de `contenido` como fallback.
    """
    raw = row.get("resumen_global")
    if raw is not None and not (isinstance(raw, float) and pd.isna(raw)):
        text = str(raw).strip()
        if text and text.lower() not in ("none", "nan"):
            return text

    contenido = str(row.get("contenido", ""))
    if len(contenido) > _CONTENIDO_FALLBACK_CHAR_LIMIT:
        return contenido[:_CONTENIDO_FALLBACK_CHAR_LIMIT] + "..."
    return contenido


def _extract_fragments(row: pd.Series) -> str:
    """Obtiene fragmentos representativos del discurso.

    Si `resumen_fragmentos` contiene una lista válida, devuelve una
    selección formateada. En caso contrario, usa un fragmento truncado
    de `contenido` como fallback.
    """
    raw = row.get("resumen_fragmentos", "[]")
    try:
        frags = json.loads(raw) if isinstance(raw, str) else raw
    except json.JSONDecodeError:
        frags = []
    if isinstance(frags, list) and frags:
        return "\n\n".join(f"- {f}" for f in frags[:5])
    contenido = str(row.get("contenido", ""))
    return contenido[:1000] + ("..." if len(contenido) > 1000 else "")
