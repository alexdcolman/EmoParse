# ══════════════════════════════════════════════════════════════════════════════
#  emoparse.cli.commands
#
#  Registro de los subcomandos del CLI.
#
#  Cada módulo de este paquete expone `register(subparsers)`, que crea su
#  propio parser y deja su handler en `set_defaults(handler=...)`. El entry
#  point recorre `COMMANDS` y no conoce ningún subcomando por nombre: sumar
#  uno es agregar un módulo acá y nada más.
#
#  El orden de `COMMANDS` es el orden en que aparecen en `emoparse --help`.
# ══════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

import argparse
from typing import Protocol

from emoparse.cli.commands import (
    acquire_cmd,
    app_cmd,
    eval_cmd,
    export_cmd,
    follows_cmd,
    inspect_cmd,
    judge_cmd,
    metrics_cmd,
    modalidad_cmd,
    network_cmd,
    retry_cmd,
    run_cmd,
    scrape_cmd,
    semas_cmd,
    stats_cmd,
    status_cmd,
    validate_cmd,
)


class CommandModule(Protocol):
    """Contrato que cumple cada módulo de subcomando."""

    def register(self, subparsers: argparse._SubParsersAction) -> None:  # type: ignore[type-arg]
        """Crea el parser del subcomando y registra su handler."""
        ...


#: Subcomandos registrados, en orden de aparición en la ayuda.
COMMANDS: tuple[CommandModule, ...] = (
    run_cmd,
    status_cmd,
    retry_cmd,
    inspect_cmd,
    stats_cmd,
    metrics_cmd,
    judge_cmd,
    modalidad_cmd,
    semas_cmd,
    export_cmd,
    validate_cmd,
    scrape_cmd,
    acquire_cmd,
    network_cmd,
    follows_cmd,
    eval_cmd,
    app_cmd,
)

__all__ = ["COMMANDS", "CommandModule"]
