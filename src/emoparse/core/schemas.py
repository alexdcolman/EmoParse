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


# ══════════════════════════════════════════════════════════════════════════════
#  Actores
# ══════════════════════════════════════════════════════════════════════════════

TipoActor = Literal["humano_individual", "colectivo", "institucional"]
ModoActor = Literal["explicito", "inferido"]


class ActorSchema(StrictBase):
    """Actor mencionado o inferido en una unidad textual."""
    actor: str = Field(
        description="Nombre o denominación del actor. Mantener el nombre "
                    "tal como aparece en el texto cuando es explícito.",
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
#  Normalización de actores (entity linking contra KB)
# ══════════════════════════════════════════════════════════════════════════════

ConfianzaLinking = Literal["alta", "media", "baja"]


class ActorLinkingSchema(StrictBase):
    """Resultado del entity linking para un actor mencionado.

    El LLM compara una mención con la KB de actores conocidos y decide
    si refiere a una entidad existente (devuelve `actor_canonico`) o si
    es una entidad nueva (`es_nuevo=True`). En caso de duda debe marcar
    `confianza="baja"` antes que adivinar un `actor_canonico` incorrecto.
    """
    actor_mencionado: str = Field(
        description="String del actor tal como lo emitió ActorsAgent. "
                    "Debe replicarse literal para que el caller correlacione "
                    "con la mención original.",
    )
    actor_canonico: str | None = Field(
        description="canonical_id de actors_kb.json (la clave del dict "
                    "'actors'), o null si no matchea con ninguna entrada "
                    "conocida. NO inventar canonical_ids: si la entidad "
                    "es nueva, dejar null y marcar es_nuevo=true.",
    )
    confianza: ConfianzaLinking = Field(  # type: ignore[valid-type]
        description="Cuán seguro está el modelo del linking: alta, media, baja. "
                    "Usar 'baja' ante ambigüedad antes que adivinar.",
    )
    es_nuevo: bool = Field(
        description="True si el modelo considera que la mención refiere a "
                    "una entidad NO presente en la KB. False si encontró un "
                    "canónico que matchea (en cuyo caso actor_canonico no "
                    "debe ser null).",
    )
    alias_candidato: bool = Field(
        description="True SOLO si la mención identifica al actor de forma "
                    "inequívoca SIN contexto: un nombre propio o una "
                    "denominación estable ('Javier Milei', 'La Libertad "
                    "Avanza', 'el FMI'). False para deícticos y pronombres "
                    "('yo', 'mí', 'nosotros'), roles dependientes del contexto "
                    "('el presidente', 'el ministro') y apodos no "
                    "identificantes ('el león'). Solo las menciones "
                    "alias_candidato=true son aptas para incorporarse a la KB "
                    "como alias; las demás se resuelven por discurso, no a "
                    "nivel global.",
    )
    canonical_id_sugerido: str | None = Field(
        description="Solo si es_nuevo=true Y alias_candidato=true: slug ASCII "
                    "propuesto para el actor nuevo (minúsculas, dígitos y "
                    "guiones bajos; empieza por letra). REGLA DE ESTABILIDAD: "
                    "el MISMO actor del mundo real debe recibir el MISMO slug "
                    "aunque la mención cambie (p. ej. 'LLA' y 'La Libertad "
                    "Avanza' → 'la_libertad_avanza'). null en cualquier otro "
                    "caso.",
    )
    display_name_sugerido: str | None = Field(
        description="Solo si es_nuevo=true Y alias_candidato=true: nombre "
                    "canónico legible del actor nuevo, expandiendo siglas o "
                    "apodos a la forma más completa y estable. null en "
                    "cualquier otro caso.",
    )
    tipo_sugerido: str | None = Field(
        description="Solo si es_nuevo=true Y alias_candidato=true: tipo del "
                    "actor nuevo, uno de 'individuo', 'institucion', "
                    "'colectivo' o 'desconocido'. null en cualquier otro caso.",
    )
    justificacion: str = Field(
        description="Justificación breve del linking, citando aliases o "
                    "elementos del contexto que respalden la decisión.",
    )


class ActorLinkingBatchItemSchema(StrictBase):
    """Ítem del batch de linking: unit_idx + linkings de esa unidad."""
    unit_idx: int = Field(
        description="Índice 0-based de la unidad en el batch. DEBE coincidir "
                    "con el número entre corchetes del prompt: UNIDAD [N].",
    )
    linkings: list[ActorLinkingSchema] = Field(
        description="Resultado del linking para cada actor mencionado en "
                    "la unidad. Mismo orden y misma cantidad que los actores "
                    "del prompt.",
    )


class ListaActorLinkingBatchSchema(RootModel[list[ActorLinkingBatchItemSchema]]):
    """Batch response del entity linking de actores."""


# ══════════════════════════════════════════════════════════════════════════════
#  Equivalencias de experienciador
# ══════════════════════════════════════════════════════════════════════════════

ClaseExperienciador = Literal[
    "enunciador", "enunciatario", "actor", "otro", "literal"
]


class ExperiencerEquivalenceSchema(StrictBase):
    """Propuesta de normalización para un experienciador crudo de un discurso.

    La normalización es local al discurso: 'yo', 'enunciador', 'el orador'
    refieren al enunciador de ESE discurso. El modelo NO debe inventar un
    destino: ante duda, usar clase 'otro' con confianza 'baja'.
    """
    raw_experienciador: str = Field(
        description="Experienciador tal como aparece en las emociones. Debe "
                    "replicarse literal para que el caller correlacione.",
    )
    clase: ClaseExperienciador = Field(  # type: ignore[valid-type]
        description="A quién refiere: 'enunciador' (incl. 'yo', 'el orador', "
                    "'quien habla'); 'enunciatario' (el/los destinatarios); "
                    "'actor' (un tercero mencionado); 'literal' (ya es un "
                    "nombre propio que no necesita cambio); 'otro' (no "
                    "resoluble con seguridad).",
    )
    canonical_sugerido: str | None = Field(
        description="Nombre canónico legible propuesto (p. ej. el nombre del "
                    "enunciador, o el del actor). Para 'literal' repetir el "
                    "crudo. Para 'otro' dejar null.",
    )
    confianza: ConfianzaLinking = Field(  # type: ignore[valid-type]
        description="alta | media | baja. Usar 'baja' ante ambigüedad antes "
                    "que forzar un destino.",
    )
    justificacion: str = Field(
        description="Justificación breve citando la evidencia del discurso.",
    )


class ExperiencerEquivalenceBatchItemSchema(StrictBase):
    """Ítem del batch: un discurso (unit_idx) y sus equivalencias."""
    unit_idx: int = Field(
        description="Índice 0-based del discurso en el batch. DEBE coincidir "
                    "con el número entre corchetes del prompt: DISCURSO [N].",
    )
    equivalencias: list[ExperiencerEquivalenceSchema] = Field(
        description="Una entrada por experienciador a normalizar de ese "
                    "discurso. Mismo conjunto que la lista del prompt.",
    )


class ListaExperiencerEquivalenceBatchSchema(
    RootModel[list[ExperiencerEquivalenceBatchItemSchema]]
):
    """Batch response de la normalización de experienciadores."""


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


class EmocionSchema(StrictBase):
    """Una emoción detectada en una unidad textual."""
    experienciador: str = Field(
        description="Actor que experimenta la emoción. Puede ser el "
                    "enunciador, un enunciatario o un actor mencionado.",
    )
    tipo_emocion: str = Field(
        description="Nombre de la emoción (ej. miedo, alegría, indignación). "
                    "Usar nombres concretos, no categorías abstractas.",
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
                    "DEBE elegirse exactamente una; si ninguna marca léxica "
                    "lo determina con claridad, usar la configuración 8 "
                    "(transposicion_situacion_reconocimiento_potencial) "
                    "como fallback de proyección situacional.",
    )
    justificacion: str = Field(
        max_length=600,
        description="Justificación semiótica de la detección, citando "
                    "elementos del texto.",
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
    "atribucion_transpositiva",
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

TipoFuente = Literal[
    "actor",
    "situacion",
    "objeto",
    "experiencia",
    "espacio",
    "discurso_ajeno",
    "no_se_identifica",
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
    fuente: str = Field(
        description="Quién o qué desencadena la emoción. Si no se puede "
                    "determinar, escribir literalmente 'no identificado'. "
                    "NO dejar vacío.",
    )
    tipo_fuente: TipoFuente = Field(  # type: ignore[valid-type]
        description="Categoría de la fuente: actor, situación, objeto, "
                    "experiencia, espacio, discurso_ajeno, no_se_identifica. "
                    "Usar 'no_se_identifica' SOLO cuando la fuente es "
                    "indeterminable; nunca dejar el campo en blanco.",
    )
    fuente_justificacion: str = Field(
        description="Justificación breve de la fuente identificada.",
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
    modo_semiotizacion: TipoModoSemiotizacion = Field(  # type: ignore[valid-type]
        description="Modo en que la emoción es semiotizada en el discurso: "
                    "'dicha' (nombrada explícitamente mediante un término emocional), "
                    "'mostrada' (inferida por comportamiento, gesto o acción descritos), "
                    "'sostenida' (construida acumulativamente a lo largo del texto, "
                    "sin nombrarse ni mostrarse en un solo punto).",
    )
    modo_semiotizacion_justificacion: str = Field(
        description="Justificación breve del modo de semiotización, citando "
                    "el fragmento textual que lo determina.",
    )
    modo_identificacion: TipoModoIdentificacion = Field(  # type: ignore[valid-type]
        description="Modo en que el analista identifica la emoción: "
                    "'directa' (la emoción se nombra o define sin ambigüedad), "
                    "'por_senales_salida' (identificada por señales expresivas: "
                    "llanto, risa, tono, etc.), "
                    "'por_senales_entrada' (identificada por el estímulo desencadenante), "
                    "'mixta' (combinación de señales de salida y entrada).",
    )
    modo_identificacion_justificacion: str = Field(
        description="Justificación breve del modo de identificación, citando "
                    "los indicadores concretos usados.",
    )
    tipo_atribucion: TipoAtribucion = Field(  # type: ignore[valid-type]
        description="Tipo de atribución de la emoción en el discurso: "
                    "'auto_atribucion' (el experienciador se atribuye la emoción "
                    "a sí mismo), "
                    "'hetero_atribucion' (el enunciador atribuye la emoción a otro), "
                    "'atribucion_transpositiva' (la emoción se traslada "
                    "a un sujeto colectivo, abstracto o institucional).",
    )
    tipo_atribucion_justificacion: str = Field(
        description="Justificación breve del tipo de atribución, citando "
                    "la construcción sintáctica o enunciativa relevante.",
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


class JuicioSchema(StrictBase):
    """Veredicto sobre la coherencia de una caracterización de emoción.

    Orden de campos: decisión seguida de justificación.
    """
    coherente: bool = Field(
        description="True si la caracterización (foria/dominancia/intensidad/"
                    "fuente) es coherente con la frase de origen y la emoción "
                    "detectada. False si hay inconsistencias.",
    )
    issues: str = Field(
        description="Si coherente=False, descripción concreta de las "
                    "inconsistencias (ej.: 'foria=euforico no encaja con la "
                    "frase, que expresa miedo'). Si coherente=True, escribir "
                    "literalmente 'no identificado'. NO dejar vacío.",
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


class ActantesEmocionSchema(StrictBase):
    """Configuración actancial completa de una emoción.

    Incluye:
        - mediador (vehiculización)
        - verificador normativo
        - verificador observacional
        - operador de modificación (manipulación actancial).

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
