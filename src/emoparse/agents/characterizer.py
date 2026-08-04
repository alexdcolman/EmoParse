# ══════════════════════════════════════════════════════════════════════════════
#  emoparse.agents.characterizer
#
#  Agente batch para caracterización de emociones detectadas.
# ══════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

import re
from typing import Any

import pandas as pd

from emoparse.agents.base import BaseBatchAgent
from emoparse.core.backend.base import LLMBackend
from emoparse.core.prompts import characterizer as prompts
from emoparse.core.schemas import (
    CaracterizacionBatchItemSchema,
    ListaCaracterizacionBatchSchema,
)
from emoparse.core.text import strip_accents_lower
from emoparse.genres.base import Genre


class CharacterizerAgent(BaseBatchAgent[ListaCaracterizacionBatchSchema]):
    """Agente batch que caracteriza emociones individuales."""

    NAME = "characterizer"
    SCHEMA = ListaCaracterizacionBatchSchema
    OUTPUT_COLUMNS = (
        "foria",
        "foria_justificacion",
        "dominancia",
        "dominancia_justificacion",
        "intensidad",
        "intensidad_justificacion",
        "duracion",
        "duracion_justificacion",
        "tipo_atribucion",
        "tipo_atribucion_justificacion",
        "temporalidad",
        "temporalidad_justificacion",
        "aspecto",
        "aspecto_justificacion",
    )
    BATCH_SIZE = 5

    def __init__(
        self,
        backend: LLMBackend,
        titulo: str = "",
        tipo_discurso: str = "",
        heuristicas: str | None = None,
        retry_config: Any | None = None,
        genre: Genre | None = None,
        enunciador: str = "",
    ) -> None:
        """
        Args:
            backend: Backend LLM utilizado para la generación estructurada.
            titulo: Título del discurso, usado como contexto para el prompt.
            tipo_discurso: Clasificación o tipo del discurso, usado como
                contexto.
            enunciador: Referente emisor del discurso, usado para distinguir
                auto de heteroatribución.
            heuristicas: Reglas heurísticas para caracterización de emociones.
                Si None, no se inyectan heurísticas en el system prompt.
            retry_config: Política de reintentos ante errores transitorios
                del backend.
            genre: Configuración opcional de género discursivo. Puede
                sobrescribir parámetros como `BATCH_SIZE`.
        """

        self._titulo = titulo
        self._tipo_discurso = tipo_discurso
        self._enunciador = enunciador
        self._heuristicas = heuristicas
        self._genre = genre

        if genre is not None and "characterizer" in genre.batch_size:
            self.BATCH_SIZE = genre.batch_size["characterizer"]  # type: ignore[misc]

        super().__init__(backend, retry_config=retry_config)

    # ── Hooks ────────────────────────────────────────────────────────────────

    def _build_system(self) -> str:
        return prompts.render_system(
            titulo=self._titulo,
            tipo_discurso=self._tipo_discurso,
            enunciador=self._enunciador,
            heuristicas=self._heuristicas,
        )

    def _build_user(self, batch: pd.DataFrame) -> str:
        bloques: list[str] = []
        for i, (_, row) in enumerate(batch.iterrows()):
            codigo = str(row.get("codigo", ""))
            frase = str(row.get("frase", ""))
            experienciador = str(row.get("experienciador", ""))
            experienciador_marca = str(row.get("experienciador_marca", ""))
            tipo_emocion = str(row.get("tipo_emocion", ""))
            modo = str(row.get("modo_existencia", ""))
            tipo_configuracion = str(row.get("tipo_configuracion", ""))
            fuente_marca = str(row.get("fuente_marca", ""))
            fuente_inferencia = str(row.get("fuente_inferencia", ""))

            bloques.append(
                f"EMOCIÓN [{i}] (codigo={codigo}):\n"
                f"  Experienciador:  {experienciador}\n"
                f"  Marca experienciador: {experienciador_marca}\n"
                f"  Tipo emoción:    {tipo_emocion}\n"
                f"  Modo existencia: {modo}\n"
                f"  Configuración:   {tipo_configuracion}\n"
                f"  Fuente marca:    {fuente_marca}\n"
                f"  Fuente inferencia: {fuente_inferencia}\n"
                f"  Frase de origen: {frase}"
            )
        unidades_block = "\n\n".join(bloques)
        return prompts.render_user(unidades_block=unidades_block)

    def _map_item_to_columns(
        self,
        item: CaracterizacionBatchItemSchema,
        row: pd.Series,
    ) -> dict[str, Any]:
        c = item.caracterizacion
        tipo_atribucion = c.tipo_atribucion
        justificacion_atribucion = c.tipo_atribucion_justificacion
        experienciador = str(row.get("experienciador", "")).strip()
        marca = str(row.get("experienciador_marca", "")).strip()
        frase = str(row.get("frase", "")).strip()
        configuracion = str(row.get("tipo_configuracion", "")).strip()
        same_as_enunciator = bool(
            self._enunciador.strip()
            and experienciador
            and _same_referent(experienciador, self._enunciador)
        )
        marca_literal = _literal_mark_in_text(marca, frase)
        explicit_config = configuracion in _EXPLICIT_ATTRIBUTION_CONFIGS

        if same_as_enunciator and _optative_self_mark(marca):
            tipo_atribucion = "auto_atribucion"
            justificacion_atribucion = (
                f"El optativo '{marca}' expresa explícitamente el deseo del enunciador."
            )
        elif tipo_atribucion == "auto_atribucion" and _first_person_mark(marca):
            # Un posesivo o pronombre de primera persona puede abarcar al
            # enunciador y a un colectivo institucional distinto de su nombre.
            pass
        elif same_as_enunciator:
            if marca_literal and explicit_config:
                tipo_atribucion = "auto_atribucion"
            elif tipo_atribucion in {"auto_atribucion", "hetero_atribucion"}:
                tipo_atribucion = "sin_atribucion"
                justificacion_atribucion = (
                    "La emoción se infiere de la construcción, sin un término "
                    "emocional atribuido explícitamente al enunciador."
                )
        elif self._enunciador.strip() and experienciador:
            if frase and marca_literal and explicit_config:
                tipo_atribucion = "hetero_atribucion"
                justificacion_atribucion = (
                    f"La unidad atribuye explícitamente la emoción a "
                    f"{experienciador}, distinto del enunciador."
                )
            elif not frase and tipo_atribucion == "auto_atribucion":
                # Compatibilidad con filas antiguas que no transportaban frase
                # ni configuración al postprocesado del characterizer.
                tipo_atribucion = "hetero_atribucion"
                justificacion_atribucion = (
                    f"La emoción se atribuye a {experienciador}, distinto del "
                    f"enunciador {self._enunciador}."
                )
            elif tipo_atribucion in {"auto_atribucion", "hetero_atribucion"}:
                tipo_atribucion = "sin_atribucion"
                justificacion_atribucion = (
                    "El experienciador se recupera del contexto, pero la unidad "
                    "no lo marca sintácticamente."
                )

        return {
            "foria": c.foria,
            "foria_justificacion": c.foria_justificacion,
            "dominancia": c.dominancia,
            "dominancia_justificacion": c.dominancia_justificacion,
            "intensidad": c.intensidad,
            "intensidad_justificacion": c.intensidad_justificacion,
            "duracion": c.duracion,
            "duracion_justificacion": c.duracion_justificacion,
            "tipo_atribucion": tipo_atribucion,
            "tipo_atribucion_justificacion": justificacion_atribucion,
            "temporalidad": c.temporalidad,
            "temporalidad_justificacion": c.temporalidad_justificacion,
            "aspecto": c.aspecto,
            "aspecto_justificacion": c.aspecto_justificacion,
        }


_OPTATIVE_SELF_MARK_RE = re.compile(r"^\s*ojal[aá]\b", re.IGNORECASE)

_EXPLICIT_ATTRIBUTION_CONFIGS = frozenset(
    {
        "sostenido_en_sustantivos",
        "sostenido_en_adjetivos",
        "ordenado_alrededor_de_verbos_psicologicos",
    }
)

_FIRST_PERSON_MARK_RE = re.compile(
    r"\b(?:yo|me|mi|mis|mío|mía|mios|mias|nosotros|nosotras|nos|nuestro|"
    r"nuestra|nuestros|nuestras)\b",
    re.IGNORECASE,
)


def _same_referent(left: str, right: str) -> bool:
    """Comparación tolerante de referentes para autoatribución."""

    def norm(value: str) -> str:
        value = strip_accents_lower(value).lstrip("@")
        return re.sub(r"[^a-z0-9]+", "", value)

    a = norm(left)
    b = norm(right)
    return bool(a and b and (a == b or a in b or b in a))


def _literal_mark_in_text(mark: str, text: str) -> bool:
    """True si la marca aparece como secuencia completa en la unidad actual."""
    mark_norm = " ".join(strip_accents_lower(mark).split())
    if not mark_norm or mark_norm in {"no identificado", "no identificada"}:
        return False
    text_norm = " ".join(strip_accents_lower(text).split())
    return bool(
        re.search(
            rf"(?<![a-z0-9]){re.escape(mark_norm)}(?![a-z0-9])",
            text_norm,
        )
    )


def _optative_self_mark(value: str) -> bool:
    """True si la marca expresa un optativo inequívoco del enunciador."""
    return bool(_OPTATIVE_SELF_MARK_RE.search(value))


def _first_person_mark(value: str) -> bool:
    """True si la marca contiene un pronombre posesivo/personal de 1ª persona."""
    return bool(_FIRST_PERSON_MARK_RE.search(value))
