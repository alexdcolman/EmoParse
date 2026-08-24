# ══════════════════════════════════════════════════════════════════════════════
#  emoparse.config.models
#
#  Modelos Pydantic para validar la configuración del run.
#
#  El loader (`config/loader.py`) toma el YAML, lo parsea como dict,
#  y construye un `RunConfig` que valida todo.
# ══════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

# ══════════════════════════════════════════════════════════════════════════════
#  Modelos
# ══════════════════════════════════════════════════════════════════════════════

#: Backends válidos. Centralizado para generar error claro si se usa
#: "ollama" en el YAML (no soportado).
BackendName = Literal["llama_cpp", "llama_server", "lmstudio"]


class ModelConfig(BaseModel):
    """Configuración de un modelo LLM individual.

    Campos extra permitidos: cada backend acepta parámetros propios
    (n_gpu_layers para llama_cpp, base_url para lmstudio, etc.). Se usa
    `extra="allow"` para evitar acoplar este schema a detalles de cada backend.
    """

    model_config = ConfigDict(extra="allow")

    backend: BackendName = Field(
        description="Tipo de backend: llama_cpp para GGUFs locales "
        "in-process, llama_server para llama.cpp en modo server "
        "(continuous batching, cache de prefijo, draft models, "
        "multimodal), lmstudio para API OpenAI-compatible.",
    )
    temperature: float = Field(
        default=0.0,
        description="0.0 = greedy/determinístico. Qwen3 recomienda 0.6.",
    )
    max_tokens: int = Field(
        default=2048,
        description="Tokens máximos por respuesta.",
    )
    seed: int = Field(
        default=42,
        description="Seed del sampler para idempotencia. Cambiá solo si "
        "querés explorar variaciones.",
    )
    # GGUF local: `llama_cpp` lo carga dentro del proceso; `llama_server`
    # puede usar el mismo path cuando EmoParse prepara/lanzar el server local.
    path: str | None = Field(
        default=None,
        description="(llama_cpp/llama_server local) Path al GGUF, relativo o absoluto.",
    )
    context_length: int = Field(
        default=8192,
        gt=0,
        description=(
            "Ventana de contexto por request. En llama_server, el launcher "
            "reserva este tamaño por slot."
        ),
    )
    n_gpu_layers: int = Field(
        default=-1,
        description="-1 = todo a GPU. 0 = solo CPU. También se usa al lanzar llama_server.",
    )

    # Lanzamiento declarativo de llama-server. Permanecen opcionales para que
    # un alias `llama_server` pueda seguir apuntando a un server administrado
    # externamente sin que EmoParse intente controlarlo.
    base_url: str | None = Field(
        default=None,
        description="(llama_server) URL raíz del server OpenAI-compatible.",
    )
    timeout: float | None = Field(
        default=None,
        gt=0,
        description="(llama_server) Timeout HTTP por request, en segundos.",
    )
    server_binary: str | None = Field(
        default=None,
        description="Ejecutable llama-server para `emoparse server` (default: llama-server).",
    )
    server_parallel: int | None = Field(
        default=None,
        ge=1,
        description=(
            "Cantidad de slots a reservar al lanzar llama-server. Si se omite, "
            "se usa pipeline.parallel."
        ),
    )
    cont_batching: bool | None = Field(
        default=None,
        description="(llama_server) Habilitar continuous batching al lanzar el server.",
    )
    cache_reuse: int | None = Field(
        default=None,
        ge=0,
        description="(llama_server) Mínimo de tokens para reutilización de prefijos KV.",
    )
    cache_type_k: str | None = Field(
        default=None,
        min_length=1,
        description="(llama_server) Tipo de KV cache para claves; mantener f16 pre-golden.",
    )
    cache_type_v: str | None = Field(
        default=None,
        min_length=1,
        description="(llama_server) Tipo de KV cache para valores; mantener f16 pre-golden.",
    )
    cpu_moe: bool | None = Field(
        default=None,
        description="(llama_server) Mantener todos los expertos MoE en CPU.",
    )
    n_cpu_moe: int | None = Field(
        default=None,
        ge=1,
        description="(llama_server) Mantener en CPU los expertos de las primeras N capas.",
    )

    @model_validator(mode="after")
    def _validate_llama_server_options(self) -> ModelConfig:
        """Evita perfiles ambiguos o que el backend in-process no puede cumplir."""
        if self.cpu_moe and self.n_cpu_moe is not None:
            raise ValueError("cpu_moe y n_cpu_moe son mutuamente excluyentes")
        if (self.cpu_moe or self.n_cpu_moe is not None) and self.backend != "llama_server":
            raise ValueError(
                "cpu_moe/n_cpu_moe se soportan sólo con backend=llama_server; "
                "llama_cpp in-process no declara overrides de tensores en este contrato"
            )
        return self


class PipelineConfig(BaseModel):
    """Parámetros del pipeline (orquestación)."""

    model_config = ConfigDict(extra="forbid")

    # Asignación de etapas a modelos; cada etapa apunta a un alias en `models`.
    # Validación realizada por Runner.
    stages: dict[str, str] = Field(
        default_factory=dict,
        description="Mapa stage → alias_de_modelo. Ej: {'metadata': 'phi4-mini', "
        "'emotions': 'qwen3-14b'}.",
    )
    cache_enabled: bool = Field(
        default=True,
        description="Si False, el CachedBackend no envuelve los backends raw.",
    )
    parallel: int = Field(
        default=1,
        ge=1,
        description="Discursos procesados en simultáneo dentro de cada stage "
        "por-frase. Solo tiene efecto con backends servidor "
        "(llama_server con --parallel N --cont-batching, "
        "lmstudio); con llama_cpp in-process el runner lo "
        "fuerza a 1.",
    )
    max_retries: int = Field(default=3, ge=0)
    retry_delays_seconds: list[int] = Field(
        default_factory=lambda: [2, 8, 15],
        description="Delays entre reintentos en segundos.",
    )
    timeout_seconds: int = Field(default=90, gt=0)
    pass2_context_mode: Literal["rolling", "full"] = Field(
        default="rolling",
        description=(
            "Modo de contexto para el pase 2 de emociones. "
            "'rolling': ventana deslizante de rolling_window frases anteriores "
            "(mejor escalado, default). "
            "'full': todas las frases anteriores del discurso "
            "(mejor calidad en discursos cortos; puede saturar el context "
            "window en discursos largos)."
        ),
    )


class PathsConfig(BaseModel):
    """Paths del proyecto.

    Strings en lugar de Path para mantener serialización a YAML/JSON sin
    convertidores custom.
    """

    model_config = ConfigDict(extra="forbid")

    runs_dir: str = Field(default="runs/")
    models_dir: str = Field(default="models/")
    knowledge_dir: str = Field(default="knowledge/")
    inputs_dir: str = Field(default="data/")


class VersionsConfig(BaseModel):
    """Versions del run. Strings opacos; actualizar manualmente.

    Campos equivalentes a `storage.models.Versions`, unificados al construir
    RunContext en Runner.
    """

    model_config = ConfigDict(extra="forbid")

    knowledge: str | None = Field(
        default=None,
        description="Bumpear cuando cambian datos del proyecto base.",
    )
    prompt: str | None = Field(
        default=None,
        description="Bumpear cuando cambian los prompts (system o user).",
    )
    ontology: str | None = Field(
        default=None,
        description="Bumpear cuando cambian las ontologías (emociones.json, foria.json, etc.).",
    )
    schema_: str | None = Field(
        default=None,
        # Alias `schema` usado por consistencia con el resto de campos.
        alias="schema",
        description="Bumpear cuando cambian los schemas Pydantic de salida.",
    )


class LoggingConfig(BaseModel):
    """Configuración de logging."""

    model_config = ConfigDict(extra="forbid")

    level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    log_to_file: bool = True
    rotation: str = "10 MB"
    retention: str = "7 days"


# ══════════════════════════════════════════════════════════════════════════════
#  RunConfig — top-level
# ══════════════════════════════════════════════════════════════════════════════


class RunConfig(BaseModel):
    """Configuración completa de un run. Lo que el YAML representa."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    models: dict[str, ModelConfig] = Field(
        description="Diccionario de alias → ModelConfig.",
    )
    pipeline: PipelineConfig = Field(default_factory=PipelineConfig)
    paths: PathsConfig = Field(default_factory=PathsConfig)
    versions: VersionsConfig = Field(default_factory=VersionsConfig)
    logging: LoggingConfig = Field(default_factory=LoggingConfig)

    # Notas opcionales que aparecen en `runs.notes`.
    notes: str = ""

    def model_config_for_alias(self, alias: str) -> dict[str, Any]:
        """Devuelve el dict que el backend requiere (`build_backend(alias, dict)`).

        Convierte ModelConfig a dict porque la factory del backend acepta dict crudo,
        manteniendo compatibilidad con formatos no-Pydantic.
        """
        if alias not in self.models:
            raise KeyError(
                f"Alias '{alias}' no definido en config.models. Disponibles: {sorted(self.models)}"
            )
        # by_alias=False asegura que `schema` aparezca como tal y no como `schema_`.
        return self.models[alias].model_dump(by_alias=False, exclude_none=True)
