# ══════════════════════════════════════════════════════════════════════════════
#  emoparse.cli.commands.app_cmd
#
#  Subcomando `app`: lanza el dashboard Streamlit del proyecto.
#
#  Flujo:
#  1) Resolver el path al entry-point de la app (app/__main__.py).
#  2) Verificar que streamlit esté disponible en el entorno.
#  3) Reemplazar el proceso actual con `streamlit run <entry>` más los
#     flags opcionales que el usuario haya pasado (--port, --browser).
#
#  Uso básico:
#      emoparse app
#
#  Con opciones:
#      emoparse app --port 8502 --no-browser
# ══════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

import argparse
import os
import shutil
import sys
from pathlib import Path

from loguru import logger


#: Path relativo al entry-point de la app dentro del paquete instalado.
_APP_ENTRY = Path(__file__).parent.parent.parent / "app" / "__main__.py"


def handle(args: argparse.Namespace) -> int:
    """Maneja `emoparse app`. Devuelve exit code (nunca si streamlit toma el proceso)."""
    streamlit_bin = shutil.which("streamlit")
    if streamlit_bin is None:
        logger.error(
            "streamlit no encontrado en el entorno. "
            "Instalalo con: pip install streamlit"
        )
        return 1

    entry = _APP_ENTRY.resolve()
    if not entry.is_file():
        logger.error(
            f"Entry-point de la app no encontrado: {entry}. "
            "Verificá que el paquete emoparse esté instalado correctamente."
        )
        return 1

    cmd: list[str] = [streamlit_bin, "run", str(entry)]

    if args.port:
        cmd += ["--server.port", str(args.port)]

    if args.no_browser:
        cmd += ["--server.headless", "true"]

    logger.info(f"[app] Lanzando dashboard: {' '.join(cmd)}")

    # os.execvp reemplaza el proceso actual; no retorna si tiene éxito.
    os.execvp(streamlit_bin, cmd)

    # Nunca se alcanza salvo fallo del exec.
    return 1  # pragma: no cover


def register(subparsers: argparse._SubParsersAction) -> None:  # type: ignore[type-arg]
    """Registra el subcomando `app` en el parser principal."""
    parser: argparse.ArgumentParser = subparsers.add_parser(
        "app",
        help="Lanza el dashboard Streamlit de EmoParse.",
        description=(
            "Inicia el servidor Streamlit y abre el dashboard en el navegador.\n"
            "Equivalente a: streamlit run src/emoparse/app/__main__.py"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--port",
        type=int,
        default=None,
        metavar="PORT",
        help="Puerto en el que escucha Streamlit (default: 8501).",
    )
    parser.add_argument(
        "--no-browser",
        action="store_true",
        default=False,
        help="No abrir el navegador automáticamente al iniciar.",
    )
    parser.set_defaults(handler=handle)
