# ══════════════════════════════════════════════════════════════════════════════
#  emoparse.agents.metadata
#
#  Agente de metadatos del pipeline.
#
#  Identifica tipo de discurso y ubicación geográfica a partir del
#  contenido del discurso. Opera con BaseAgent: una llamada al LLM por
#  fila del DataFrame y mapeo del resultado estructurado a columnas
#  planas para persistencia y análisis downstream.
# ══════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

import json
from typing import Any

import pandas as pd

from emoparse.agents.base import BaseAgent
from emoparse.core.backend.base import LLMBackend
from emoparse.core.prompts import metadata as prompts
from emoparse.core.schemas import MetadatosSchema
from emoparse.genres.base import Genre


class MetadataAgent(BaseAgent[MetadatosSchema]):
    """Identifica tipo de discurso y ubicación geográfica.

    Procesa una fila por discurso y agrega columnas de tipo de discurso,
    justificación y localización (ciudad, provincia, país).
    """

    NAME = "metadata"
    SCHEMA = MetadatosSchema
    OUTPUT_COLUMNS = (
        "tipo_discurso",
        "tipo_discurso_justificacion",
        "ciudad",
        "provincia",
        "pais",
        "lugar_justificacion",
    )

    def __init__(
        self,
        backend: LLMBackend,
        diccionario_tipos: dict[str, Any],
        retry_config: Any | None = None,
        genre: Genre | None = None,
    ) -> None:
        """
        Args:
            backend: Backend LLM ya inicializado.
            diccionario_tipos: Diccionario de tipos de discurso usado en el
                system prompt.
            retry_config: Política opcional de reintentos.
            genre: Parámetro reservado para compatibilidad de configuración
                por género. Actualmente no modifica prompts ni schema.
        """
        # Debe inicializarse antes de super().__init__ porque la base
        # construye el system prompt durante el init.
        self._diccionario_str = json.dumps(
            diccionario_tipos, ensure_ascii=False, indent=2
        )
        self._genre = genre
        super().__init__(backend, retry_config=retry_config)

    # ── Hooks de BaseAgent ───────────────────────────────────────────────────

    def _build_system(self) -> str:
        return prompts.render_system(diccionario=self._diccionario_str)

    def _build_user(self, row: pd.Series) -> str:
        codigo = str(row["codigo"])
        resumen, used_fallback = _resolve_resumen(row)

        fragmentos = _extract_fragments(row) if used_fallback else ""

        return prompts.render_user(
            codigo=codigo,
            resumen=resumen,
            fragmentos=fragmentos,
        )

    def _map_to_columns(
        self,
        parsed: MetadatosSchema,
        row: pd.Series,
    ) -> dict[str, Any]:
        return {
            "tipo_discurso": parsed.tipo_discurso,
            "tipo_discurso_justificacion": parsed.tipo_discurso_justificacion,
            "ciudad": parsed.ciudad,
            "provincia": parsed.provincia,
            "pais": parsed.pais,
            "lugar_justificacion": parsed.lugar_justificacion,
        }


# ══════════════════════════════════════════════════════════════════════════════
#  Helpers
# ══════════════════════════════════════════════════════════════════════════════

#: Límite de caracteres usado cuando no hay resumen disponible y se
#: recurre al contenido original. Evita inflar innecesariamente el
#: prompt y reduce riesgo de overflow de contexto.
_CONTENIDO_FALLBACK_CHAR_LIMIT = 4000


def _resolve_resumen(row: pd.Series) -> tuple[str, bool]:
    """Resuelve el texto de resumen usado en el prompt.

    Prioriza `resumen_global` cuando existe. Si no está disponible,
    usa `contenido` truncado como fallback para evitar prompts
    excesivamente largos.

    Returns:
        tuple[str, bool]:
            - texto final usado como resumen
            - True si hubo fallback a `contenido`
    """
    raw = row.get("resumen_global")
    if raw is not None and not (isinstance(raw, float) and pd.isna(raw)):
        text = str(raw).strip()
        if text and text.lower() not in ("none", "nan"):
            return text, False
    contenido = str(row.get("contenido", ""))
    if len(contenido) > _CONTENIDO_FALLBACK_CHAR_LIMIT:
        return (
            contenido[:_CONTENIDO_FALLBACK_CHAR_LIMIT] + "...",
            True,
        )
    return contenido, True


def _extract_fragments(row: pd.Series) -> str:
    """Extrae fragmentos representativos para el prompt.

    Usa `resumen_fragmentos` cuando está disponible; si no, aplica
    fallback al contenido truncado.
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
