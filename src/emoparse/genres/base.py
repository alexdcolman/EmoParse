# ══════════════════════════════════════════════════════════════════════════════
#  emoparse.genres.base
#
#  Plugin API para géneros.
# ══════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

from collections.abc import Callable
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

#: Unidad de chunking que el género quiere consumir.
ChunkUnit = Literal["frase", "parrafo", "documento"]

#: Unidad de contexto enunciativo para los agentes que desambiguan con
#: contexto (emotions, emotions_pass2, judge).
#: 'ninguno'  → cada unidad se analiza aislada.
#: 'discurso' → el contexto es el propio documento (frases previas, resumen).
#: 'hilo'     → el contexto es la conversación a la que pertenece el documento
#:              (cadena de posts padre, post raíz). Requiere que el corpus
#:              traiga estructura conversacional (tabla `posts`/`hilos`).
ContextUnit = Literal["ninguno", "discurso", "hilo"]


#: Stages canónicas del pipeline.
StageName = Literal[
    "summarizer",
    "metadata",
    "enunciation",
    "technoparse",
    "reframing",
    "emoji_affect",
    "hashtag_semiotics",
    "vision_describe",
    "tecno_usage",
    "actors",
    "emotions",
    "emotions_pass2",
    "explode_emotions",
    "deixis",
    "modalidad",
    "normalize_emotions",
    "characterizer",
    "actants",
    "judge",
    "semas",
]


class GenreContextBlock(BaseModel):
    """Bloque de metadata de género que puede llegar a los prompts.

    El género declara qué campos del modelo de metadata componen el bloque y
    cuánto contexto puede consumir cada stage. El render y el recorte son
    genéricos: sumar un género nuevo no requiere modificar agentes ni stages.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str = Field(
        description="Identificador estable del bloque, en snake_case.",
        pattern=r"^[a-z][a-z0-9_]*$",
    )
    title: str = Field(
        description="Título breve y legible que encabeza el bloque.",
        min_length=1,
    )
    fields: tuple[str, ...] = Field(
        description="Campos del input_metadata_model incluidos, en orden.",
        min_length=1,
    )
    stage_token_budgets: dict[StageName, int] = Field(
        description="Presupuesto aproximado de tokens por stage consumidora.",
        min_length=1,
    )

    @model_validator(mode="after")
    def validate_declaration(self) -> GenreContextBlock:
        """Comprueba unicidad de campos y presupuestos positivos."""
        if len(set(self.fields)) != len(self.fields):
            raise ValueError(f"El bloque '{self.name}' contiene campos repetidos")
        invalid = {
            stage: budget for stage, budget in self.stage_token_budgets.items() if budget < 1
        }
        if invalid:
            raise ValueError(f"El bloque '{self.name}' tiene presupuestos inválidos: {invalid}")
        return self


class Genre(BaseModel):
    """Descriptor declarativo de un género de discurso."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        arbitrary_types_allowed=True,
    )

    genre_id: str = Field(
        description="Identificador único, snake_case. Se usa en CLI "
        "(`--genre <id>`) y se persiste en runs.config para "
        "auditoría.",
    )
    display_name: str = Field(
        description="Nombre legible (aparece en logs y en stats).",
    )

    # ── Metadata propia del input ────────────────────────────────────────────
    input_metadata_model: type[BaseModel] | None = Field(
        default=None,
        exclude=True,
        description="Modelo Pydantic que valida la metadata propia del género "
        "en el borde de ingesta. Se excluye de model_dump porque "
        "es una clase de runtime, no configuración serializable.",
    )
    input_metadata_display: dict[str, str] = Field(
        default_factory=dict,
        description="Etiquetas legibles para los campos declarados por "
        "input_metadata_model. Permiten que interfaces y exports "
        "los presenten sin ramas específicas por género.",
    )
    context_blocks: tuple[GenreContextBlock, ...] = Field(
        default=(),
        description="Bloques de contexto construidos desde la metadata del "
        "input. Cada bloque declara sus campos y el presupuesto "
        "por stage; el pipeline los renderiza sin ramas por género.",
    )

    # ── Unidad de chunking ───────────────────────────────────────────────────
    unit: ChunkUnit = Field(
        default="frase",
        description="Granularidad de las unidades textuales que consumen "
        "los agentes por-frase."
        "'frase' usa split_into_sentences."
        "'parrafo' parte por dobles newlines."
        "'documento' no chunkea — cada discurso es una sola unidad.",
    )

    # ── Unidad de contexto enunciativo ───────────────────────────────────────
    context_unit: ContextUnit = Field(
        default="discurso",
        description="De dónde toman contexto los agentes que desambiguan "
        "con material circundante. 'discurso' es el "
        "comportamiento clásico (frases previas + resumen). "
        "'hilo' usa la conversación (posts padre) cuando el "
        "corpus la trae. 'ninguno' analiza cada unidad aislada.",
    )

    # ── Parsing tecnodiscursivo ──────────────────────────────────────────────
    technoparse: bool = Field(
        default=False,
        description="Si True, la stage determinista `technoparse` extrae "
        "los tecnolingüísticos de cada unidad (hashtags, "
        "menciones, URLs, emojis, tecnografismos) antes de "
        "cualquier agente LLM. Pensado para discurso nativo "
        "digital (tuits, posts).",
    )

    # ── Roles enunciativos válidos ───────────────────────────────────────────
    enunciation_roles: tuple[str, ...] = Field(
        description="Universo cerrado de roles enunciativos que el género "
        "acepta. Construye dinámicamente Literal[*roles] para "
        "el schema de EnunciatarioSchema, restringiendo el "
        "sampler vía GBNF al universo válido del género. Cuando "
        "el género discrimina roles por tipo de discurso "
        "(`enunciatarios_por_tipo`), este universo es la unión de "
        "todos ellos más los transversales: la restricción por "
        "tipo se resuelve en el prompt y en un filtro post-hoc, "
        "no en el sampler, para no multiplicar variantes de "
        "gramática ni de cache por tipo.",
    )

    # ── Roles enunciativos por tipo de discurso ──────────────────────────────
    roles_transversales: tuple[str, ...] = Field(
        default=(),
        description="Roles enunciativos del dispositivo, válidos en cualquier "
        "tipo de discurso del género (p. ej. en el post de red "
        "social, el destinatario mencionado y la audiencia "
        "ambiente). Se suman a los roles del tipo identificado.",
    )
    enunciatarios_por_tipo: dict[str, tuple[str, ...]] = Field(
        default_factory=dict,
        description="Mapa tipo_de_discurso → roles enunciativos propios de ese "
        "tipo (posiciones de creencia/destinación). La escena "
        "enunciativa se cruza: los roles efectivos de un discurso "
        "son los transversales más los de su tipo. El tipo lo "
        "resuelve `metadata`; si el mapa tiene una sola entrada, "
        "se usa siempre (géneros de campo discursivo fijo). Vacío "
        "conserva el comportamiento plano (roles = "
        "`enunciation_roles`).",
    )
    roles_descripciones: dict[str, str] = Field(
        default_factory=dict,
        description="Descripción breve de cada rol enunciativo (transversal o "
        "por tipo), inyectada en el prompt de enunciación junto al "
        "identificador. Claves sin rol asociado se ignoran.",
    )

    # ── Overrides opcionales del config global ───────────────────────────────
    models: dict[str, str] = Field(
        default_factory=dict,
        description="Override (parcial) de pipeline.stages: stage→alias. "
        "Solo las stages presentes acá overridean; el resto "
        "respeta el config.yaml.",
    )
    batch_size: dict[str, int] = Field(
        default_factory=dict,
        description="Override de batch size por stage. Solo aplica a "
        "stages batch (actors, emotions, characterizer, judge).",
    )
    summarizer: bool = Field(
        default=True,
        description="Si False, la stage summarizer se desactiva para este "
        "género. Útil para textos cortos como tuits donde resumir "
        "no aporta.",
    )

    stages_invalidas: tuple[str, ...] = Field(
        default=(),
        description="Stages que no tienen sentido para este género y que el "
        "CLI rechaza si se piden explícitamente por --stages. A "
        "diferencia de `summarizer=False` (que desactiva en "
        "silencio una stage que igual correría en los defaults), "
        "esto es para stages que el usuario podría pedir a mano "
        "pero que producirían ruido o no aplican: el pase 2 de "
        "emociones en textos de una sola frase, por ejemplo. Se "
        "informan con un error explícito, no se saltean en "
        "silencio, para que quede claro por qué no corrieron.",
    )

    # ── Detección de emociones ───────────────────────────────────────────────
    max_emociones_unidad: int = Field(
        default=10,
        ge=1,
        description="Tope de emociones que los pases de detección pueden "
        "devolver por unidad. Restringe el schema (maxItems) vía "
        "`schema_factory`, así que la gramática obliga a cerrar la "
        "lista: acota el peor caso de generación y garantiza que "
        "la salida entre en la ventana del modelo. Ajustarlo por "
        "género permite ceñirlo a lo que cada unidad puede portar "
        "de verdad (un post es mucho más corto que un párrafo de "
        "discurso).",
    )

    # ── Enunciación por género ───────────────────────────────────────────────
    enunciador_from_handle: bool = Field(
        default=False,
        description="Si True, el enunciador se fija de forma determinista "
        "desde los campos del input (`autor_display`, con "
        "fallback a `autor_handle`), sin inferencia LLM. Pensado "
        "para discurso nativo digital, donde la cuenta autora es "
        "el enunciador; funciona igual con corpus seudonimizados "
        "(el alias es estable por cuenta).",
    )
    enunciador_from_input_field: str | None = Field(
        default=None,
        description="Campo de input_metadata_model que fija de forma "
        "determinista al emisor concreto del discurso. El valor "
        "puede ser un string o una colección de nombres. Evita "
        "inferir por LLM cuando la autoría ya viene declarada.",
    )
    auditorio_predeterminado: bool = Field(
        default=False,
        description="Si True, el auditorio se construye de forma "
        "determinista desde el dispositivo, sin inferencia LLM: "
        "seguidores de la cuenta (siempre), un auditorio por "
        "hashtag presente (nunca combinados) y un destinatario "
        "directo por cuenta mencionada.",
    )
    auditorio_oral: bool = Field(
        default=False,
        description="Si True, el género presupone una situación oral con "
        "público presente. Los vocativos describen el auditorio, "
        "no bastan para asignar posiciones de destinación. Si el "
        "LLM omite el auditorio pese a marcas situacionales, se "
        "construye un fallback determinista.",
    )

    # ── Tipos de discurso cerrados ───────────────────────────────────────────
    tipos_discurso: tuple[str, ...] = Field(
        default=(),
        description="Vocabulario cerrado de tipos de discurso para la stage "
        "metadata. Si no está vacío, construye Literal[*tipos] "
        "para `MetadatosSchema.tipo_discurso`, restringiendo el "
        "sampler vía GBNF. Tupla vacía conserva el campo libre "
        "con el diccionario de tipos como referencia.",
    )
    tipos_discurso_descripciones: dict[str, str] = Field(
        default_factory=dict,
        description="Descripciones breves de los tipos cerrados, inyectadas "
        "en el system prompt junto al identificador. Claves que "
        "no estén en `tipos_discurso` se ignoran.",
    )

    prompt_overrides: dict[str, str] = Field(
        default_factory=dict,
        description="Map stage_name → nombre de template Jinja2 alternativo. "
        "Útil cuando un género quiere un prompt completamente "
        "distinto (ej. tuit sin sección 'enunciador' en actors). "
        "El template alternativo debe existir en "
        "core/prompts/templates/. Si no se especifica, se "
        "usa el template default.",
    )

    heuristics_overrides: dict[str, str] = Field(
        default_factory=dict,
        description="Map stage_name → archivo de heurísticas propio del "
        "género, relativo a knowledge_dir. No reemplaza a las "
        "heurísticas base de la stage: se concatena después de "
        "ellas, de modo que el género suma sus reglas de lectura "
        "sin repetir las comunes. Si el archivo no existe, la "
        "stage corre solo con las base.",
    )

    @model_validator(mode="after")
    def validate_input_metadata_declaration(self) -> Genre:
        """Comprueba que las etiquetas refieran a campos del modelo tipado."""
        if self.enunciador_from_handle and self.enunciador_from_input_field:
            raise ValueError(
                "enunciador_from_handle y enunciador_from_input_field son mutuamente excluyentes"
            )

        if self.input_metadata_model is None:
            if (
                self.input_metadata_display
                or self.context_blocks
                or self.enunciador_from_input_field
            ):
                raise ValueError(
                    "input_metadata_display, context_blocks y "
                    "enunciador_from_input_field requieren "
                    "input_metadata_model"
                )
            return self

        declared = set(self.input_metadata_model.model_fields)
        if (
            self.enunciador_from_input_field is not None
            and self.enunciador_from_input_field not in declared
        ):
            raise ValueError(
                "enunciador_from_input_field refiere a un campo no declarado: "
                f"{self.enunciador_from_input_field}"
            )
        unknown = set(self.input_metadata_display) - declared
        if unknown:
            raise ValueError(
                f"input_metadata_display contiene campos no declarados: {sorted(unknown)}"
            )

        block_names = [block.name for block in self.context_blocks]
        if len(set(block_names)) != len(block_names):
            raise ValueError("context_blocks contiene nombres repetidos")

        for block in self.context_blocks:
            undeclared = set(block.fields) - declared
            if undeclared:
                raise ValueError(
                    f"El bloque '{block.name}' usa campos no declarados: {sorted(undeclared)}"
                )
            without_label = set(block.fields) - set(self.input_metadata_display)
            if without_label:
                raise ValueError(
                    f"El bloque '{block.name}' usa campos sin etiqueta en "
                    f"input_metadata_display: {sorted(without_label)}"
                )
        return self

    # ── Helpers de resolución de roles ───────────────────────────────────────
    def roles_para_tipo(self, tipo_discurso: str | None) -> tuple[str, ...]:
        """Roles enunciativos efectivos para un tipo de discurso.

        Cruza los transversales del género con los del tipo identificado por
        `metadata`. Reglas de resolución cuando el tipo no matchea el mapa:
        con una sola entrada, se usa siempre (géneros de campo fijo, como el
        presidencial); con varias, se cae a la unión de todos los tipos para
        no perder ningún rol. Sin mapa por tipo, devuelve `enunciation_roles`.
        """
        if not self.enunciatarios_por_tipo:
            return self.enunciation_roles
        clave = _norm_tipo(tipo_discurso)
        mapa_norm = {_norm_tipo(k): v for k, v in self.enunciatarios_por_tipo.items()}
        if clave in mapa_norm:
            especificos = mapa_norm[clave]
        elif len(self.enunciatarios_por_tipo) == 1:
            especificos = next(iter(self.enunciatarios_por_tipo.values()))
        else:
            especificos = tuple(
                dict.fromkeys(r for roles in self.enunciatarios_por_tipo.values() for r in roles)
            )
        # dict.fromkeys preserva orden y deduplica (transversales primero).
        return tuple(dict.fromkeys((*self.roles_transversales, *especificos)))


def _norm_tipo(tipo: str | None) -> str:
    """Normaliza un identificador de tipo de discurso para comparar."""
    return str(tipo or "").strip().lower()


# ══════════════════════════════════════════════════════════════════════════════
#  Tipo de la factory function que cada entry-point debe exponer.
# ══════════════════════════════════════════════════════════════════════════════

#: Factory de Genre: callable sin argumentos que devuelve un Genre.
GenreFactory = Callable[[], Genre]
