# ══════════════════════════════════════════════════════════════════════════════
#  emoparse.agents.emotions
#
#  Detección de emociones en frases o párrafos mediante procesamiento
#  batch.
#
#  El agente utiliza:
#  - ontología emocional
#  - heurísticas de inferencia
#  - actores previamente identificados por unidad
#
#  Cada fila de entrada representa una unidad textual y debe incluir la
#  columna actores. El output agrega la columna emociones, con una
#  lista estructurada de emociones detectadas.
#
#  Este módulo también incluye utilidades determinísticas para construir
#  resúmenes de contexto emocional (emotion_rolling) utilizados por el
#  segundo pase de análisis (EmotionsAgentPass2).
# ══════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

import pandas as pd

from emoparse.agents.base import BaseBatchAgent
from emoparse.core.backend.base import LLMBackend
from emoparse.core.prompts import emotions as prompts
from emoparse.core.schemas import (
    EmocionesBatchItemSchema,
    ListaEmocionesBatchSchema,
)

if TYPE_CHECKING:
    from emoparse.genres.base import Genre


#: Valores válidos del alcance de detección (experienciadores a analizar).
EMOTION_SCOPE_VALUES: tuple[str, ...] = ("enunciador", "enunciatarios", "actores")


def alcance_text(
    emotion_scope: tuple[str, ...] | None,
    enunciador: str,
    enunciatarios: str,
) -> str:
    """Frase legible del alcance de detección, o cadena vacía si no hay límite.

    Compartida por los dos pases para que el mismo `emotion_scope` produzca
    la misma restricción en ambos prompts.
    """
    if not emotion_scope:
        return ""
    partes: list[str] = []
    if "enunciador" in emotion_scope:
        partes.append(f"el enunciador ({enunciador or 'no identificado'})")
    if "enunciatarios" in emotion_scope:
        detalle = f" ({enunciatarios})" if enunciatarios else ""
        partes.append(f"los enunciatarios del discurso{detalle}")
    if "actores" in emotion_scope:
        partes.append(
            "otros actores mencionados en la unidad, distintos del "
            "enunciador y de los enunciatarios"
        )
    return "; ".join(partes)


class EmotionsAgent(BaseBatchAgent[ListaEmocionesBatchSchema]):
    """Primer pase de detección de emociones.

    Procesa frases o párrafos utilizando ontología emocional, heurísticas
    de inferencia y los actores previamente identificados en cada unidad.

    Agrega la columna `emociones`, que contiene una lista JSON con
    `experienciador`, `tipo_emocion`, `modo_existencia`, `fuente_marca`,
    `fuente_inferencia`, `tipo_configuracion` y `justificacion`.

    El parámetro `emotion_scope` restringe qué experienciadores se analizan.
    Si es None o vacío se detectan emociones de cualquier actor. Si contiene
    uno o más de `EMOTION_SCOPE_VALUES`, el prompt instruye al modelo a
    devolver únicamente emociones cuyo experienciador caiga en esas clases.
    """

    NAME = "emotions"
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
        emotion_scope: tuple[str, ...] | None = None,
        retry_config: Any | None = None,
        genre: "Genre | None" = None,
    ) -> None:
        """
        Args:
            backend: Backend LLM utilizado para generación estructurada.
            ontologia: Ontología emocional utilizada por el agente.
            heuristicas: Reglas heurísticas para inferencia emocional.
            configuraciones: Texto formateado con las 8 configuraciones del
                simulacro emocional (TIPO_CONF). Si es string vacío, el
                template lo renderiza como bloque vacío.
            titulo: Título del discurso.
            tipo_discurso: Tipo o clasificación del discurso.
            enunciador: Sujeto principal de enunciación.
            enunciatarios: Destinatarios o audiencia del discurso.
            auditorio: Auditorio (destinatario directo, quienes efectivamente
                escuchan o leen el discurso) del discurso, ya formateado
                como texto. Vacío si no se conoce.
            emotion_scope: Restricción opcional de experienciadores a analizar.
                 Si es None o vacío, se analizan emociones de cualquier experienciador.
            retry_config: Política de reintentos ante errores transitorios.
            genre: Configuración opcional de género discursivo. Puede
                ajustar parámetros como BATCH_SIZE.
        """
        self._ontologia = ontologia
        self._heuristicas = heuristicas
        self._configuraciones = configuraciones
        self._titulo = titulo
        self._tipo_discurso = tipo_discurso
        self._enunciador = enunciador
        self._enunciatarios = enunciatarios
        self._auditorio = auditorio
        self._emotion_scope = tuple(emotion_scope) if emotion_scope else ()
        self._genre = genre

        if genre is not None and "emotions" in genre.batch_size:
            self.BATCH_SIZE = genre.batch_size["emotions"]  # type: ignore[misc]

        super().__init__(backend, retry_config=retry_config)

    # ── Hooks de BaseBatchAgent ──────────────────────────────────────────────

    def _build_system(self) -> str:
        return prompts.render_system(
            ontologia=self._ontologia,
            heuristicas=self._heuristicas,
            configuraciones=self._configuraciones,
            titulo=self._titulo,
            tipo_discurso=self._tipo_discurso,
            enunciador=self._enunciador,
            enunciatarios=self._enunciatarios,
            auditorio=self._auditorio,
            alcance=self._alcance_text(),
        )

    def _build_user(self, batch: pd.DataFrame) -> str:
        bloques: list[str] = []
        for i, (_, row) in enumerate(batch.iterrows()):
            codigo = str(row.get("codigo", ""))
            frase = str(row.get("frase", row.get("contenido", "")))
            actores_str = self._format_actores(row.get("actores"))

            bloques.append(
                f"UNIDAD [{i}] (codigo={codigo}):\n"
                f"FRASE: {frase}\n"
                f"ACTORES IDENTIFICADOS: {actores_str}"
            )

        unidades_block = "\n\n".join(bloques)
        return prompts.render_user(unidades_block=unidades_block)

    def _map_item_to_columns(
        self,
        item: EmocionesBatchItemSchema,
        row: pd.Series,
    ) -> dict[str, Any]:
        emociones_json = json.dumps(
            [e.model_dump() for e in item.emociones],
            ensure_ascii=False,
        )
        return {"emociones": emociones_json}

    # ── Helpers ──────────────────────────────────────────────────────────────

    def _alcance_text(self) -> str:
        """Frase legible del alcance, o cadena vacía si no hay restricción."""
        return alcance_text(
            self._emotion_scope, self._enunciador, self._enunciatarios
        )

    @staticmethod
    def _format_actores(actores_raw: Any) -> str:
        """Convierte la representación de actores a texto legible.

        Acepta JSON serializado, listas ya parseadas o valores nulos, y
        devuelve una representación compacta adecuada para el prompt.

        Nota de mantenimiento:
            La lógica está duplicada respecto de `EmotionsAgentPass2`.
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


# ══════════════════════════════════════════════════════════════════════════════
#  Utilidades para construir contexto emocional determinístico
# ══════════════════════════════════════════════════════════════════════════════

def compute_emotion_rolling_summary(
    df_with_emotions: pd.DataFrame,
    *,
    window: int = 5,
) -> pd.DataFrame:
    """Construye un resumen rolling de emociones previas por frase.

    Recibe un DataFrame con la columna `emociones` ya generada por el primer
    pase y agrega `emotion_rolling`, que resume las emociones de las últimas
    `window` frases anteriores dentro del mismo discurso.

    Determinística: el resultado depende solo de (`codigo`, `unit_idx`) y del
    contenido de `emociones`, no del orden de iteración del DataFrame.
    """
    if df_with_emotions.empty:
        out = df_with_emotions.copy()
        out["emotion_rolling"] = pd.Series(dtype="object")
        return out

    sorted_df = df_with_emotions.sort_values(
        ["codigo", "unit_idx"], kind="stable"
    ).reset_index(drop=True)

    rollings: list[str] = []
    history: list[str] = []
    current_codigo: str | None = None

    for _, row in sorted_df.iterrows():
        codigo = str(row["codigo"])
        if codigo != current_codigo:
            history = []
            current_codigo = codigo

        if not history:
            rollings.append("(sin emociones previas en este discurso)")
        else:
            rollings.append("\n".join(history[-window:]))

        emociones_raw = row.get("emociones")
        emociones_str = _format_frase_for_history(
            emociones_raw,
            unit_idx=int(row["unit_idx"]),
        )
        if emociones_str:
            history.append(emociones_str)

    sorted_df = sorted_df.copy()
    sorted_df["emotion_rolling"] = rollings

    if not df_with_emotions.index.equals(sorted_df.index):
        key_cols = ["codigo", "unit_idx"]
        merged = df_with_emotions.merge(
            sorted_df[[*key_cols, "emotion_rolling"]],
            on=key_cols,
            how="left",
        )
        return merged
    return sorted_df


def compute_emotion_full_summary(
    df_with_emotions: pd.DataFrame,
) -> pd.DataFrame:
    """Construye un resumen completo de emociones previas por frase.

    A diferencia de `compute_emotion_rolling_summary`, incluye todas las
    emociones anteriores del discurso en lugar de una ventana deslizante.
    Mantiene las mismas garantías de determinismo y produce la misma columna
    de salida: `emotion_rolling`.
    """
    if df_with_emotions.empty:
        out = df_with_emotions.copy()
        out["emotion_rolling"] = pd.Series(dtype="object")
        return out

    sorted_df = df_with_emotions.sort_values(
        ["codigo", "unit_idx"], kind="stable"
    ).reset_index(drop=True)

    summaries: list[str] = []
    history: list[str] = []
    current_codigo: str | None = None

    for _, row in sorted_df.iterrows():
        codigo = str(row["codigo"])
        if codigo != current_codigo:
            history = []
            current_codigo = codigo

        if not history:
            summaries.append("(sin emociones previas en este discurso)")
        else:
            summaries.append("\n".join(history))

        emociones_raw = row.get("emociones")
        emociones_str = _format_frase_for_history(
            emociones_raw,
            unit_idx=int(row["unit_idx"]),
        )
        if emociones_str:
            history.append(emociones_str)

    sorted_df = sorted_df.copy()
    sorted_df["emotion_rolling"] = summaries

    if not df_with_emotions.index.equals(sorted_df.index):
        key_cols = ["codigo", "unit_idx"]
        merged = df_with_emotions.merge(
            sorted_df[[*key_cols, "emotion_rolling"]],
            on=key_cols,
            how="left",
        )
        return merged
    return sorted_df


def _format_frase_for_history(
    raw: Any,
    *,
    unit_idx: int,
) -> str | None:
    """Formatea las emociones de una frase para el historial contextual."""
    if raw is None or (isinstance(raw, float) and pd.isna(raw)):
        return None
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            return None
    else:
        parsed = raw
    if not isinstance(parsed, list) or not parsed:
        return None
    parts: list[str] = []
    for emo in parsed:
        if not isinstance(emo, dict):
            continue
        exp = emo.get("experienciador", "?")
        tipo = emo.get("tipo_emocion", "?")
        modo = emo.get("modo_existencia", "?")
        parts.append(f"{exp} siente {tipo} ({modo})")
    if not parts:
        return None
    return f"[unidad {unit_idx}] " + "; ".join(parts)
