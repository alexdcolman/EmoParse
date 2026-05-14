# ══════════════════════════════════════════════════════════════════════════════
#  emoparse.config.loader
#
#  Lectura de config.yaml y construcción de RunConfig validado.
#
#  Decisiones:
#  - Validación en lectura, no en uso. Si el YAML contiene errores,
#    se detectan al inicio del run.
#  - Errores con contexto: ValidationError de Pydantic incluye el path
#    JSON del campo malformado. Se captura y re-emite con mensaje que
#    agrega el archivo de origen para facilitar el debug.
# ══════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

import yaml
from loguru import logger
from pydantic import ValidationError

from emoparse.config.models import RunConfig


#: Pattern para variables de entorno: ${VAR} o ${VAR:-default}.
#: Soporta default vacío (`${VAR:-}`) y defaults con cualquier carácter
#: excepto `}`.
_ENV_VAR_PATTERN = re.compile(r"\$\{([A-Z_][A-Z0-9_]*)(?::-([^}]*))?\}")


class ConfigError(ValueError):
    """Error al cargar/validar el config. Incluye contexto del archivo."""


def load_config(path: Path | str) -> RunConfig:
    """Lee un YAML y devuelve un RunConfig validado.

    El YAML puede contener referencias a variables de entorno con la
    sintaxis `${VAR}` o `${VAR:-default}`. Se expanden antes del parsing
    YAML, así que pueden aparecer en cualquier valor (paths, model names,
    versions, etc.).

    Args:
        path: Ruta al archivo de config.

    Returns:
        RunConfig validado, listo para usar.

    Raises:
        ConfigError: archivo no existe, YAML malformado, o falla de
            validación.
    """
    p = Path(path).expanduser().resolve()
    if not p.is_file():
        raise ConfigError(f"Config file no encontrado: {p}")

    try:
        raw_text = p.read_text(encoding="utf-8")
    except OSError as e:
        raise ConfigError(f"No pude leer {p}: {e}") from e

    # Expansión de variables de entorno previa al parsing YAML.
    expanded_text = _expand_env_vars(raw_text)

    try:
        data = yaml.safe_load(expanded_text)
    except yaml.YAMLError as e:
        raise ConfigError(f"YAML inválido en {p}: {e}") from e

    if not isinstance(data, dict):
        raise ConfigError(
            f"El config en {p} debe ser un mapping (dict) en el top-level, "
            f"recibí: {type(data).__name__}"
        )

    try:
        cfg = RunConfig.model_validate(data)
    except ValidationError as e:
        raise ConfigError(
            f"Config inválido en {p}:\n{_format_validation_error(e)}"
        ) from e

    logger.info(
        f"[Config] Cargado {p} | "
        f"models={list(cfg.models)} | "
        f"stages={list(cfg.pipeline.stages)}"
    )
    return cfg


def _expand_env_vars(text: str) -> str:
    """Expande referencias ${VAR} y ${VAR:-default} en el texto.

    - ${VAR}            → os.environ["VAR"], o lanza ConfigError si no existe.
    - ${VAR:-default}   → os.environ.get("VAR", "default").
    - ${VAR:-}          → os.environ.get("VAR", "").

    No hay sintaxis de escape (no es necesaria; `${...}` es muy raro
    en valores YAML reales).
    """
    def _replace(m: re.Match[str]) -> str:
        var_name = m.group(1)
        default = m.group(2)
        value = os.environ.get(var_name)
        if value is not None:
            return value
        if default is not None:
            return default
        raise ConfigError(
            f"Variable de entorno '{var_name}' referenciada en config "
            f"pero no definida y sin default. Usá ${{{var_name}:-valor}} "
            f"para proveer un default."
        )
    return _ENV_VAR_PATTERN.sub(_replace, text)


def _format_validation_error(e: ValidationError) -> str:
    """Formatea un ValidationError para legibilidad en CLI/logs."""
    lines: list[str] = []
    for err in e.errors():
        loc = " → ".join(str(p) for p in err["loc"])
        lines.append(f"  - en `{loc}`: {err['msg']}")
    return "\n".join(lines)


def save_config(config: RunConfig, path: Path | str) -> None:
    """Serializa un RunConfig a YAML. Útil para snapshots de runs:
    RunsRepository guarda el config completo en `runs.config`.

    Args:
        config: RunConfig a serializar.
        path:   destino, sobrescribe.
    """
    p = Path(path).expanduser().resolve()
    p.parent.mkdir(parents=True, exist_ok=True)
    data: dict[str, Any] = config.model_dump(
        by_alias=False,
        exclude_none=True,
    )
    p.write_text(
        yaml.safe_dump(data, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    logger.info(f"[Config] Guardado en {p}")
