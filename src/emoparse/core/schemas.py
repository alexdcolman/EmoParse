# ══════════════════════════════════════════════════════════════════════════════
#  emoparse.core.schemas
#
#  Schemas Pydantic v2 de salida del LLM.
# ══════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

from typing import Literal

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
    """Tipo de discurso + lugar geográfico.

    Campos obligatorios tipo str. Convención: si valor indeterminable, usar
    'no identificado'.
    """
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
#  Emociones
# ══════════════════════════════════════════════════════════════════════════════

ModoExistenciaEmocion = Literal[
    "realizada",
    "potencial",
    "actual",
    "virtual",
    "inducida_proyectada",
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
    justificacion: str = Field(
        description="Justificación semiótica de la detección, citando "
                    "elementos del texto.",
    )


class EmocionesBatchItemSchema(StrictBase):
    """Un ítem del batch de emociones."""
    unit_idx: int = Field(
        description="Índice 0-based de la unidad en el batch.",
    )
    emociones: list[EmocionSchema] = Field(
        description="Emociones identificadas en esa unidad. Lista vacía "
                    "si no hay emociones detectables.",
    )


class ListaEmocionesBatchSchema(RootModel[list[EmocionesBatchItemSchema]]):
    """Batch response de detección de emociones."""


# ══════════════════════════════════════════════════════════════════════════════
#  Caracterización de emociones (foria, dominancia, intensidad, fuente)
# ══════════════════════════════════════════════════════════════════════════════

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
    """Caracterización completa de una emoción detectada.

    Orden de campos: decisión seguida de justificación.
    """
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
