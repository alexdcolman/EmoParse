# ══════════════════════════════════════════════════════════════════════════════
#  emoparse.inputs.seleccion
#
#  Selección declarativa de un subconjunto del corpus.
#
#  Acota qué unidades entran al análisis según los campos que el propio
#  input trae (fuente, autor, fecha, tipo, idioma, o cualquier columna
#  presente en el archivo). Se declara en un YAML:
#
#      seleccion:
#        - field: fuente
#          op: eq
#          value: bluesky
#        - field: fecha
#          op: between
#          value: ["2026-03-01", "2026-05-31"]
#
#  Los filtros se aplican en AND. El vocabulario de operaciones es el mismo
#  que el de las policies de reintento, para no tener dos sintaxis: acá se
#  evalúa sobre columnas del DataFrame de entrada, allá sobre el payload
#  JSON de una etapa ya corrida.
# ══════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

import pandas as pd
import yaml
from loguru import logger
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class SeleccionError(ValueError):
    """Selección mal declarada, o que no deja ninguna unidad."""


#: Operaciones admitidas.
#:   eq / ne          igual, distinto
#:   in               pertenece a una lista
#:   contains         la columna contiene el texto (sin distinguir mayúsculas)
#:   gte / lte        desde, hasta (fechas o números)
#:   between          rango cerrado; cualquiera de los dos extremos puede ir
#:                    en null para dejarlo abierto
#:   is_null          la columna está vacía o ausente
#:   is_not_null      la columna tiene valor
SeleccionOp = Literal[
    "eq", "ne", "in", "contains", "gte", "lte", "between",
    "is_null", "is_not_null",
]

_OPS_CON_VALOR: frozenset[str] = frozenset(
    {"eq", "ne", "in", "contains", "gte", "lte", "between"}
)

#: Cómo se lee cada operación en el resumen que se imprime y se persiste.
_LECTURA: dict[str, str] = {
    "eq": "igual a",
    "ne": "distinto de",
    "in": "entre",
    "contains": "contiene",
    "gte": "desde",
    "lte": "hasta",
    "between": "en el rango",
    "is_null": "sin valor",
    "is_not_null": "con valor",
}


class SelectorFiltro(BaseModel):
    """Un filtro sobre una columna del input."""

    model_config = ConfigDict(extra="forbid")

    field: str = Field(description="Columna del input sobre la que filtrar.")
    op: SeleccionOp = Field(default="eq")
    value: Any = Field(default=None)

    @field_validator("field")
    @classmethod
    def _field_no_vacio(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("field vacío.")
        return v.strip()

    @model_validator(mode="after")
    def _valor_coherente(self) -> SelectorFiltro:
        if self.op in _OPS_CON_VALOR and self.value is None:
            raise ValueError(
                f"La op '{self.op}' necesita 'value'. Para verificar "
                "ausencia, usá 'is_null' / 'is_not_null'."
            )
        if self.op == "in" and not isinstance(self.value, list):
            raise ValueError("La op 'in' necesita 'value' como lista.")
        if self.op == "between":
            if not isinstance(self.value, list) or len(self.value) != 2:
                raise ValueError(
                    "La op 'between' necesita 'value' como lista de dos "
                    "extremos; cualquiera puede ir en null para dejar el "
                    "rango abierto de ese lado."
                )
            if self.value[0] is None and self.value[1] is None:
                raise ValueError(
                    "La op 'between' con los dos extremos en null no filtra "
                    "nada. Usá 'gte' o 'lte' si el rango es abierto."
                )
        return self

    def leer(self) -> str:
        """Cómo se lee el filtro en una línea."""
        if self.op in ("is_null", "is_not_null"):
            return f"{self.field} {_LECTURA[self.op]}"
        return f"{self.field} {_LECTURA[self.op]} {self.value!r}"


class Seleccion(BaseModel):
    """Contenido del archivo de selección."""

    model_config = ConfigDict(extra="forbid")

    seleccion: list[SelectorFiltro] = Field(default_factory=list)

    @model_validator(mode="after")
    def _al_menos_uno(self) -> Seleccion:
        if not self.seleccion:
            raise ValueError(
                "El archivo no declara ningún filtro bajo 'seleccion'."
            )
        return self

    def leer(self) -> str:
        """Los filtros en una línea, tal como se aplican (en AND)."""
        return " y ".join(f.leer() for f in self.seleccion)


def load_seleccion(path: Path | str) -> Seleccion:
    """Carga y valida un archivo YAML de selección."""
    p = Path(path).expanduser().resolve()
    if not p.is_file():
        raise SeleccionError(f"Archivo de selección no encontrado: {p}")
    try:
        data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as e:
        raise SeleccionError(f"YAML inválido en {p}: {e}") from e
    if not isinstance(data, dict):
        raise SeleccionError(
            f"El YAML de {p} debe ser un mapping con la clave 'seleccion'."
        )
    try:
        return Seleccion.model_validate(data)
    except ValueError as e:
        raise SeleccionError(f"Selección inválida en {p}: {e}") from e


def aplicar_seleccion(df: pd.DataFrame, seleccion: Seleccion) -> pd.DataFrame:
    """Devuelve las filas del input que pasan todos los filtros.

    Falla con un mensaje explícito cuando un filtro nombra una columna que
    el input no tiene, o cuando el resultado queda vacío: un conjunto vacío
    devuelto en silencio se confunde con un corpus ya procesado.
    """
    mascara = pd.Series(True, index=df.index)
    for filtro in seleccion.seleccion:
        if filtro.field not in df.columns:
            raise SeleccionError(
                f"El input no tiene la columna '{filtro.field}'. "
                f"Columnas disponibles: {sorted(df.columns)}."
            )
        mascara &= _mascara_de(df[filtro.field], filtro)

    resultado = df[mascara].reset_index(drop=True)
    if resultado.empty:
        raise SeleccionError(
            f"Ninguna unidad del input cumple la selección ({seleccion.leer()}). "
            "Revisá los valores: el análisis no se corre sobre un corpus vacío."
        )
    logger.info(
        f"[Selección] {len(resultado)} de {len(df)} unidad(es) dentro del "
        f"alcance ({seleccion.leer()})."
    )
    return resultado


# ══════════════════════════════════════════════════════════════════════════════
#  Evaluación de un filtro
# ══════════════════════════════════════════════════════════════════════════════

def _mascara_de(serie: pd.Series, filtro: SelectorFiltro) -> pd.Series:
    """Máscara booleana de una columna para un filtro."""
    if filtro.op == "is_null":
        return serie.isna() | (serie.astype(str).str.strip() == "")
    if filtro.op == "is_not_null":
        return serie.notna() & (serie.astype(str).str.strip() != "")
    if filtro.op == "contains":
        return (
            serie.fillna("").astype(str)
            .str.contains(str(filtro.value), case=False, regex=False)
        )
    if filtro.op == "eq":
        return _texto(serie) == _texto_valor(filtro.value)
    if filtro.op == "ne":
        return _texto(serie) != _texto_valor(filtro.value)
    if filtro.op == "in":
        admitidos = {_texto_valor(v) for v in filtro.value}
        return _texto(serie).isin(admitidos)

    # Comparaciones de orden: fechas o números, según lo que declare el valor.
    if filtro.op == "gte":
        col, (desde,) = _ordenables(serie, [filtro.value])
        return col.notna() & (col >= desde)
    if filtro.op == "lte":
        col, (hasta,) = _ordenables(serie, [filtro.value])
        return col.notna() & (col <= hasta)
    if filtro.op == "between":
        col, (desde, hasta) = _ordenables(serie, list(filtro.value))
        mascara = col.notna()
        if desde is not None:
            mascara &= col >= desde
        if hasta is not None:
            mascara &= col <= hasta
        return mascara

    raise SeleccionError(f"Operación desconocida: {filtro.op}")


def _texto(serie: pd.Series) -> pd.Series:
    """Columna como texto normalizado, para las comparaciones de igualdad."""
    return serie.fillna("").astype(str).str.strip().str.casefold()


def _texto_valor(valor: Any) -> str:
    """Valor declarado como texto normalizado."""
    return str(valor).strip().casefold()


def _ordenables(
    serie: pd.Series, valores: list[Any]
) -> tuple[pd.Series, list[Any]]:
    """Convierte columna y extremos a un tipo comparable.

    El tipo lo decide el valor declarado, no la columna: si los extremos
    parsean como fecha, la columna se lee como fecha; si son números, como
    número. Así una columna de fechas en formatos mezclados (con y sin
    hora, con y sin zona) se compara bien contra un `2026-03-01` escrito a
    mano, que es el caso habitual.
    """
    declarados = [v for v in valores if v is not None]

    fechas = [pd.to_datetime(v, errors="coerce", utc=True) for v in declarados]
    if declarados and not any(pd.isna(f) for f in fechas):
        col = pd.to_datetime(serie, errors="coerce", utc=True, format="mixed")
        convertidos = [
            None if v is None else pd.to_datetime(v, errors="coerce", utc=True)
            for v in valores
        ]
        return col, convertidos

    if all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in declarados):
        return pd.to_numeric(serie, errors="coerce"), list(valores)

    return _texto(serie), [None if v is None else _texto_valor(v) for v in valores]
