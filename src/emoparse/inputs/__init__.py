"""Carga de discursos input desde CSV o JSON."""

from emoparse.inputs.loader import REQUIRED_COLUMNS, InputError, load_discursos

__all__ = ["load_discursos", "InputError", "REQUIRED_COLUMNS"]
