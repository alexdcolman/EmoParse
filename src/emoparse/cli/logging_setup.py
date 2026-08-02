# ══════════════════════════════════════════════════════════════════════════════
#  emoparse.cli.logging_setup
#
#  Configuración de los destinos de log del CLI.
#
#  Dos destinos con criterios distintos:
#  - Consola (stderr): nivel según las flags globales (-v / -q). Es lo que
#    se lee mientras corre.
#  - Archivo: siempre en DEBUG, con rotación. Es lo que se lee después,
#    cuando un run de horas falló en la tercera etapa y la consola ya no
#    está. Un run se reanuda muchas veces, así que cada invocación escribe
#    su propio archivo.
#
#  El directorio se resuelve por precedencia: --log-dir, la variable de
#  entorno EMOPARSE_LOG_DIR, y por último `logs/` en el directorio actual.
# ══════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

import re
import sys
from datetime import datetime
from pathlib import Path

from loguru import logger

#: Directorio de logs por default, relativo al directorio de trabajo.
_DEFAULT_LOG_DIR = "logs"

#: Variable de entorno que sobrescribe el directorio por default.
_LOG_DIR_ENV = "EMOPARSE_LOG_DIR"

#: Tamaño al que rota el archivo, y cuántos archivos rotados se conservan.
_ROTATION = "20 MB"
_RETENTION = 20

#: Caracteres admitidos en el nombre del archivo; el resto se colapsa a "-".
_NOMBRE_INVALIDO = re.compile(r"[^A-Za-z0-9._-]+")


def configure(
    verbose: bool = False,
    quiet: bool = False,
    log_dir: str | Path | None = None,
    no_log_file: bool = False,
    comando: str | None = None,
    etiqueta: str | None = None,
) -> Path | None:
    """Instala los destinos de log y devuelve el archivo escrito, si hay.

    `etiqueta` identifica la corrida dentro del nombre del archivo (el
    run-id, o el nombre de la base cuando el comando opera sobre una).
    Devuelve None cuando el archivo se desactivó o no se pudo crear: un
    problema de logging nunca interrumpe el comando.
    """
    logger.remove()
    logger.add(sys.stderr, level=_nivel(verbose, quiet))

    if no_log_file:
        return None

    destino = _resolver_dir(log_dir)
    try:
        destino.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        logger.warning(
            f"No pude crear el directorio de logs {destino}: {e}. Sigo solo con la consola."
        )
        return None

    archivo = destino / _nombre(comando, etiqueta)
    try:
        logger.add(
            archivo,
            level="DEBUG",
            rotation=_ROTATION,
            retention=_RETENTION,
            encoding="utf-8",
            # Las stages por frase corren en un pool de hilos: sin cola, las
            # líneas de distintos hilos se entrelazan dentro del archivo.
            enqueue=True,
            backtrace=True,
            # `diagnose` volcaría el valor de las variables locales en los
            # tracebacks, y ahí viaja texto del corpus: rompería la garantía
            # de los corpus seudonimizados.
            diagnose=False,
        )
    except OSError as e:
        logger.warning(f"No pude escribir el log en {archivo}: {e}. Sigo solo con la consola.")
        return None
    return archivo


def etiqueta_de(args) -> str | None:
    """Deriva la etiqueta del nombre de archivo desde los args del comando.

    Prefiere el run-id explícito; si no hay, usa el nombre de la base sobre
    la que opera el comando, que es lo que identifica la corrida en los
    subcomandos de lectura.
    """
    run_id = getattr(args, "run_id", None)
    if run_id:
        return str(run_id)
    db = getattr(args, "db", None)
    if db:
        return Path(str(db)).stem
    return None


def _nivel(verbose: bool, quiet: bool) -> str:
    """Nivel de la consola. Con ambas flags, verbose tiene precedencia."""
    if verbose:
        return "DEBUG"
    if quiet:
        return "WARNING"
    return "INFO"


def _resolver_dir(log_dir: str | Path | None) -> Path:
    """Directorio de logs por precedencia: flag, entorno, default."""
    import os

    if log_dir:
        return Path(log_dir).expanduser()
    del_entorno = os.getenv(_LOG_DIR_ENV)
    if del_entorno:
        return Path(del_entorno).expanduser()
    return Path(_DEFAULT_LOG_DIR)


def _nombre(comando: str | None, etiqueta: str | None) -> str:
    """Nombre del archivo: `<comando>_<etiqueta>_<timestamp>.log`."""
    partes = [
        _limpiar(comando or "emoparse"),
        _limpiar(etiqueta or "sin-run"),
        datetime.now().strftime("%Y%m%d-%H%M%S"),
    ]
    return "_".join(partes) + ".log"


def _limpiar(valor: str) -> str:
    """Reduce un valor arbitrario a un fragmento de nombre de archivo seguro."""
    limpio = _NOMBRE_INVALIDO.sub("-", valor).strip("-.")
    return limpio or "sin-nombre"
