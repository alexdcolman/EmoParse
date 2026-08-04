# ══════════════════════════════════════════════════════════════════════════════
#  emoparse.agents.emotions
#
#  Detección de emociones en frases o párrafos mediante procesamiento
#  batch.
#
#  El agente utiliza:
#  - modos de existencia y configuraciones
#  - heurísticas de inferencia
#  - actores previamente identificados por unidad
#
#  Cada fila de entrada representa una unidad textual y debe incluir la
#  columna actores. El output agrega la columna emociones, con una
#  lista estructurada de emociones detectadas.
#
#  Las filas pueden traer además dos columnas opcionales de contexto,
#  pensadas para discurso nativo digital: `contexto_hilo` (la cadena de
#  posts a los que la unidad responde) y `tecno` (los tecnolingüísticos de
#  la unidad ya extraídos). Si están presentes y no vacías, se inyectan en
#  el bloque de la unidad como material de desambiguación.
#
#  Este módulo también incluye utilidades determinísticas para construir
#  resúmenes de contexto emocional (emotion_rolling) utilizados por el
#  segundo pase de análisis (EmotionsAgentPass2).
# ══════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

import json
import re
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

import pandas as pd

from emoparse.agents.base import BaseBatchAgent
from emoparse.core.backend.base import LLMBackend
from emoparse.core.prompts import emotions as prompts
from emoparse.core.schemas import (
    CONFIGURACION_POR_ID,
    EmocionesBatchItemSchema,
    ListaEmocionesBatchSchema,
)
from emoparse.core.text import (
    sanitize_emotion_label,
    sanitize_referent_label,
)
from emoparse.genres.schema_factory import emociones_batch_schema
from emoparse.knowledge.normalization import strip_accents

if TYPE_CHECKING:
    from emoparse.genres.base import Genre


#: Valores válidos del alcance de detección (experienciadores a analizar).
EMOTION_SCOPE_VALUES: tuple[str, ...] = ("enunciador", "enunciatarios", "actores")

#: Campos de inferencia de una emoción y su saneador. Las marcas
#: (`experienciador_marca`, `fuente_marca`) NO se sanean: son transcripción
#: literal de la unidad y cualquier recorte rompería esa correspondencia.
_SANEADORES: dict[str, Callable[[str | None], str]] = {
    "tipo_emocion": sanitize_emotion_label,
    "experienciador": sanitize_referent_label,
    "fuente_inferencia": sanitize_referent_label,
}


_ENUNCIATOR_ROLE_LABELS = frozenset(
    {
        "hablante",
        "el hablante",
        "enunciador",
        "el enunciador",
        "autor",
        "el autor",
        "autora",
        "la autora",
        "autor del post",
        "el autor del post",
        "autora del post",
        "la autora del post",
    }
)
_SIENTO_QUE_RE = re.compile(r"\bsiento\s+que\b", re.IGNORECASE)
_AGRADECER_MARK_RE = re.compile(
    r"\b(?:agradezco|agradecemos|agradece|agradecen|agradeci[oó]|agradecer)\b",
    re.IGNORECASE,
)
_CARENCIA_RE = re.compile(r"\bcare(?:zco|ce|cemos|cen)\b", re.IGNORECASE)
_ESPERAR_SELF_RE = re.compile(r"\b(?:espero|esperamos)\b", re.IGNORECASE)
_INTERES_LEXEME_RE = re.compile(r"\binter(?:[eé]s|esad\w*|esa\w*)\b", re.IGNORECASE)
_CANSADO_STATE_RE = re.compile(
    r"\b(?:estoy|estamos|est[aá]|est[aá]n|estaba|estaban)\s+(?:muy\s+)?cansad\w*\b",
    re.IGNORECASE,
)
_CANSADO_MARK_RE = re.compile(
    r"\b(?:estoy|estamos|est[aá]|est[aá]n|estaba|estaban|cansad\w*)\b",
    re.IGNORECASE,
)
_OJALA_RE = re.compile(r"\bojal[aá]\b", re.IGNORECASE)
_HARTARSE_RE = re.compile(
    r"\b(?P<actor>(?:el|la|los|las)\s+[\wáéíóúüñ@.-]+"
    r"(?:\s+[\wáéíóúüñ@.-]+){0,3})\s+se\s+hart[oó]\b",
    re.IGNORECASE,
)
_CONDITIONAL_BELIEF_RE = re.compile(
    r"\bcuando\b[^.;:\n]{0,120}?\b"
    r"(?P<mark>(?:lo\s+)?(?:voy|vamos)\s+a\s+creer|"
    r"(?:lo\s+)?creer(?:é|emos))\b",
    re.IGNORECASE,
)
_EVIDENCE_SOURCE_RE = re.compile(
    r"\b(?:acciones|hechos|pruebas|resultados|evidencia)\b",
    re.IGNORECASE,
)
_COGNITIVE_MATRIX_MARK_RE = re.compile(
    r"^\s*(?:yo\s+)?(?:creo|pienso|considero|entiendo|siento|"
    r"me\s+parece)\s+que\b",
    re.IGNORECASE,
)
_UNKNOWN_MARKS = frozenset(
    {
        "",
        "no identificado",
        "no identificada",
        "no se identifica",
        "desconocido",
        "desconocida",
    }
)
_OPTATIVE_MARKS = frozenset({"ojala"})
_OPTATIVE_EMOTIONS = frozenset({"esperanza", "deseo"})
_FIRST_PERSON_MARK_RE = re.compile(
    r"\b(?:yo|me|mi|mis|m[ií]o|m[ií]a|nosotros|nosotras|nos|nuestro|"
    r"nuestra|nuestros|nuestras)\b",
    re.IGNORECASE,
)
_MAX_MARK_WORDS = 6


def sanitize_emocion(emo: dict[str, Any]) -> dict[str, Any]:
    """Devuelve la emoción con sus campos de inferencia saneados.

    Garantiza determinísticamente lo que el prompt pide: una sola categoría
    por campo, sin alternativas ("Argentina / Estado argentino"), sin
    enumeraciones ni perífrasis en `tipo_emocion`, y sin restos tipográficos
    de una generación truncada. Un campo que quedaría vacío se deja como
    estaba: es preferible una etiqueta sucia a perder la emoción.

    Resuelve además el id de configuración a su nombre canónico, de modo que
    lo que se persiste es el identificador de siempre.
    """
    out = dict(emo)
    conf = out.get("tipo_configuracion")
    if isinstance(conf, int) and not isinstance(conf, bool):
        nombre = CONFIGURACION_POR_ID.get(conf)
        if nombre:
            out["tipo_configuracion"] = nombre
    for campo, sanear in _SANEADORES.items():
        crudo = out.get(campo)
        if not isinstance(crudo, str):
            continue
        limpio = sanear(crudo)
        if limpio:
            out[campo] = limpio
    return out


def resolve_enunciator_referent(value: Any, enunciador: str) -> Any:
    """Resuelve etiquetas genéricas del emisor al referente concreto conocido."""
    if not isinstance(value, str) or not enunciador.strip():
        return value
    if _norm_clave(value) in _ENUNCIATOR_ROLE_LABELS:
        return enunciador.strip()
    return value


def _is_unknown_mark(value: Any) -> bool:
    return _norm_clave(value) in _UNKNOWN_MARKS


def _literal_mark_in_text(value: Any, text: str) -> bool:
    """True si la marca aparece como secuencia completa dentro de la unidad."""
    mark = _norm_clave(value)
    if not mark or mark in _UNKNOWN_MARKS:
        return False
    return bool(
        re.search(
            rf"(?<![a-z0-9]){re.escape(mark)}(?![a-z0-9])",
            _norm_clave(text),
        )
    )


def _same_referent(left: Any, right: Any) -> bool:
    """Compara referentes tolerando @, espacios y signos."""
    a = re.sub(r"[^a-z0-9]+", "", _norm_clave(left).lstrip("@"))
    b = re.sub(r"[^a-z0-9]+", "", _norm_clave(right).lstrip("@"))
    return bool(a and b and (a == b or a in b or b in a))


def _emotion_has_lexical_evidence(
    tipo: str,
    text: str,
) -> bool:
    """Comprueba evidencia léxica del tipo detectado sin catálogo canónico."""
    return bool(re.search(rf"\b{re.escape(tipo)}\b", _norm_clave(text)))


def _first_person_mark(value: Any) -> bool:
    return bool(_FIRST_PERSON_MARK_RE.search(str(value or "")))


def _matched_text(match: re.Match[str] | None, group: str | int = 0) -> str:
    return match.group(group).strip() if match is not None else ""


def _mark_is_clause_like(value: Any) -> bool:
    raw = str(value or "").strip()
    if not raw:
        return False
    return "\n" in raw or len(raw.split()) > _MAX_MARK_WORDS


def normalize_emotion_for_unit(
    emotion: dict[str, Any],
    *,
    text: str,
    enunciador: str,
) -> dict[str, Any] | None:
    """Normaliza estructura y evidencia sin crear emociones ausentes.

    Las correcciones semánticas se limitan a casos donde el modelo ya produjo
    una emoción. Este postprocesado nunca completa una detección omitida.
    """
    out = dict(emotion)
    out["experienciador"] = resolve_enunciator_referent(
        out.get("experienciador"),
        enunciador,
    )
    tipo = _norm_clave(out.get("tipo_emocion"))
    same_as_enunciator = bool(enunciador.strip()) and _same_referent(
        out.get("experienciador"),
        enunciador,
    )
    mark_raw = str(out.get("experienciador_marca", "") or "").strip()
    mark = _norm_clave(mark_raw)

    agradecer = _AGRADECER_MARK_RE.search(text)
    if (
        agradecer is not None
        and tipo in {"esperanza", "gratitud"}
        and (_AGRADECER_MARK_RE.search(mark_raw) or mark in {"agradezco", "agradecemos"})
    ):
        gratitud = "gratitud"
        out["tipo_emocion"] = gratitud
        out["experienciador_marca"] = _matched_text(agradecer)
        out["modo_existencia"] = "realizada"
        out["tipo_configuracion"] = "ordenado_alrededor_de_verbos_psicologicos"
        tipo = _norm_clave(gratitud)
        mark_raw = str(out["experienciador_marca"])
        mark = _norm_clave(mark_raw)

    esperar = _ESPERAR_SELF_RE.search(text)
    if esperar is not None and same_as_enunciator:
        if tipo in _OPTATIVE_EMOTIONS:
            esperanza = "esperanza"
            out["tipo_emocion"] = esperanza
            out["experienciador_marca"] = _matched_text(esperar)
            out["modo_existencia"] = "realizada"
            out["tipo_configuracion"] = "ordenado_alrededor_de_verbos_psicologicos"
            tipo = _norm_clave(esperanza)
            mark_raw = str(out["experienciador_marca"])
            mark = _norm_clave(mark_raw)
        elif tipo == "interes" and (
            mark == _norm_clave(_matched_text(esperar)) or not _INTERES_LEXEME_RE.search(text)
        ):
            return None

    if _CARENCIA_RE.search(mark_raw):
        return None

    if _SIENTO_QUE_RE.search(text):
        matrix_mark = mark in {"siento", "siento que"} or bool(
            _COGNITIVE_MATRIX_MARK_RE.search(mark_raw)
        )
        if matrix_mark and not _emotion_has_lexical_evidence(
            tipo,
            text,
        ):
            return None

    ojala = _OJALA_RE.search(text)
    if mark in _OPTATIVE_MARKS or (ojala is not None and mark == _norm_clave(_matched_text(ojala))):
        if tipo not in _OPTATIVE_EMOTIONS:
            return None
        esperanza = "esperanza"
        out["tipo_emocion"] = esperanza
        out["experienciador_marca"] = _matched_text(ojala) or mark_raw
        out["modo_existencia"] = "realizada"
        out["tipo_configuracion"] = "cualificacion_por_indicadores_cognitivos"
        tipo = _norm_clave(esperanza)
        mark_raw = str(out["experienciador_marca"])
        mark = _norm_clave(mark_raw)

    if (
        ojala is not None
        and same_as_enunciator
        and _is_unknown_mark(mark_raw)
        and not _emotion_has_lexical_evidence(tipo, text)
    ):
        return None

    if (
        tipo == "hartazgo"
        and same_as_enunciator
        and _CANSADO_STATE_RE.search(text)
        and _CANSADO_MARK_RE.search(mark_raw)
    ):
        out["modo_existencia"] = "realizada"
        out["tipo_configuracion"] = "sostenido_en_adjetivos"

    if tipo == "hartazgo":
        for hartarse in _HARTARSE_RE.finditer(text):
            actor = _matched_text(hartarse, "actor")
            if not _same_referent(out.get("experienciador"), actor):
                continue
            out["experienciador_marca"] = actor
            out["modo_existencia"] = "realizada"
            out["tipo_configuracion"] = "ordenado_alrededor_de_verbos_psicologicos"
            mark_raw = actor
            mark = _norm_clave(mark_raw)
            break

    belief = _CONDITIONAL_BELIEF_RE.search(text)
    if tipo == "desconfianza" and belief is not None:
        out["experienciador_marca"] = _matched_text(belief, "mark")
        out["modo_existencia"] = "realizada"
        out["tipo_configuracion"] = "cualificacion_por_indicadores_cognitivos"
        if _is_unknown_mark(out.get("fuente_marca")):
            source_match = _EVIDENCE_SOURCE_RE.search(text[: belief.start("mark")])
            source = _matched_text(source_match) or "no identificado"
            out["fuente_marca"] = source
            out["fuente_inferencia"] = source
        mark_raw = str(out["experienciador_marca"])
        mark = _norm_clave(mark_raw)

    if _mark_is_clause_like(mark_raw):
        lexical = _emotion_has_lexical_evidence(tipo, text)
        if same_as_enunciator and _COGNITIVE_MATRIX_MARK_RE.search(mark_raw):
            if not lexical:
                return None
            out["experienciador"] = "no identificado"
            out["experienciador_marca"] = "no identificado"
            out["tipo_configuracion"] = "sostenido_en_sustantivos"
            same_as_enunciator = False
            mark_raw = "no identificado"
            mark = _norm_clave(mark_raw)
        else:
            out["experienciador_marca"] = "no identificado"
            mark_raw = "no identificado"
            mark = _norm_clave(mark_raw)

    if not _literal_mark_in_text(mark_raw, text) and not _is_unknown_mark(mark_raw):
        lexical = _emotion_has_lexical_evidence(tipo, text)
        if same_as_enunciator and not _first_person_mark(mark_raw):
            if not lexical:
                return None
            out["experienciador"] = "no identificado"
        out["experienciador_marca"] = "no identificado"

    source_mark = str(out.get("fuente_marca", "") or "").strip()
    if _mark_is_clause_like(source_mark) or (
        not _literal_mark_in_text(source_mark, text) and not _is_unknown_mark(source_mark)
    ):
        out["fuente_marca"] = "no identificado"

    return out


def dedupe_emociones(emociones: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Elimina duplicados por experienciador, emoción y modo de existencia."""
    vistas: set[tuple[str, str, str]] = set()
    out: list[dict[str, Any]] = []
    for emotion in emociones:
        key = (
            _norm_clave(emotion.get("experienciador")),
            _norm_clave(emotion.get("tipo_emocion")),
            _norm_clave(emotion.get("modo_existencia")),
        )
        if key in vistas:
            continue
        vistas.add(key)
        out.append(emotion)
    return out


def order_emotions_by_evidence(
    emociones: list[dict[str, Any]],
    text: str,
) -> list[dict[str, Any]]:
    """Ordena por la primera marca literal para conservar el recorrido textual."""
    text_norm = _norm_clave(text)

    def key(item: tuple[int, dict[str, Any]]) -> tuple[int, int]:
        index, emotion = item
        mark = _norm_clave(emotion.get("experienciador_marca"))
        position = text_norm.find(mark) if mark and mark not in _UNKNOWN_MARKS else -1
        return (position if position >= 0 else len(text_norm) + index, index)

    return [emotion for _, emotion in sorted(enumerate(emociones), key=key)]


def _norm_clave(valor: Any) -> str:
    """Normaliza un campo para comparar identidad, literalidad y aliases."""
    text = strip_accents(str(valor or "").strip().lower())
    return " ".join(text.split())


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

    Procesa frases o párrafos utilizando modos de existencia, configuraciones,
    heurísticas de inferencia y los actores identificados en cada unidad.

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
        heuristicas: str,
        configuraciones: str = "",
        titulo: str = "",
        tipo_discurso: str = "",
        enunciador: str = "",
        enunciatarios: str = "",
        auditorio: str = "",
        resumen: str = "",
        contexto_genero: str = "",
        modos_existencia: str = "",
        emotion_scope: tuple[str, ...] | None = None,
        retry_config: Any | None = None,
        genre: Genre | None = None,
    ) -> None:
        """
        Args:
            backend: Backend LLM utilizado para generación estructurada.
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
            modos_existencia: Catálogo formateado de modos de existencia.
            emotion_scope: Restricción opcional de experienciadores a analizar.
                 Si es None o vacío, se analizan emociones de cualquier experienciador.
            retry_config: Política de reintentos ante errores transitorios.
            genre: Configuración opcional de género discursivo. Puede
                ajustar parámetros como BATCH_SIZE y sustituir el template
                del system prompt vía `prompt_overrides`.
        """
        self._heuristicas = heuristicas
        self._configuraciones = configuraciones
        self._titulo = titulo
        self._tipo_discurso = tipo_discurso
        self._enunciador = enunciador
        self._enunciatarios = enunciatarios
        self._auditorio = auditorio
        self._resumen = resumen
        self._contexto_genero = contexto_genero
        self._modos_existencia = modos_existencia
        self._emotion_scope = tuple(emotion_scope) if emotion_scope else ()
        self._genre = genre

        if genre is not None:
            restricted = emociones_batch_schema(genre)
            if restricted is not None:
                self.SCHEMA = restricted  # type: ignore[misc]

        if genre is not None and "emotions" in genre.batch_size:
            self.BATCH_SIZE = genre.batch_size["emotions"]  # type: ignore[misc]

        super().__init__(backend, retry_config=retry_config)

    # ── Hooks de BaseBatchAgent ──────────────────────────────────────────────

    def _build_system(self) -> str:
        template = "emotions_system"
        if self._genre is not None:
            template = self._genre.prompt_overrides.get("emotions", template)
        return prompts.render_system(
            heuristicas=self._heuristicas,
            configuraciones=self._configuraciones,
            titulo=self._titulo,
            tipo_discurso=self._tipo_discurso,
            enunciador=self._enunciador,
            enunciatarios=self._enunciatarios,
            auditorio=self._auditorio,
            resumen=self._resumen,
            contexto_genero=self._contexto_genero,
            modos_existencia=self._modos_existencia,
            alcance=self._alcance_text(),
            template=template,
        )

    def _build_user(self, batch: pd.DataFrame) -> str:
        bloques: list[str] = []
        for i, (_, row) in enumerate(batch.iterrows()):
            codigo = str(row.get("codigo", ""))
            frase = str(row.get("frase", row.get("contenido", "")))
            actores_str = self._format_actores(row.get("actores"))
            contexto_hilo = _opt_str(row.get("contexto_hilo"))
            tecno = _opt_str(row.get("tecno"))
            media_desc = _opt_str(row.get("media_desc"))

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

            bloques.append("\n".join(partes))

        unidades_block = "\n\n".join(bloques)
        return prompts.render_user(unidades_block=unidades_block)

    def _map_item_to_columns(
        self,
        item: EmocionesBatchItemSchema,
        row: pd.Series,
    ) -> dict[str, Any]:
        saneadas: list[dict[str, Any]] = []
        text = str(row.get("frase", row.get("contenido", "")))
        enunciador = getattr(self, "_enunciador", "")
        for emocion in item.emociones:
            limpia = sanitize_emocion(emocion.model_dump())
            normalizada = normalize_emotion_for_unit(
                limpia,
                text=text,
                enunciador=enunciador,
            )
            if normalizada is not None:
                saneadas.append(normalizada)

        emociones_json = json.dumps(
            order_emotions_by_evidence(dedupe_emociones(saneadas), text),
            ensure_ascii=False,
        )
        return {"emociones": emociones_json}

    # ── Helpers ──────────────────────────────────────────────────────────────

    def _alcance_text(self) -> str:
        """Frase legible del alcance, o cadena vacía si no hay restricción."""
        return alcance_text(self._emotion_scope, self._enunciador, self._enunciatarios)

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


def _opt_str(value: Any) -> str:
    """String de una celda opcional: None/NaN → ''."""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    return str(value).strip()


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

    sorted_df = df_with_emotions.sort_values(["codigo", "unit_idx"], kind="stable").reset_index(
        drop=True
    )

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

    sorted_df = df_with_emotions.sort_values(["codigo", "unit_idx"], kind="stable").reset_index(
        drop=True
    )

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
