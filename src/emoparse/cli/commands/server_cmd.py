# ══════════════════════════════════════════════════════════════════════════════
#  emoparse.cli.commands.server_cmd
#
#  Lanzamiento/diagnóstico reproducible de llama-server desde config.yaml.
# ══════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

import argparse
import json
import os
import shlex
import shutil
import subprocess
from pathlib import Path

from emoparse.config import load_config
from emoparse.core.backend.exceptions import BackendConfigError
from emoparse.core.backend.llama_server import LlamaServerBackend
from emoparse.core.backend.server_launch import (
    build_llama_server_launch_profile,
    configured_server_runtime,
)


def _resolve_binary(binary: str) -> str | None:
    """Resuelve un ejecutable por PATH o por ruta explícita."""
    if os.sep in binary:
        path = Path(binary).expanduser()
        if path.is_file() and os.access(path, os.X_OK):
            return str(path)
        return None
    return shutil.which(binary)


def _print_json(title: str, payload: dict[str, object]) -> None:
    print(title)
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))


def _check_running_server(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    if args.model not in config.models:
        raise BackendConfigError(
            f"Alias '{args.model}' no definido. Disponibles: {sorted(config.models)}"
        )
    model = config.models[args.model]
    if model.backend != "llama_server":
        raise BackendConfigError(
            f"Alias '{args.model}' usa backend={model.backend}; se esperaba llama_server"
        )

    declared = configured_server_runtime(config, args.model)
    backend = LlamaServerBackend(
        alias=args.model,
        model_config=config.model_config_for_alias(args.model),
    )
    try:
        observed = backend.runtime_profile()
    finally:
        backend.close()

    _print_json(
        "=== llama-server configurado ===",
        {"alias": args.model, **declared},
    )
    _print_json("=== llama-server observado ===", observed)

    observed_slots = observed.get("parallel_slots")
    declared_slots = int(declared["server_parallel"])
    requested = int(config.pipeline.parallel)
    if isinstance(observed_slots, int):
        if model.server_parallel is not None and observed_slots != declared_slots:
            raise BackendConfigError(
                f"El server expone {observed_slots} slot(s), pero "
                f"models.{args.model}.server_parallel={declared_slots}."
            )
        if observed_slots < requested:
            raise BackendConfigError(
                f"El server expone {observed_slots} slot(s), pero pipeline.parallel={requested}."
            )
    elif max(declared_slots, requested) > 1:
        raise BackendConfigError(
            "El server está disponible, pero /slots y /props no permitieron "
            "comprobar el paralelismo configurado."
        )

    observed_contexts = observed.get("slot_context_lengths")
    declared_context = int(declared["context_per_slot"])
    if isinstance(observed_contexts, list):
        numeric_contexts = {
            value for value in observed_contexts if isinstance(value, int) and value > 0
        }
        if numeric_contexts and numeric_contexts != {declared_context}:
            raise BackendConfigError(
                f"El server expone contexto(s) por slot {sorted(numeric_contexts)}, "
                f"pero models.{args.model}.context_length={declared_context}."
            )

    print("SERVER_CHECK=OK")
    return 0


def handle(args: argparse.Namespace) -> int:
    if args.check:
        return _check_running_server(args)

    config = load_config(args.config)
    profile = build_llama_server_launch_profile(
        config,
        args.model,
        binary_override=args.binary,
    )
    _print_json("=== Perfil llama-server efectivo ===", profile.to_dict())
    print("Comando:")
    print(shlex.join(profile.command()))

    if args.dry_run:
        return 0

    resolved_binary = _resolve_binary(profile.binary)
    if resolved_binary is None:
        raise BackendConfigError(
            f"No se encontró el ejecutable {profile.binary!r}. "
            "Instalá/compilá llama.cpp o usá --binary RUTA."
        )
    model_path = Path(profile.model_path).expanduser()
    if not model_path.is_file():
        raise BackendConfigError(f"GGUF no encontrado: {model_path}")

    command = profile.command()
    command[0] = resolved_binary
    completed = subprocess.run(command, check=False)
    return int(completed.returncode)


def register(subparsers: argparse._SubParsersAction) -> None:  # type: ignore[type-arg]
    parser = subparsers.add_parser(
        "server",
        help="Prepara, comprueba o lanza llama-server desde config.yaml.",
        description=(
            "Prepara o lanza llama-server en foreground a partir de un alias "
            "backend=llama_server. --dry-run muestra el comando sin ejecutarlo; "
            "--check consulta /health y /slots de un server ya iniciado."
        ),
    )
    parser.add_argument(
        "--config",
        default="config.yaml",
        metavar="YAML",
        help="Config de EmoParse (default: config.yaml).",
    )
    parser.add_argument(
        "--model",
        required=True,
        metavar="ALIAS",
        help="Alias de models con backend=llama_server.",
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--dry-run",
        action="store_true",
        help="Mostrar perfil y comando efectivo sin iniciar el proceso.",
    )
    mode.add_argument(
        "--check",
        action="store_true",
        help="Comprobar disponibilidad y slots de un server ya iniciado.",
    )
    parser.add_argument(
        "--binary",
        default=None,
        metavar="RUTA",
        help="Sobrescribir el ejecutable llama-server sólo para este lanzamiento.",
    )
    parser.set_defaults(handler=handle)
