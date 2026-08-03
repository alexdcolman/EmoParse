# ══════════════════════════════════════════════════════════════════════════════
#  emoparse.agents.emotions_pass2
#
#  Segundo pase de detección de emociones con contexto previo.
#
#  El output mantiene el mismo schema estructural que el pase 1
#  (ListaEmocionesBatchSchema), permitiendo que ambos resultados sean
#  consumidos de forma intercambiable según el flujo downstream.
# ══════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any, Literal

import pandas as pd
from loguru import logger

from emoparse.agents.base import BaseBatchAgent
from emoparse.agents.emotions import (
    alcance_text,
    canonical_emotion,
    dedupe_emociones,
    sanitize_emocion,
)
from emoparse.core.backend.base import LLMBackend
from emoparse.core.backend.retry import RetryConfig
from emoparse.core.prompts import emotions_pass2 as prompts
from emoparse.core.schemas import (
    EmocionesBatchItemSchema,
    ListaEmocionesBatchSchema,
)
from emoparse.genres.schema_factory import emociones_batch_schema

if TYPE_CHECKING:
    from emoparse.genres.base import Genre


#: Tope de caracteres del contexto previo inyectado por unidad. El rolling no
#: tenía cota propia (a diferencia de `contexto_hilo`) y crecía con el largo
#: del hilo o del discurso, comiéndose el presupuesto de generación. El pase 2
#: es la stage con menos margen (arrastra las heurísticas de los dos pases más
#: el contexto previo), así que la cota es estricta. Se conserva la cola: las
#: emociones más recientes son las que desambiguan.
_MAX_ROLLING_CHARS = 300


class EmotionsAgentPass2(BaseBatchAgent[ListaEmocionesBatchSchema]):
    """Segundo pase de análisis de emociones con contexto previo.

    Espera un DataFrame similar al del primer pase, pero con la columna
    adicional `emotion_rolling`, que resume en texto las frases anteriores
    del mismo discurso (referencia auxiliar para desambiguar, no evidencia);
    en géneros con contexto de hilo, esa columna trae las emociones ya
    detectadas en los posts padre. Las filas pueden traer además las mismas
    columnas opcionales de contexto que el pase 1, pensadas para discurso
    nativo digital: `contexto_hilo` (la cadena de posts a los que la unidad
    responde), `tecno` (los tecnolingüísticos de la unidad) y `media_desc`
    (descripciones generadas de la media adjunta).

    `emotion_scope` restringe qué experienciadores se analizan, con la misma
    semántica que en el pase 1. Pasar el mismo alcance a ambos pases mantiene
    el filtro coherente de punta a punta: el explode prioriza el pase 2, así
    que si el pase 1 se acota pero el pase 2 no, el alcance se perdería.

    Args:
        context_mode: `"rolling"` usa una ventana deslizante de frases
            recientes; `"full"` usa todo el historial previo del discurso.
    """

    NAME = "emotions_pass2"
    SCHEMA = ListaEmocionesBatchSchema
    OUTPUT_COLUMNS = ("emociones",)
    BATCH_SIZE = 3

    def __init__(
        self,
        backend: LLMBackend,
        ontologia: str,
        heuristicas: str,
        configuraciones: str = "",
        titulo: str = "",
        tipo_discurso: str = "",
        enunciador: str = "",
        enunciatarios: str = "",
        auditorio: str = "",
        resumen: str = "",
        emotion_scope: tuple[str, ...] | None = None,
        emotion_alias_lookup: dict[str, str] | None = None,
        context_mode: Literal["rolling", "full"] = "rolling",
        retry_config: RetryConfig | None = None,
        genre: Genre | None = None,
    ) -> None:
        """
        Args:
            backend: Backend LLM utilizado para generación estructurada.
            ontologia: Ontología emocional utilizada por el prompt.
            heuristicas: Reglas heurísticas de interpretación emocional.
            configuraciones: Texto formateado con las 8 configuraciones del
                simulacro emocional (TIPO_CONF). Si es string vacío, el
                template lo renderiza como bloque sin contenido.
            titulo: Título del discurso.
            tipo_discurso: Tipo o clasificación del discurso.
            enunciador: Sujeto principal de enunciación del discurso.
            enunciatarios: Destinatarios o audiencias del discurso.
            auditorio: Auditorio (destinatario directo, quienes efectivamente
                escuchan o leen el discurso) del discurso, ya formateado
                como texto. Vacío si no se conoce.
            emotion_scope: Restricción de experienciadores a analizar. Si se
                pasa, el prompt enfatiza que solo se consideren emociones
                relacionadas con esos actores específicos. Si no se pasa, se
                analizan emociones de cualquier experienciador presente.
            emotion_alias_lookup: Mapa de nombres/aliases a emoción canónica.
                Las etiquetas ajenas se descartan antes de persistirse.
            context_mode: Estrategia de construcción del contexto previo
                (`"rolling"` o `"full"`).
            retry_config: Política de reintentos ante errores transitorios.
            genre: Configuración opcional de género discursivo. Puede
                ajustar parámetros como `BATCH_SIZE`.
        """
        self._ontologia = ontologia
        self._heuristicas = heuristicas
        self._configuraciones = configuraciones
        self._titulo = titulo
        self._tipo_discurso = tipo_discurso
        self._enunciador = enunciador
        self._enunciatarios = enunciatarios
        self._auditorio = auditorio
        self._resumen = resumen
        self._emotion_scope = tuple(emotion_scope) if emotion_scope else ()
        self._emotion_alias_lookup = emotion_alias_lookup or {}
        self._context_mode = context_mode
        self._genre = genre

        if genre is not None:
            restricted = emociones_batch_schema(genre)
            if restricted is not None:
                self.SCHEMA = restricted  # type: ignore[misc]

            if "emotions_pass2" in genre.batch_size:
                self.BATCH_SIZE = genre.batch_size["emotions_pass2"]  # type: ignore[misc]
            elif "emotions" in genre.batch_size:
                self.BATCH_SIZE = genre.batch_size["emotions"]  # type: ignore[misc]

        super().__init__(
            backend,
            retry_config=retry_config,
        )

    # ── Hooks de BaseBatchAgent ──────────────────────────────────────────────

    def _build_system(self) -> str:
        template = "emotions_pass2_system"
        if self._genre is not None:
            template = self._genre.prompt_overrides.get("emotions_pass2", template)
        return prompts.render_system(
            ontologia=self._ontologia,
            heuristicas=self._heuristicas,
            configuraciones=self._configuraciones,
            titulo=self._titulo,
            tipo_discurso=self._tipo_discurso,
            enunciador=self._enunciador,
            enunciatarios=self._enunciatarios,
            auditorio=self._auditorio,
            resumen=self._resumen,
            alcance=alcance_text(self._emotion_scope, self._enunciador, self._enunciatarios),
            template=template,
        )

    def _build_user(self, batch: pd.DataFrame) -> str:
        hilo_genre = self._genre is not None and self._genre.context_unit == "hilo"
        rolling_label = (
            "EMOCIONES EN EL HILO (posts padre; referencia auxiliar, NO evidencia de este post):"
            if hilo_genre
            else "EMOCIONES EN FRASES PREVIAS (referencia auxiliar, NO evidencia de esta frase):"
        )
        bloques: list[str] = []
        for i, (_, row) in enumerate(batch.iterrows()):
            codigo = str(row.get("codigo", ""))
            frase = str(row.get("frase", row.get("contenido", "")))
            actores_str = self._format_actores(row.get("actores"))
            contexto_hilo = _opt_str(row.get("contexto_hilo"))
            tecno = _opt_str(row.get("tecno"))
            media_desc = _opt_str(row.get("media_desc"))
            rolling = _opt_str(row.get("emotion_rolling"))
            if len(rolling) > _MAX_ROLLING_CHARS:
                rolling = "(...)\n" + rolling[-_MAX_ROLLING_CHARS:]
            if not rolling:
                rolling = "(sin emociones previas)"

            partes = [f"UNIDAD [{i}] (codigo={codigo}):"]
            if contexto_hilo:
                partes.append(
                    "CONTEXTO DEL HILO (posts a los que responde; solo para "
                    "desambiguar, NO fuente de emociones):\n"
                    f"{contexto_hilo}"
                )
            partes.append(f"FRASE: {frase}")
            partes.append(f"ACTORES IDENTIFICADOS: {actores_str}")
            if tecno:
                partes.append(f"TECNOLINGÜÍSTICOS DE LA UNIDAD: {tecno}")
            if media_desc:
                partes.append(
                    "MEDIA ADJUNTA (descripción generada; el post es un "
                    f"enunciado compuesto texto+imagen):\n{media_desc}"
                )
            partes.append(f"{rolling_label}\n{rolling}")

            bloques.append("\n".join(partes))
        unidades_block = "\n\n".join(bloques)
        return prompts.render_user(unidades_block=unidades_block)

    def _map_item_to_columns(
        self,
        item: EmocionesBatchItemSchema,
        row: pd.Series,
    ) -> dict[str, Any]:
        saneadas: list[dict[str, Any]] = []
        for emocion in item.emociones:
            limpia = sanitize_emocion(emocion.model_dump())
            canonica = canonical_emotion(limpia.get("tipo_emocion"), self._emotion_alias_lookup)
            if canonica is None:
                logger.warning(
                    "[emotions_pass2] Emoción fuera de ontología descartada "
                    f"(unit_idx={item.unit_idx}): {limpia.get('tipo_emocion')!r}"
                )
                continue
            limpia["tipo_emocion"] = canonica
            saneadas.append(limpia)
        emociones_json = json.dumps(
            dedupe_emociones(saneadas),
            ensure_ascii=False,
        )
        return {"emociones": emociones_json}

    # ── Helpers ──────────────────────────────────────────────────────────────

    @staticmethod
    def _format_actores(actores_raw: Any) -> str:
        """Convierte la representación de actores a texto legible.

        Acepta JSON serializado, listas ya parseadas o valores nulos, y
        devuelve una representación compacta adecuada para el prompt.

        Nota de mantenimiento:
            La lógica está duplicada respecto de `EmotionsAgent` (pase 1).
            Si otro agente requiere el mismo helper, puede evaluarse su
            extracción a un módulo compartido para evitar divergencias.
        """
        if actores_raw is None or (isinstance(actores_raw, float) and pd.isna(actores_raw)):
            return "(no procesados)"
        if isinstance(actores_raw, str):
            try:
                parsed = json.loads(actores_raw)
            except json.JSONDecodeError:
                return f"(error de parseo: {actores_raw[:60]})"
        else:
            parsed = actores_raw

        if not isinstance(parsed, list) or not parsed:
            return "(ninguno identificado)"

        formatted = []
        for a in parsed:
            if isinstance(a, dict):
                nombre = a.get("actor", "?")
                tipo = a.get("tipo", "?")
                formatted.append(f"{nombre} ({tipo})")
        return "; ".join(formatted) if formatted else "(ninguno)"


def _opt_str(value: Any) -> str:
    """String de una celda opcional: None/NaN → ''.

    Nota de mantenimiento:
        Duplicado respecto de `emoparse.agents.emotions` (pase 1), como
        `_format_actores`: si un tercer agente lo requiere, evaluar su
        extracción a un módulo compartido.
    """
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    return str(value).strip()
