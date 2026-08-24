# ══════════════════════════════════════════════════════════════════════════════
#  emoparse.core.backend.server_launch
#
#  Perfil declarativo para lanzar llama-server de forma reproducible desde el
#  mismo config que usa el pipeline. No gestiona procesos en background: el CLI
#  lo ejecuta en foreground y el usuario conserva el control del lifecycle.
# ══════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

from dataclasses import asdict, dataclass
from urllib.parse import urlparse

from emoparse.config.models import RunConfig
from emoparse.core.backend.exceptions import BackendConfigError

_DEFAULT_BASE_URL = "http://127.0.0.1:8080"
_DEFAULT_BINARY = "llama-server"
_DEFAULT_CACHE_TYPE = "f16"


@dataclass(frozen=True, slots=True)
class LlamaServerLaunchProfile:
    """Configuración efectiva con la que EmoParse lanzará un llama-server."""

    alias: str
    binary: str
    model_path: str
    base_url: str
    host: str
    port: int
    parallel: int
    context_per_slot: int
    context_total: int
    n_gpu_layers: int
    cont_batching: bool
    cache_reuse: int | None
    cache_type_k: str
    cache_type_v: str
    cpu_moe: bool
    n_cpu_moe: int | None

    def to_dict(self) -> dict[str, object]:
        return asdict(self)

    def command(self) -> list[str]:
        """Construye argv sin shell ni interpolación de strings."""
        gpu_layers = "all" if self.n_gpu_layers < 0 else str(self.n_gpu_layers)
        command = [
            self.binary,
            "--model",
            self.model_path,
            "--host",
            self.host,
            "--port",
            str(self.port),
            "--ctx-size",
            str(self.context_total),
            "--n-gpu-layers",
            gpu_layers,
            "--parallel",
            str(self.parallel),
            "--cont-batching" if self.cont_batching else "--no-cont-batching",
            "--cache-prompt",
            "--cache-type-k",
            self.cache_type_k,
            "--cache-type-v",
            self.cache_type_v,
            "--slots",
        ]
        if self.cache_reuse is not None:
            command.extend(["--cache-reuse", str(self.cache_reuse)])
        if self.cpu_moe:
            command.append("--cpu-moe")
        elif self.n_cpu_moe is not None:
            command.extend(["--n-cpu-moe", str(self.n_cpu_moe)])
        return command


def build_llama_server_launch_profile(
    config: RunConfig,
    alias: str,
    *,
    binary_override: str | None = None,
) -> LlamaServerLaunchProfile:
    """Deriva el comando de server desde un alias `llama_server` validado.

    `context_length` expresa contexto utilizable por request. llama-server
    reparte `--ctx-size` entre slots, por lo que el launcher reserva
    `context_length * parallel` como contexto total.
    """
    if alias not in config.models:
        raise BackendConfigError(
            f"Alias '{alias}' no definido. Disponibles: {sorted(config.models)}"
        )
    model = config.models[alias]
    if model.backend != "llama_server":
        raise BackendConfigError(
            f"Alias '{alias}' usa backend={model.backend}; `emoparse server` "
            "requiere backend=llama_server"
        )
    if not model.path:
        raise BackendConfigError(
            f"Alias '{alias}' no declara `path`; hace falta el GGUF para lanzar llama-server"
        )

    base_url = (model.base_url or _DEFAULT_BASE_URL).rstrip("/")
    parsed = urlparse(base_url)
    if parsed.scheme != "http" or not parsed.hostname:
        raise BackendConfigError(
            f"base_url no lanzable localmente: {base_url!r}. "
            "`emoparse server` admite una URL raíz http://host:puerto."
        )
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise BackendConfigError(f"base_url no lanzable localmente: {base_url!r}")
    if parsed.path not in ("", "/"):
        raise BackendConfigError(
            f"base_url debe ser la raíz del llama-server, sin path: {base_url!r}"
        )

    port = parsed.port or 80
    parallel = model.server_parallel or config.pipeline.parallel
    context_per_slot = int(model.context_length)
    context_total = context_per_slot * parallel

    return LlamaServerLaunchProfile(
        alias=alias,
        binary=binary_override or model.server_binary or _DEFAULT_BINARY,
        model_path=model.path,
        base_url=base_url,
        host=parsed.hostname,
        port=port,
        parallel=parallel,
        context_per_slot=context_per_slot,
        context_total=context_total,
        n_gpu_layers=int(model.n_gpu_layers),
        cont_batching=True if model.cont_batching is None else bool(model.cont_batching),
        cache_reuse=model.cache_reuse,
        cache_type_k=model.cache_type_k or _DEFAULT_CACHE_TYPE,
        cache_type_v=model.cache_type_v or _DEFAULT_CACHE_TYPE,
        cpu_moe=bool(model.cpu_moe),
        n_cpu_moe=model.n_cpu_moe,
    )


def configured_server_runtime(config: RunConfig, alias: str) -> dict[str, object]:
    """Metadata declarada que puede persistirse aunque el server sea externo."""
    if alias not in config.models:
        raise KeyError(alias)
    model = config.models[alias]
    if model.backend != "llama_server":
        raise ValueError(f"{alias} no usa llama_server")

    parallel = model.server_parallel or config.pipeline.parallel
    return {
        "base_url": (model.base_url or _DEFAULT_BASE_URL).rstrip("/"),
        "server_parallel": parallel,
        "context_per_slot": int(model.context_length),
        "cont_batching": True if model.cont_batching is None else bool(model.cont_batching),
        "cache_reuse": model.cache_reuse,
        "cache_type_k": model.cache_type_k or _DEFAULT_CACHE_TYPE,
        "cache_type_v": model.cache_type_v or _DEFAULT_CACHE_TYPE,
        "cpu_moe": bool(model.cpu_moe),
        "n_cpu_moe": model.n_cpu_moe,
        "n_gpu_layers": int(model.n_gpu_layers),
    }
