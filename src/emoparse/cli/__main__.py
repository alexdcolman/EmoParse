# ══════════════════════════════════════════════════════════════════════════════
#  emoparse.cli.__main__
#
#  Entry point del CLI.
#
#  Define el parser principal con sus flags globales, delega el registro de
#  cada subcomando en su propio módulo (`COMMANDS`) y despacha la ejecución
#  al handler que ese módulo dejó en `set_defaults(handler=...)`.
# ══════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

from dotenv import load_dotenv

load_dotenv()

import argparse
from collections.abc import Callable

from loguru import logger

from emoparse.cli import logging_setup
from emoparse.cli.commands import COMMANDS

#: Handler de subcomando: recibe argparse.Namespace y devuelve exit code.
HandlerFn = Callable[[argparse.Namespace], int]


def build_parser() -> argparse.ArgumentParser:
    """Construye el parser principal y registra los subcomandos.

    Público: además del entry point, lo consume el generador de la
    referencia de comandos.
    """
    parser = argparse.ArgumentParser(
        prog="emoparse",
        description=(
            "EmoParse — análisis semiótico de emociones en discursos. "
            "Orquesta el pipeline completo: ingest, agentes LLM por etapa, "
            "persistencia con resumability, y caché de respuestas LLM."
        ),
    )
    _add_global_flags(parser)

    sub = parser.add_subparsers(
        title="subcomandos",
        dest="command",
        # Se fuerza subcomando obligatorio para evitar ejecución vacía y
        # obtener feedback inmediato cuando se invoca `emoparse` sin args.
        required=True,
    )
    for command in COMMANDS:
        command.register(sub)
    return parser


def _add_global_flags(parser: argparse.ArgumentParser) -> None:
    """Flags que aplican a cualquier subcomando, leídas antes de despachar."""
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Logging en DEBUG (más detalle).",
    )
    parser.add_argument(
        "-q",
        "--quiet",
        action="store_true",
        help="Logging en WARNING (menos ruido).",
    )
    parser.add_argument(
        "--log-dir",
        dest="log_dir",
        default=None,
        metavar="DIR",
        help=(
            "Directorio donde escribir el log de la corrida. Default: la "
            "variable EMOPARSE_LOG_DIR, o `logs/`."
        ),
    )
    parser.add_argument(
        "--no-log-file",
        dest="no_log_file",
        action="store_true",
        help="No escribir el log a archivo; solo consola.",
    )


def main(argv: list[str] | None = None) -> int:
    """Entry point del CLI. Devuelve el exit code del proceso."""
    parser = build_parser()
    args = parser.parse_args(argv)

    archivo_log = logging_setup.configure(
        verbose=args.verbose,
        quiet=args.quiet,
        log_dir=args.log_dir,
        no_log_file=args.no_log_file,
        comando=args.command,
        etiqueta=logging_setup.etiqueta_de(args),
    )
    if archivo_log is not None:
        logger.debug(f"[CLI] Log de la corrida: {archivo_log}")

    handler: HandlerFn = args.handler
    try:
        return handler(args)
    except KeyboardInterrupt:
        logger.warning("[CLI] Interrumpido por el usuario.")
        return 130  # convención: SIGINT
    except Exception as e:
        # En modo verbose se muestra traceback completo; de lo contrario,
        # solo un mensaje resumido.
        if args.verbose:
            logger.exception(f"[CLI] Error: {e}")
        else:
            logger.error(f"[CLI] Error: {e}. Re-correr con -v para traceback.")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
