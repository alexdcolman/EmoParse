# ══════════════════════════════════════════════════════════════════════════════
#  emoparse.inputs.loader
#
#  Carga discursos desde CSV o JSON.
# ══════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd
from loguru import logger


class InputError(ValueError):
    """Error al cargar discursos."""


#: Columnas obligatorias en el DF resultante.
REQUIRED_COLUMNS: tuple[str, ...] = ("codigo", "contenido")


def load_discursos(path: Path | str) -> pd.DataFrame:
    """Carga discursos desde CSV o JSON y devuelve DataFrame validado."""
    p = Path(path).expanduser().resolve()
    if not p.is_file():
        raise InputError(f"Archivo input no encontrado: {p}")

    ext = p.suffix.lower()
    if ext == ".csv":
        df = _load_csv(p)
    elif ext == ".json":
        df = _load_json(p)
    else:
        raise InputError(
            f"Extensión no soportada: '{ext}'. Use .csv o .json."
        )

    _validate_columns(df, p)
    _validate_no_empty_codigo(df, p)
    _validate_unique_codigos(df, p)
    _validate_no_empty_content(df, p)

    logger.info(
        f"[Inputs] Cargados {len(df)} discursos desde {p.name} "
        f"(columnas: {list(df.columns)})"
    )
    return df


# ══════════════════════════════════════════════════════════════════════════════
#  Lectores por formato
# ══════════════════════════════════════════════════════════════════════════════

def _load_csv(path: Path) -> pd.DataFrame:
    """Lee un CSV con pandas."""
    try:
        df = pd.read_csv(path, encoding="utf-8", dtype={"codigo": str})
    except UnicodeDecodeError as e:
        raise InputError(
            f"Encoding inválido en {path} (esperaba UTF-8): {e}. "
            "Tip: si el archivo viene de Excel, guardalo como CSV UTF-8."
        ) from e
    except (pd.errors.EmptyDataError, pd.errors.ParserError) as e:
        raise InputError(f"CSV malformado en {path}: {e}") from e
    return df


def _load_json(path: Path) -> pd.DataFrame:
    """Lee un JSON en formato lista o dict y devuelve DataFrame."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as e:
        raise InputError(f"No pude leer {path}: {e}") from e
    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        raise InputError(f"JSON inválido en {path}: {e}") from e

    rows: list[dict[str, Any]] = []
    if isinstance(data, list):
        if not all(isinstance(item, dict) for item in data):
            raise InputError(
                f"JSON de {path} es una lista pero contiene items que "
                f"no son dicts. Verificá el formato."
            )
        rows = list(data)
    elif isinstance(data, dict):
        for codigo, payload in data.items():
            if not isinstance(payload, dict):
                raise InputError(
                    f"En {path}, la entrada '{codigo}' debe ser un dict, "
                    f"recibí: {type(payload).__name__}"
                )
            if "codigo" in payload and payload["codigo"] != codigo:
                raise InputError(
                    f"En {path}, la entrada '{codigo}' tiene un campo "
                    f"`codigo='{payload['codigo']}'` que no coincide con la key. "
                    "Eliminá el campo `codigo` interno o hacé que coincida."
                )
            rows.append({"codigo": codigo, **payload})
    else:
        raise InputError(
            f"JSON de {path} debe ser lista o dict, recibí: {type(data).__name__}"
        )

    if not rows:
        raise InputError(f"JSON de {path} no contiene discursos.")

    return pd.DataFrame(rows)


# ══════════════════════════════════════════════════════════════════════════════
#  Validaciones
# ══════════════════════════════════════════════════════════════════════════════

def _validate_columns(df: pd.DataFrame, path: Path) -> None:
    """Verifica columnas obligatorias."""
    missing = [c for c in REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        raise InputError(
            f"En {path}, faltan columnas obligatorias: {missing}. "
            f"Columnas presentes: {list(df.columns)}"
        )


def _validate_no_empty_codigo(df: pd.DataFrame, path: Path) -> None:
    """Verifica que `codigo` no esté vacío/NaN.

    El código es el identificador único de cada discurso y la clave que
    enlaza las tablas `discursos`, `frases` y `emociones`. Un código vacío
    rompe la trazabilidad y, con varios discursos, colisiona en la
    validación de unicidad de forma poco transparente; conviene rechazarlo
    en la entrada.
    """
    empty_mask = df["codigo"].fillna("").astype(str).str.strip() == ""
    n_empty = int(empty_mask.sum())
    if n_empty > 0:
        raise InputError(
            f"En {path}, hay {n_empty} discurso(s) con `codigo` vacío. "
            "El código identifica de forma única a cada discurso y no puede "
            "quedar en blanco."
        )


def _validate_unique_codigos(df: pd.DataFrame, path: Path) -> None:
    """Verifica que los códigos sean únicos."""
    duplicates = df["codigo"][df["codigo"].duplicated()].unique()
    if len(duplicates) > 0:
        raise InputError(
            f"En {path}, hay códigos duplicados: {list(duplicates[:5])}"
            + ("..." if len(duplicates) > 5 else "")
        )


def _validate_no_empty_content(df: pd.DataFrame, path: Path) -> None:
    """Verifica que `contenido` no esté vacío/NaN."""
    empty_mask = df["contenido"].fillna("").astype(str).str.strip() == ""
    n_empty = int(empty_mask.sum())
    if n_empty > 0:
        codigos_vacios = df.loc[empty_mask, "codigo"].tolist()
        raise InputError(
            f"En {path}, hay {n_empty} discurso(s) con `contenido` vacío. "
            f"Códigos: {codigos_vacios[:5]}"
            + ("..." if n_empty > 5 else "")
        )
