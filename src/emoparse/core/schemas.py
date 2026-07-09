# ══════════════════════════════════════════════════════════════════════════════
#  emoparse.core.schemas
#
#  Schemas Pydantic v2 de salida del LLM.
# ══════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

from typing import Literal, Annotated

from pydantic import BaseModel, ConfigDict, Field, RootModel


# ══════════════════════════════════════════════════════════════════════════════
#  Convención: todos los schemas tienen extra="forbid"
#  Se define una base común para no repetir el ConfigDict.
# ══════════════════════════════════════════════════════════════════════════════

class StrictBase(BaseModel):
    """Base para todos los schemas de salida LLM.

    ConfigDict:
    - extra="forbid": rechaza campos no declarados.
    - populate_by_name=True: acepta nombre y alias.
    - str_strip_whitespace=True: trim automático de strings.
    """
    model_config = ConfigDict(
        extra="forbid",
        populate_by_name=True,
        str_strip_whitespace=True,
    )


# ══════════════════════════════════════════════════════════════════════════════
#  Metadatos
# ══════════════════════════════════════════════════════════════════════════════

class MetadatosSchema(StrictBase):
    """Tipo de discurso + lugar geográfico."""
    tipo_discurso: str = Field(
        description="Tipo de discurso identificado (ej. asunción, anuncio de medida, "
                    "discurso de campaña, etc.)",
    )
    tipo_discurso_justificacion: str = Field(
        description="Justificación breve del tipo identificado, basada en el texto",
    )
    ciudad: str = Field(
        description="Ciudad desde donde se emite el discurso. "
                    "Si no se puede determinar, devolver 'no identificado'",
    )
    provincia: str = Field(
        description="Provincia o estado. Si no se puede determinar, "
                    "devolver 'no identificado'",
    )
    pais: str = Field(
        description="País. Si no se puede determinar, devolver 'no identificado'",
    )
    lugar_justificacion: str = Field(
        description="Justificación breve del lugar identificado",
    )


# ══════════════════════════════════════════════════════════════════════════════
#  Enunciación
# ══════════════════════════════════════════════════════════════════════════════

#: Roles enunciativos consolidados de los géneros del proyecto.
TipoEnunciatario = Literal[
    # Discurso político (Verón)
    "prodestinatario",
    "paradestinatario",
    "contradestinatario",
    # Tuit / redes sociales
    "seguidor",
    "oponente",
    "audiencia_general",
    # Periodismo / discurso público
    "audiencia_objetivo",
    "fuente",
    "oponente_ideologico",
]


class EnunciadorSchema(StrictBase):
    """Quién emite el discurso. Persona, institución o colectivo."""
    actor: str = Field(
        description="Nombre o denominación del enunciador. "
                    "Si es implícito, inferir del contexto. "
                    "Si es totalmente indeterminable: 'no identificado'.",
    )
    justificacion: str = Field(
        description="Justificación breve de la identificación, citando "
                    "elementos del texto.",
    )


class EnunciatarioSchema(StrictBase):
    """Destinatario del discurso.
    
    Campo `tipo` restringido vía Literal a roles válidos.
    """
    actor: str = Field(
        description="Actor o grupo destinatario. Si es genérico: "
                    "'audiencia general', 'simpatizantes', etc.",
    )
    tipo: TipoEnunciatario = Field(  # type: ignore[valid-type]
        description="Rol enunciativo según el género del discurso.",
    )
    justificacion: str = Field(
        description="Justificación breve, citando elementos del texto.",
    )


class AuditorioSchema(StrictBase):
    """Auditorio: destinatario DIRECTO del discurso (quien lo escucha o lee).

    Se distingue de los enunciatarios (pro/para/contradestinatario), que son
    posiciones de destinación construidas por el discurso. El auditorio es el
    público concreto presente en la situación de enunciación.
    """
    actor: str = Field(
        description="Auditorio directo del discurso (p. ej. 'los presentes en "
                    "el Foro de Davos', 'la cadena nacional'). Si es "
                    "indeterminable: 'no identificado'.",
    )
    justificacion: str = Field(
        description="Justificación breve, citando elementos del texto o de la "
                    "situación de enunciación.",
    )


class ColectivoIdentificacionSchema(StrictBase):
    """Colectivo con el que el enunciador se identifica o al que se adscribe.

    La `clase` se valida contra la ontología de colectivos del género (no es un
    Literal cerrado en el schema para no multiplicar variantes por tipo de
    discurso). Las clases inválidas se descartan al persistir.
    """
    clase: str = Field(
        description="Clase del colectivo según la ontología provista para el "
                    "tipo de discurso (p. ej. institucional, partidario, "
                    "ideológico). Usar EXACTAMENTE uno de los identificadores "
                    "listados.",
    )
    nombre: str = Field(
        description="Denominación concreta del colectivo (p. ej. 'gobierno de "
                    "Milei', 'La Libertad Avanza', 'libertarismo').",
    )
    justificacion: str = Field(
        description="Justificación breve, citando elementos del texto.",
    )


class EnunciacionSchema(StrictBase):
    """Estructura enunciativa completa: enunciador + enunciatarios."""
    enunciador: EnunciadorSchema = Field(
        description="El enunciador del discurso.",
    )
    enunciatarios: list[EnunciatarioSchema] = Field(
        description="Lista de enunciatarios identificados. Puede haber 1 o "
                    "varios. Si solo se identifica uno, devolver una lista "
                    "con un solo elemento.",
    )
    auditorio: list[AuditorioSchema] = Field(
        description="Auditorio directo (quienes escuchan o leen el discurso). "
                    "Puede haber varios. Devolvé lista vacía SOLO si es "
                    "realmente indeterminable; si el discurso da pistas del "
                    "público presente, identificalo.",
    )
    colectivos: list[ColectivoIdentificacionSchema] = Field(
        description="Colectivos de identificación del enunciador, según la "
                    "ontología provista. Pueden ser varios. Devolvé lista vacía "
                    "solo si no hay evidencia en el discurso.",
    )


# ══════════════════════════════════════════════════════════════════════════════
#  Actores
# ══════════════════════════════════════════════════════════════════════════════

TipoActor = Literal["humano_individual", "colectivo", "institucional"]
ModoActor = Literal["explicito", "inferido"]


class ActorSchema(StrictBase):
    """Actor mencionado o inferido en una unidad textual."""
    marca: str = Field(
        description="Marca discursiva: la expresión LITERAL de la unidad que "
                    "habilita al actor (la mención de superficie tal cual: "
                    "'Javier Milei', 'ellos', 'la Casa Rosada', 'represión', "
                    "'tomamos'). Si es un sujeto tácito, transcribí el verbo o "
                    "construcción que lo porta (ej. 'ordenaron').",
    )
    actor: str = Field(
        description="Referente inferido de la marca: a quién refiere. Si la "
                    "marca ya nombra al actor explícitamente, repetilo; si es "
                    "inferido (deíctico, tácito, metonimia), poné el referente "
                    "deducido del contexto.",
    )
    tipo: TipoActor = Field(  # type: ignore[valid-type]
        description="Tipo de actor según naturaleza ontológica.",
    )
    modo: ModoActor = Field(  # type: ignore[valid-type]
        description="Modo de aparición: 'explicito' si se nombra "
                    "literalmente, 'inferido' si se deduce del contexto.",
    )
    justificacion: str = Field(
        description="Justificación breve de la identificación, citando "
                    "elementos del texto.",
    )


class ActoresBatchItemSchema(StrictBase):
    """Ítem del batch de actores: unit_idx + actores de la unidad."""
    unit_idx: int = Field(
        description="Índice 0-based de la unidad en el batch. DEBE coincidir "
                    "con el número entre corchetes del prompt: UNIDAD [N].",
    )
    actores: list[ActorSchema] = Field(
        description="Actores identificados en esa unidad. Lista vacía si "
                    "no hay actores identificables.",
    )


class ListaActoresBatchSchema(RootModel[list[ActoresBatchItemSchema]]):
    """Batch response: lista de items, uno por unidad del batch."""


# ══════════════════════════════════════════════════════════════════════════════
#  Emociones
# ══════════════════════════════════════════════════════════════════════════════

ModoExistenciaEmocion = Literal[
    "realizada",
    "potencial",
    "actual",
    "virtual",
    "inducida_proyectada",
]


#: Ocho tipos de configuraciones de simulacro emocional.
#: Ver: https://github.com/alexdcolman/cartografia-afectiva/blob/main/diccionario_variables.md
TipoConfiguracion = Literal[
    "sostenido_en_sustantivos",
    "sostenido_en_adjetivos",
    "ordenado_alrededor_de_verbos_psicologicos",
    "cualificacion_por_indicadores_cognitivos",
    "cualificacion_por_indicadores_comportamiento",
    "cualificacion_por_indicadores_axiologicos",
    "cualificacion_por_componentes_descriptivo_narrativos",
    "transposicion_situacion_reconocimiento_potencial",
]


#: Derivación determinista: tipo_configuracion → (modo_semiotizacion,
#: modo_identificacion). Reemplaza la inferencia LLM de esas dos variables, que
#: están atadas a la configuración. Se pierde la identificación "mixta".
SEMIOSIS_POR_CONFIGURACION: dict[str, tuple[str, str]] = {
    "sostenido_en_sustantivos": ("dicha", "directa"),
    "sostenido_en_adjetivos": ("dicha", "directa"),
    "ordenado_alrededor_de_verbos_psicologicos": ("dicha", "directa"),
    "cualificacion_por_indicadores_cognitivos": ("mostrada", "por_senales_salida"),
    "cualificacion_por_indicadores_comportamiento": ("mostrada", "por_senales_salida"),
    "cualificacion_por_indicadores_axiologicos": ("mostrada", "por_senales_salida"),
    "cualificacion_por_componentes_descriptivo_narrativos": ("sostenida", "por_senales_entrada"),
    "transposicion_situacion_reconocimiento_potencial": ("sostenida", "por_senales_entrada"),
}


def semiosis_from_config(tipo_configuracion: str | None) -> tuple[str, str]:
    """Deriva (modo_semiotizacion, modo_identificacion) de la configuración.

    Devuelve ("", "") si la configuración es desconocida o nula.
    """
    return SEMIOSIS_POR_CONFIGURACION.get(tipo_configuracion or "", ("", ""))


class EmocionSchema(StrictBase):
    """Una emoción detectada en una unidad textual."""
    experienciador: str = Field(
        description="Referente del experienciador: actor que experimenta la "
                    "emoción (enunciador, enunciatario o actor mencionado). Es "
                    "la INFERENCIA del referente, no la marca de superficie.",
    )
    experienciador_marca: str = Field(
        description="Marca discursiva del experienciador: la expresión LITERAL "
                    "de la unidad que lo porta ('nosotros', 'el presidente', "
                    "sujeto tácito como 'tienen miedo'). Transcribila tal cual.",
    )
    tipo_emocion: str = Field(
        description="Nombre de la emoción (ej. miedo, alegría, indignación). "
                    "Usar nombres concretos, no categorías abstractas.",
    )
    fuente_marca: str = Field(
        description="Marca discursiva de la FUENTE de la emoción: la expresión "
                    "LITERAL que la porta ('la barbarie invasora', 'el "
                    "capitalismo de libre empresa'). Si la fuente no es "
                    "identificable en la unidad, poné \"no identificado\".",
    )
    fuente_inferencia: str = Field(
        description="Quién o qué desencadena la emoción. Si no se puede "
                    "determinar, escribir literalmente 'no identificado'. "
                    "NO dejar vacío.",
    )
    modo_existencia: ModoExistenciaEmocion = Field(  # type: ignore[valid-type]
        description="Modo de existencia semiótica de la emoción: "
                    "realizada (efectivamente sentida), "
                    "potencial (susceptible de aparecer), "
                    "actual (ocurriendo en el presente del enunciado), "
                    "virtual (presupuesta, no manifiesta), "
                    "inducida_proyectada (provocada o atribuida por el discurso).",
    )
    tipo_configuracion: TipoConfiguracion = Field(  # type: ignore[valid-type]
        description="Configuración del simulacro emocional (TIPO_CONF). "
                    "Identifica cómo la emoción es portada en la unidad: "
                    "sostenido_en_sustantivos, sostenido_en_adjetivos, "
                    "ordenado_alrededor_de_verbos_psicologicos, "
                    "cualificacion_por_indicadores_cognitivos, "
                    "cualificacion_por_indicadores_comportamiento, "
                    "cualificacion_por_indicadores_axiologicos, "
                    "cualificacion_por_componentes_descriptivo_narrativos, "
                    "transposicion_situacion_reconocimiento_potencial. "
                    "Las configuraciones sostenidas en sustantivos, adjetivos "
                    "o verbos psicológicos SOLO aplican si la marca léxica "
                    "pertenece a la familia léxica de una emoción ('amor', "
                    "'amaba', 'amado'); una palabra no emocional ('inclaudicable') "
                    "no cuenta como tal. "
                    "DEBE elegirse exactamente una; si ninguna marca léxica "
                    "lo determina con claridad, usar la configuración 8 "
                    "(transposicion_situacion_reconocimiento_potencial) "
                    "como fallback de proyección situacional.",
    )


class EmocionesBatchItemSchema(StrictBase):
    """Un ítem del batch de emociones."""
    unit_idx: int = Field(
        description="Índice 0-based de la unidad en el batch.",
    )
    emociones: list[EmocionSchema] = Field(
        max_length=10,
        description="Emociones identificadas en esa unidad. Lista vacía "
                    "si no hay emociones detectables.",
    )


class ListaEmocionesBatchSchema(
    RootModel[Annotated[list[EmocionesBatchItemSchema], Field(min_length=1)]]
):
    """Batch response de detección de emociones."""


# ══════════════════════════════════════════════════════════════════════════════
#  Caracterización de emociones
# ══════════════════════════════════════════════════════════════════════════════

TipoDuracion = Literal["instantanea", "durable", "permanente"]

TipoModoSemiotizacion = Literal["dicha", "mostrada", "sostenida"]

TipoModoIdentificacion = Literal[
    "directa",
    "por_senales_salida",
    "por_senales_entrada",
    "mixta",
]

TipoAtribucion = Literal[
    "auto_atribucion",
    "hetero_atribucion",
    "sin_atribucion",
]

Foria = Literal[
    "euforico",
    "disforico",
    "aforico",
    "ambiforico",
    "indeterminado",
]

Dominancia = Literal["corporal", "cognoscitiva", "mixta"]

Intensidad = Literal["alta", "baja", "neutra_ambivalente"]

#: Temporalidad histórica de la emoción respecto de la situación de enunciación.
#: Se piensa en términos estrictos/históricos: la emoción *futura* de un auditorio
#: que escucha o lee el discurso es contemporánea (no `futuro_historico`).
Temporalidad = Literal[
    "contemporanea",
    "pasado_historico",
    "futuro_historico",
    "atemporal",
    "indeterminada",
]

#: Aspecto gramatical de la predicación emocional (lista cerrada).
Aspecto = Literal[
    "perfectivo",
    "imperfectivo",
    "ingresivo",
    "terminativo",
    "iterativo",
    "no_marcado",
]


class CaracterizacionEmocionSchema(StrictBase):
    """Caracterización completa de una emoción detectada."""
    foria: Foria = Field(  # type: ignore[valid-type]
        description="Tonalidad afectiva: eufórico (positivo), disfórico "
                    "(negativo), afórico (neutro), ambifórico (mezcla "
                    "positivo+negativo), indeterminado.",
    )
    foria_justificacion: str = Field(
        description="Justificación breve de la foria, citando elementos.",
    )
    dominancia: Dominancia = Field(  # type: ignore[valid-type]
        description="Tipo de dominancia: corporal (somática, vísceral), "
                    "cognoscitiva (mental, evaluativa), mixta.",
    )
    dominancia_justificacion: str = Field(
        description="Justificación breve de la dominancia.",
    )
    intensidad: Intensidad = Field(  # type: ignore[valid-type]
        description="Intensidad: alta, baja, o neutra/ambivalente.",
    )
    intensidad_justificacion: str = Field(
        description="Justificación breve de la intensidad.",
    )
    duracion: TipoDuracion = Field(  # type: ignore[valid-type]
        description="Duración de la emoción en el texto: "
                    "'instantanea' (punto, evento único), "
                    "'durable' (se extiende a lo largo del enunciado o discurso), "
                    "'permanente' (rasgo estable del experienciador, sin límite temporal).",
    )
    duracion_justificacion: str = Field(
        description="Justificación breve de la duración, citando marcadores "
                    "temporales o de aspecto presentes en el texto.",
    )
    tipo_atribucion: TipoAtribucion = Field(  # type: ignore[valid-type]
        description="Cómo se atribuye EXPLÍCITAMENTE la emoción: "
                    "'auto_atribucion' (el experienciador se la atribuye a sí "
                    "mismo de forma explícita, ej. 'yo amo a Laura'), "
                    "'hetero_atribucion' (un actor, incluido el enunciador, "
                    "atribuye explícitamente una emoción a otro actor, ej. "
                    "'ella ama a Laura'), "
                    "'sin_atribucion' (nadie la atribuye explícitamente; se "
                    "infiere de la situación, la valoración o el comportamiento). "
                    "Sin atribución textual directa, usar 'sin_atribucion'.",
    )
    tipo_atribucion_justificacion: str = Field(
        description="Justificación breve del tipo de atribución, citando "
                    "la construcción sintáctica o enunciativa relevante.",
    )
    temporalidad: Temporalidad = Field(  # type: ignore[valid-type]
        description="Locus temporal HISTÓRICO de la emoción respecto de la "
                    "situación de enunciación: "
                    "'contemporanea' (del presente de la enunciación; INCLUYE "
                    "la emoción proyectada sobre el auditorio que escucha o lee "
                    "el discurso), "
                    "'pasado_historico' (situada en un pasado histórico, p. ej. "
                    "el terror de víctimas de un genocidio), "
                    "'futuro_historico' (situada en un futuro histórico, NO la "
                    "del auditorio presente), "
                    "'atemporal' (gnómica o rasgo sin anclaje temporal), "
                    "'indeterminada' (no deducible).",
    )
    temporalidad_justificacion: str = Field(
        description="Justificación breve, citando el marcador temporal o el "
                    "anclaje histórico relevante del texto.",
    )
    aspecto: Aspecto = Field(  # type: ignore[valid-type]
        description="Aspecto gramatical de la predicación emocional: "
                    "'perfectivo' (completada, vista como un todo), "
                    "'imperfectivo' (en curso o habitual), "
                    "'ingresivo' (foco en el inicio/incoación), "
                    "'terminativo' (foco en el cese), "
                    "'iterativo' (repetida), "
                    "'no_marcado' (sin marca aspectual clara).",
    )
    aspecto_justificacion: str = Field(
        description="Justificación breve, citando la marca aspectual (tiempo/"
                    "perífrasis verbal, adverbio) relevante del texto.",
    )


class CaracterizacionBatchItemSchema(StrictBase):
    """Ítem del batch de caracterizaciones.

    `unit_idx` indexa una emoción dentro del batch.
    """
    unit_idx: int = Field(
        description="Índice 0-based de la emoción en el batch.",
    )
    caracterizacion: CaracterizacionEmocionSchema = Field(
        description="Caracterización completa de la emoción.",
    )


class ListaCaracterizacionBatchSchema(RootModel[list[CaracterizacionBatchItemSchema]]):
    """Batch response de caracterizaciones de emociones."""


# ══════════════════════════════════════════════════════════════════════════════
#  LLM-as-judge: un LLM evalúa la coherencia de la caracterización ya producida
#  por el CharacterizerAgent. 
# ══════════════════════════════════════════════════════════════════════════════

ConfianzaJuicio = Literal["alta", "media", "baja"]


#: Campos del simulacro que el juez puede proponer corregir. Cerrado y ACOTADO a
#: los elementos de mayor valor/menor ambigüedad: identidad de la emoción,
#: experienciador y fuente, temporalidad y los actantes. Se dejan FUERA las
#: dimensiones finas del characterizer (foria/dominancia/intensidad/duración/
#: atribución/aspecto): son las que más hacían dudar y "loopear" al juez.
CampoCorregible = Literal[
    "experienciador",
    "tipo_emocion",
    "fuente_inferencia",
    "modo_existencia",
    "caracterizacion.temporalidad",
    "actantes.mediador.tipo",
    "actantes.verificador_normativo.tipo",
    "actantes.verificador_normativo.evaluacion",
    "actantes.verificador_observacional.tipo",
    "actantes.verificador_observacional.evaluacion",
    "actantes.operador_modificacion.funcion",
    "actantes.polaridad.tipo",
]


class CorreccionElementoSchema(StrictBase):
    """Corrección propuesta para UN elemento del simulacro."""
    campo: CampoCorregible = Field(  # type: ignore[valid-type]
        description="Elemento a corregir, identificado por su ruta.",
    )
    valor_sugerido: str = Field(
        max_length=60,
        description="SOLO el valor corregido (una palabra o nombre corto), sin "
                    "explicación ni razonamiento. Debe ser un valor VÁLIDO del "
                    "campo (p. ej. una foria válida). Si no conocés un valor "
                    "válido para ese campo, NO lo incluyas como corrección.",
    )


class JuicioSchema(StrictBase):
    """Veredicto sobre la corrección de un simulacro emocional.

    Orden de campos: decisión, sugerencias de corrección, justificación global
    y confianza.
    """
    coherente: bool = Field(
        description="True si el simulacro es CORRECTO en lo sustantivo (sin "
                    "errores mayores). False solo cuando hay al menos un error "
                    "sustantivo que amerite corrección.",
    )
    sugerencias: list[CorreccionElementoSchema] = Field(
        default_factory=list,
        max_length=5,
        description="Correcciones propuestas, una por elemento a corregir. "
                    "Lista VACÍA cuando coherente=True. Incluir SOLO errores "
                    "sustantivos (fuente/experienciador mal atribuidos por "
                    "retome o discurso ajeno, ironía, inversión de polaridad, "
                    "etc.); NO correcciones menores ni de matices terminológicos.",
    )
    issues: str = Field(
        max_length=120,
        description="Si coherente=False, el problema mayor en UNA frase corta "
                    "(máx. ~15 palabras), sin razonar. Si coherente=True, "
                    "escribir literalmente 'no identificado'. NO dejar vacío.",
    )
    confianza: ConfianzaJuicio = Field(  # type: ignore[valid-type]
        description="Cuán seguro está el juez de su veredicto: alta, media, baja.",
    )


class JuicioBatchItemSchema(StrictBase):
    """Ítem del batch de juicios.

    `unit_idx` indexa una emoción dentro del batch.
    """
    unit_idx: int = Field(
        description="Índice 0-based de la emoción en el batch.",
    )
    juicio: JuicioSchema = Field(
        description="Veredicto del juez sobre la caracterización de la emoción.",
    )


class ListaJuiciosBatchSchema(RootModel[list[JuicioBatchItemSchema]]):
    """Batch response de juicios sobre caracterizaciones."""


# ══════════════════════════════════════════════════════════════════════════════
#  Actantes del simulacro emocional
#
#  Configuración actancial extendida de la emoción. Cubre cuatro componentes
#  del dispositivo analítico: mediador (vehiculización de la emoción), dos
#  verificadores (normativo y observacional) y operador de modificación
#  (manipulación actancial de la emoción).
#
#  Granularidad: emoción individual. En una misma frase pueden coexistir
#  emociones con configuraciones actanciales distintas.
#
#  Cada sub-componente declara `presente: bool` y, si está presente, su
#  tipo y descripción. Esto fuerza una decisión binaria antes que un
#  juego de campos opcionales, lo que reduce variabilidad en la salida
#  del LLM.
# ══════════════════════════════════════════════════════════════════════════════

#: Tipos de mediadores. Las emociones pueden ser activadas o
#: transportadas por dispositivos, discursos, documentos, objetos,
#: espacios o acciones.
#: Sobre la noción, ver: Plantin (2014).
TipoMediador = Literal[
    "discurso_propio",
    "discurso_ajeno",
    "documento_o_registro",
    "objeto_o_artefacto",
    "espacio_o_escena",
    "accion_o_comportamiento",
    "ausente",
]

#: Tipos de verificadores normativos. Evalúan adecuación o validez
#: cultural de la emoción según una norma (sociocultural difusa,
#: moral, jurídica, ideológica o estética).
#: Nota: la voz "verificador" es tomada de Berrendonner (1982).
TipoVerificadorNormativo = Literal[
    "norma_sociocultural",
    "norma_moral_o_etica",
    "norma_juridica_o_institucional",
    "norma_ideologica_o_politica",
    "norma_estetica_o_de_gusto",
    "ausente",
]

#: Tipos de verificadores observacionales. Definen o cuestionan la
#: autenticidad de la emoción o la realidad de su desencadenante.
TipoVerificadorObservacional = Literal[
    "cuestionamiento_de_autenticidad",
    "reinterpretacion_del_desencadenante",
    "corroboracion_de_autenticidad",
    "corroboracion_del_desencadenante",
    "ausente",
]

#: Evaluación del verificador normativo: legitima o deslegitima la emoción.
EvaluacionNormativa = Literal["legitima", "deslegitima", "sin_evaluacion"]

#: Evaluación del verificador observacional: confirma o niega que la
#: emoción haya sido efectivamente sentida o que su desencadenante
#: coincida con el alegado.
EvaluacionObservacional = Literal["realizada", "no_realizada", "sin_evaluacion"]

#: Operaciones del operador de modificación. Articulan los modos en que
#: un discurso interfiere sobre la emoción de un experienciador:
#: argumentación, persuasión afectiva, activación o inhibición.
FuncionOpMod = Literal[
    "argumentacion_de_la_emocion",
    "persuasion_afectiva",
    "activacion_emocional",
    "inhibicion",
    "ausente",
]

#: Polaridad de la predicación emocional y, si está negada, la modalidad de la
#: negación. Es ortogonal al modo de existencia y al operador de modificación:
#: describe si la emoción se predica afirmada o negada, y bajo qué modalidad.
TipoPolaridad = Literal[
    "afirmada",           # se predica positivamente (caso por defecto)
    "negada_factual",     # se asevera que NO ocurre ("no se arrepienten")
    "negada_deontica",    # deber-ser / argumentada ("no se dejen robar la esperanza")
    "negada_volitiva",    # no deseada ("no quiero que sientan miedo")
    "negada_epistemica",  # negación de apariencia/creencia ("no es que esté triste")
]


class MediadorSchema(StrictBase):
    """Vehículo que media entre la fuente de la emoción y el experienciador."""
    presente: bool = Field(
        description="True si la emoción es activada o transportada por algún "
                    "mediador. False si el vínculo entre fuente y "
                    "experienciador es directo, sin mediación.",
    )
    descripcion: str | None = Field(
        default=None,
        description="Descripción breve del mediador identificado. NULL si "
                    "presente=false.",
    )
    tipo: TipoMediador = Field(  # type: ignore[valid-type]
        description="Categoría del mediador. Usar 'ausente' cuando "
                    "presente=false.",
    )
    justificacion: str = Field(
        description="Justificación breve, citando elementos del texto.",
    )


class VerificadorNormativoSchema(StrictBase):
    """Operación que evalúa la emoción desde una norma sociocultural."""
    presente: bool = Field(
        description="True si el discurso evalúa la legitimidad o adecuación "
                    "normativa de la emoción. False en caso contrario.",
    )
    descripcion: str | None = Field(
        default=None,
        description="Descripción breve del verificador. NULL si presente=false.",
    )
    tipo: TipoVerificadorNormativo = Field(  # type: ignore[valid-type]
        description="Categoría de la norma invocada. Usar 'ausente' cuando "
                    "presente=false.",
    )
    evaluacion: EvaluacionNormativa = Field(  # type: ignore[valid-type]
        description="Sentido de la evaluación: 'legitima' valida la emoción, "
                    "'deslegitima' la rechaza, 'sin_evaluacion' cuando "
                    "presente=false o el discurso no toma posición.",
    )
    justificacion: str = Field(
        description="Justificación breve, citando elementos del texto.",
    )


class VerificadorObservacionalSchema(StrictBase):
    """Operación que evalúa la autenticidad de la emoción o de su desencadenante."""
    presente: bool = Field(
        description="True si el discurso cuestiona o corrobora la "
                    "autenticidad de la emoción o de su desencadenante. "
                    "False en caso contrario.",
    )
    descripcion: str | None = Field(
        default=None,
        description="Descripción breve del verificador. NULL si presente=false.",
    )
    tipo: TipoVerificadorObservacional = Field(  # type: ignore[valid-type]
        description="Categoría de la operación observacional. Usar 'ausente' "
                    "cuando presente=false.",
    )
    evaluacion: EvaluacionObservacional = Field(  # type: ignore[valid-type]
        description="Resultado de la evaluación: 'realizada' confirma la "
                    "emoción o su desencadenante, 'no_realizada' la niega, "
                    "'sin_evaluacion' cuando presente=false o el discurso "
                    "no toma posición.",
    )
    justificacion: str = Field(
        description="Justificación breve, citando elementos del texto.",
    )


class OperadorModificacionSchema(StrictBase):
    """Operación dirigida a modificar la emoción de un experienciador."""
    presente: bool = Field(
        description="True si el discurso despliega una operación de "
                    "argumentación, persuasión, activación o inhibición "
                    "sobre la emoción. False en caso contrario.",
    )
    descripcion: str | None = Field(
        default=None,
        description="Descripción breve de la operación. NULL si "
                    "presente=false.",
    )
    funcion: FuncionOpMod = Field(  # type: ignore[valid-type]
        description="Función actancial sobre la emoción. Usar 'ausente' "
                    "cuando presente=false.",
    )
    justificacion: str = Field(
        description="Justificación breve, citando elementos del texto.",
    )


class PolaridadSchema(StrictBase):
    """Polaridad de la predicación emocional y modalidad de la negación.

    A diferencia del operador de modificación (una operación DIRIGIDA a la
    emoción de un experienciador) y del verificador observacional (autenticidad
    de la emoción o de su desencadenante), la polaridad describe si la emoción
    se predica AFIRMADA o NEGADA en el texto, y bajo qué modalidad se la niega.
    """
    negada: bool = Field(
        description="True si la emoción se predica NEGADA en el texto (no "
                    "ocurre, no debe ocurrir, no se desea, no aparenta). "
                    "False si se afirma positivamente.",
    )
    tipo: TipoPolaridad = Field(  # type: ignore[valid-type]
        description="'afirmada' cuando negada=false. Cuando negada=true: "
                    "'negada_factual' (se asevera que no ocurre: 'no se "
                    "arrepienten'), 'negada_deontica' (deber-ser / argumentada: "
                    "'no se dejen robar la esperanza'), 'negada_volitiva' (no "
                    "deseada: 'no quiero que sientan miedo'), 'negada_epistemica' "
                    "(negación de apariencia o creencia: 'no es que esté triste').",
    )
    justificacion: str = Field(
        description="Justificación breve, citando la marca de negación "
                    "(adverbio, operador deóntico, verbo volitivo) del texto.",
    )


class ActantesEmocionSchema(StrictBase):
    """Configuración actancial completa de una emoción.

    Incluye:
        - mediador (vehiculización)
        - verificador normativo
        - verificador observacional
        - operador de modificación (manipulación actancial)
        - polaridad (afirmación / negación de la emoción y su modalidad).

    Cuando alguno de los componentes está deshabilitado por
    configuración del run, el agente persiste un placeholder
    determinístico con `presente=false`; el schema sigue exigiendo el
    sub-objeto completo para que downstream pueda asumir una forma
    estable.
    """
    mediador: MediadorSchema = Field(
        description="Vehiculización de la emoción.",
    )
    verificador_normativo: VerificadorNormativoSchema = Field(
        description="Verificación normativa de la emoción.",
    )
    verificador_observacional: VerificadorObservacionalSchema = Field(
        description="Verificación observacional de la emoción.",
    )
    operador_modificacion: OperadorModificacionSchema = Field(
        description="Operador de modificación emocional.",
    )
    polaridad: PolaridadSchema = Field(
        description="Polaridad de la predicación emocional (afirmada/negada) "
                    "y modalidad de la negación.",
    )


class ActantesBatchItemSchema(StrictBase):
    """Ítem del batch de actantes.

    `unit_idx` indexa una emoción dentro del batch.
    """
    unit_idx: int = Field(
        description="Índice 0-based de la emoción en el batch.",
    )
    actantes: ActantesEmocionSchema = Field(
        description="Configuración actancial completa de la emoción.",
    )


class ListaActantesBatchSchema(RootModel[list[ActantesBatchItemSchema]]):
    """Batch response de configuraciones actanciales."""


# ══════════════════════════════════════════════════════════════════════════════
#  Semas de referentes canónicos
# ══════════════════════════════════════════════════════════════════════════════

ClaseReferente = Literal["actor", "circunstante", "cualidad"]

RolEnunciativoSema = Literal["enunciador", "enunciatario", "nombrado", "inferido"]

# Naturaleza según clase. Cada Literal incluye "no_aplica": el modelo debe
# declararlo explícitamente cuando la dimensión no corresponde a la `clase`
# del referente, en vez de omitir el campo (el schema no permite omitirlo).
NaturalezaActor = Literal[
    "humano", "animal", "institucional", "sobrenatural", "objeto",
    "concepto", "experiencia", "proceso", "otro", "no_aplica",
]
IndividuacionSema = Literal["individual", "colectivo", "no_aplica"]
TemporalidadSema = Literal[
    "pasado_historico", "futuro_historico", "contemporaneidad", "indefinido",
    "no_aplica",
]
NaturalezaCircunstante = Literal[
    "temporal", "espacial", "espaciotemporal", "acontecimiento", "proceso",
    "situacion", "no_aplica",
]
NaturalezaCualidad = Literal["estado", "atributo", "valor", "otro", "no_aplica"]

# Semas opcionales: dimensiones que no dependen de la `clase` y pueden
# omitirse (lista vacía) sin que eso implique una generación incompleta.
SemaOpcional = Literal[
    "victima", "victimario", "testigo", "beneficiario", "adversario", "aliado",
    "actor", "situacion", "objeto", "experiencia", "espacio", "discurso_ajeno",
    "agente", "paciente", "animado", "inanimado", "figurativo", "no_figurativo",
    "generico", "particular", "abstracto", "concreto",
]


class SemasBatchItemSchema(StrictBase):
    """Ítem del batch de semas: unit_idx + clasificación completa del referente.

    Todos los campos de clasificación son obligatorios en el schema (el
    grammar GBNF los fuerza): el modelo debe declarar un valor por dimensión,
    usando `no_aplica` cuando la dimensión no corresponde a la `clase` del
    referente, en vez de omitir la evidencia insuficiente con una lista vacía.
    """
    unit_idx: int = Field(
        description="Índice 0-based del referente en el batch. DEBE coincidir "
                    "con el número entre corchetes del prompt: REFERENTE [N].",
    )
    clase: ClaseReferente = Field(
        description="Clase actancial del referente: figura autónoma (actor), "
                    "circunstancia (circunstante) o predicado calificante (cualidad).",
    )
    rol_enunciativo: RolEnunciativoSema = Field(
        description="Posición del referente respecto de la enunciación.",
    )
    naturaleza_actor: NaturalezaActor = Field(
        description="Naturaleza ontológica si clase=actor. no_aplica en otro caso.",
    )
    individuacion: IndividuacionSema = Field(
        description="Grado de individuación si clase=actor. no_aplica en otro caso.",
    )
    temporalidad: TemporalidadSema = Field(
        description="Tiempo histórico si clase=actor. no_aplica en otro caso.",
    )
    naturaleza_circunstante: NaturalezaCircunstante = Field(
        description="Tipo de circunstante si clase=circunstante. no_aplica en otro caso.",
    )
    naturaleza_cualidad: NaturalezaCualidad = Field(
        description="Tipo de cualidad si clase=cualidad. no_aplica en otro caso.",
    )
    opcionales: list[SemaOpcional] = Field(
        description="Semas opcionales (rol narrativo, tipo de fuente, "
                    "agente/paciente, animación, figuratividad, especificidad, "
                    "concreción) con evidencia clara. Lista vacía si ninguno aplica.",
    )


class ListaSemasBatchSchema(RootModel[list[SemasBatchItemSchema]]):
    """Batch response: lista de items, uno por referente del batch."""


# ══════════════════════════════════════════════════════════════════════════════
#  Deixis: resolución de marcas deícticas a referentes concretos
# ══════════════════════════════════════════════════════════════════════════════

#: Categorías esquemáticas de referente deíctico. Conjunto cerrado: ninguna
#: marca puede asignarse a un tipo fuera de esta lista.
TipoReferenteDeixis = Literal[
    "enunciador",
    "auditorio",
    "colectivo_identificacion",
]


class ReferenteDeixisSchema(StrictBase):
    """Un referente concreto al que apunta una marca deíctica.

    `tipo_referente_deixis` es la categoría esquemática (cerrada);
    `referente_deixis` es el nombre CONCRETO elegido entre los referentes del
    discurso (enunciador, auditorio o colectivo), nunca el tipo.
    """
    tipo_referente_deixis: TipoReferenteDeixis = Field(  # type: ignore[valid-type]
        description="Categoría esquemática del referente.",
    )
    referente_deixis: str = Field(
        description="Nombre concreto del referente (p. ej. 'Javier Milei', "
                    "'los presentes en el Foro de Davos', 'La Libertad "
                    "Avanza'). Debe elegirse de los referentes provistos del "
                    "discurso, no inventarse.",
    )


class MarcaDeixisSchema(StrictBase):
    """Resolución deíctica de una marca: puede apuntar a varios referentes."""
    marca: str = Field(
        description="La marca deíctica tal como aparece en el discurso "
                    "(p. ej. 'tenemos', 'nuestro equipo', 'veamos').",
    )
    referentes: list[ReferenteDeixisSchema] = Field(
        description="Uno o varios referentes a los que apunta la marca. "
                    "'nuestro equipo' puede apuntar al enunciador Y a su "
                    "colectivo de identificación a la vez.",
    )


class DeixisSchema(StrictBase):
    """Resolución deíctica de todas las marcas candidatas de un discurso."""
    resoluciones: list[MarcaDeixisSchema] = Field(
        description="Una entrada por marca deíctica resuelta. Marcas sin "
                    "deixis de 1ª/2ª persona se omiten. Devolvé lista vacía "
                    "solo si ninguna marca tiene deixis resoluble.",
    )


# ══════════════════════════════════════════════════════════════════════════════
#  Modalidad referencial: cómo una marca refiere a su referente
# ══════════════════════════════════════════════════════════════════════════════

#: Cómo la marca refiere al referente (eje 1+2). Conjunto cerrado.
ModalidadReferencial = Literal[
    "designacion",                 # SN/nombre propio que nombra o categoriza
    "referencia_gramatical",       # deixis/morfología (pronombres, concordancia)
    "identificacion_inferencial",  # se identifica por la actitud/valores
]

#: Naturaleza del referente al que apunta la marca. Conjunto cerrado.
NaturalezaReferente = Literal[
    "persona", "colectivo", "institucion", "objeto_proceso", "otro",
]


class ModalidadItemSchema(StrictBase):
    """Clasificación de un vínculo marca→referente."""
    marca: str = Field(
        description="La marca tal como aparece (p. ej. 'ellos son la casta "
                    "corrupta', 'el presidente', 'he defendido').",
    )
    referente: str = Field(
        description="El referente concreto al que se vinculó la marca "
                    "(p. ej. 'javier_milei').",
    )
    modalidad: ModalidadReferencial = Field(  # type: ignore[valid-type]
        description="'designacion' si la marca NOMBRA o CATEGORIZA al referente "
                    "con un sustantivo/nombre propio ('Javier Milei', 'el "
                    "presidente', 'la academia'). 'referencia_gramatical' si lo "
                    "refiere por deixis o morfología sin nombrarlo (pronombres, "
                    "'yo/nosotros', concordancia verbal 'he defendido'). "
                    "'identificacion_inferencial' si el referente se identifica "
                    "por la actitud/valores/juicios expresados, NO por nombrarlo "
                    "('ellos son la casta corrupta' identifica al enunciador).",
    )
    naturaleza: NaturalezaReferente = Field(  # type: ignore[valid-type]
        description="Tipo del referente: 'persona' (individuo), 'colectivo' "
                    "(grupo), 'institucion' (organización/estado), "
                    "'objeto_proceso' (objeto de discurso, evento o "
                    "nominalización abstracta), 'otro'.",
    )
    justificacion: str = Field(
        description="Justificación breve (una oración).",
    )


class ModalidadSchema(StrictBase):
    """Clasificación de modalidad referencial de un lote de vínculos."""
    clasificaciones: list[ModalidadItemSchema] = Field(
        description="Una entrada por vínculo marca→referente del lote. "
                    "Devolvé una clasificación para cada uno.",
    )
