# ══════════════════════════════════════════════════════════════════════════════
#  emoparse.genres.base
#
#  Plugin API para géneros.
# ══════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

from typing import Callable, Literal

from pydantic import BaseModel, ConfigDict, Field


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


class Genre(BaseModel):
    """Descriptor declarativo de un género de discurso."""
    model_config = ConfigDict(extra="forbid", frozen=True)

    genre_id: str = Field(
        description="Identificador único, snake_case. Se usa en CLI "
                    "(`--genre <id>`) y se persiste en runs.config para "
                    "auditoría.",
    )
    display_name: str = Field(
        description="Nombre legible (aparece en logs y en stats).",
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
        description="Conjunto cerrado de roles enunciativos que el género "
                    "acepta. Construye dinámicamente Literal[*roles] para "
                    "el schema de EnunciatarioSchema, restringiendo el "
                    "sampler vía GBNF al universo válido del género.",
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

    prompt_overrides: dict[str, str] = Field(
        default_factory=dict,
        description="Map stage_name → nombre de template Jinja2 alternativo. "
                    "Útil cuando un género quiere un prompt completamente "
                    "distinto (ej. tuit sin sección 'enunciador' en actors). "
                    "El template alternativo debe existir en "
                    "core/prompts/templates/. Si no se especifica, se "
                    "usa el template default.",
    )


# ══════════════════════════════════════════════════════════════════════════════
#  Tipo de la factory function que cada entry-point debe exponer.
# ══════════════════════════════════════════════════════════════════════════════

#: Factory de Genre: callable sin argumentos que devuelve un Genre.
GenreFactory = Callable[[], Genre]
