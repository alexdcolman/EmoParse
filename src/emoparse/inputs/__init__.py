"""Carga de discursos input desde CSV o JSON, y selección del corpus."""

from emoparse.inputs.loader import REQUIRED_COLUMNS, InputError, load_discursos
from emoparse.inputs.seleccion import (
    Seleccion,
    SeleccionError,
    aplicar_seleccion,
    load_seleccion,
)

__all__ = [
    "load_discursos",
    "InputError",
    "REQUIRED_COLUMNS",
    "Seleccion",
    "SeleccionError",
    "aplicar_seleccion",
    "load_seleccion",
]
