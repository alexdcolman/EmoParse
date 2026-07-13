# ══════════════════════════════════════════════════════════════════════════════
#  emoparse.pipeline.contracts
#
#  Contratos Pandera para DataFrames entre stages del pipeline.
# ══════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

import pandas as pd
import pandera.pandas as pa
from pandera.pandas import DataFrameModel
from pandera.typing.pandas import Series


class DiscursoInputContract(DataFrameModel):
    """DF de discursos post-ingest."""

    codigo: Series[str] = pa.Field(nullable=False)
    contenido: Series[str] = pa.Field(nullable=False)

    class Config:
        name = "DiscursoInputContract"
        strict = False  # Permite columnas adicionales (titulo, fecha, etc.).
        coerce = False


class PostInputContract(DataFrameModel):
    """DF de posts post-ingest (corpus de discurso nativo digital)."""

    post_id: Series[str] = pa.Field(nullable=False)
    plataforma: Series[str] = pa.Field(nullable=False)
    autor_handle: Series[str] = pa.Field(nullable=False)
    texto: Series[str] = pa.Field(nullable=False)  # '' solo en reposts puros
    tipo: Series[str] = pa.Field(
        nullable=False, isin=["original", "reply", "quote", "repost"]
    )
    es_repost_puro: Series[int] = pa.Field(nullable=False, isin=[0, 1])

    class Config:
        name = "PostInputContract"
        strict = False  # Permite columnas adicionales (fecha, metricas, etc.).
        coerce = False


class HiloContract(DataFrameModel):
    """DF de hilos agregados por el thread builder."""

    conversacion_id: Series[str] = pa.Field(nullable=False)
    post_raiz: Series[str] = pa.Field(nullable=False)
    n_posts: Series[int] = pa.Field(nullable=False, ge=1)
    profundidad_max: Series[int] = pa.Field(nullable=False, ge=0)

    class Config:
        name = "HiloContract"
        strict = False
        coerce = False


class FraseInputContract(DataFrameModel):
    """DF de frases sin anotación previa."""

    codigo: Series[str] = pa.Field(nullable=False)
    unit_idx: Series[int] = pa.Field(nullable=False, ge=0)
    frase: Series[str] = pa.Field(nullable=False)

    class Config:
        name = "FraseInputContract"
        strict = False
        coerce = False


class FraseConActoresContract(DataFrameModel):
    """DF de frases con la columna `actores` ya procesada."""

    codigo: Series[str] = pa.Field(nullable=False)
    unit_idx: Series[int] = pa.Field(nullable=False, ge=0)
    frase: Series[str] = pa.Field(nullable=False)
    actores: Series[object] = pa.Field(nullable=True)  # JSON string | None

    class Config:
        name = "FraseConActoresContract"
        strict = False
        coerce = False


class FraseParaLinkingContract(DataFrameModel):
    """DF de frases con actores y subset de menciones a linkear (T5)."""

    codigo: Series[str] = pa.Field(nullable=False)
    unit_idx: Series[int] = pa.Field(nullable=False, ge=0)
    frase: Series[str] = pa.Field(nullable=False)
    # Lista JSON-serializada de actores a normalizar para esa unidad.
    actores_a_linkear: Series[object] = pa.Field(nullable=False)

    class Config:
        name = "FraseParaLinkingContract"
        strict = False
        coerce = False


class FraseConEmocionesContract(DataFrameModel):
    """DF de frases con emociones de pase 1 ya detectadas."""

    codigo: Series[str] = pa.Field(nullable=False)
    unit_idx: Series[int] = pa.Field(nullable=False, ge=0)
    frase: Series[str] = pa.Field(nullable=False)
    emociones: Series[object] = pa.Field(nullable=True)

    class Config:
        name = "FraseConEmocionesContract"
        strict = False
        coerce = False


class EmocionExplodedContract(DataFrameModel):
    """DF de emociones 'explotadas' (una fila por emoción)."""

    codigo: Series[str] = pa.Field(nullable=False)
    frase_idx: Series[int] = pa.Field(nullable=False, ge=0)
    emocion_idx: Series[int] = pa.Field(nullable=False, ge=0)
    experienciador: Series[str] = pa.Field(nullable=False)
    tipo_emocion: Series[str] = pa.Field(nullable=False)
    fuente_marca: Series[str] = pa.Field(nullable=False)
    fuente_inferencia: Series[str] = pa.Field(nullable=False)
    modo_existencia: Series[str] = pa.Field(nullable=False)
    tipo_configuracion: Series[str] = pa.Field(nullable=True)

    class Config:
        name = "EmocionExplodedContract"
        strict = False
        coerce = False


def validate(contract: type[DataFrameModel], df: pd.DataFrame, lazy: bool = False) -> pd.DataFrame:
    """Valida un DataFrame contra un contrato Pandera.

    Args:
        contract: La clase DataFrameModel a usar como schema.
        df: El DataFrame a validar.
        lazy: Si True, acumula todos los errores antes de lanzar
            (útil en producción para diagnóstico completo).
            Si False (default), falla en el primer error.

    Returns:
        El mismo `df` recibido (sin coerciones).

    Raises:
        pandera.errors.SchemaError: si el DF no cumple el contrato.
    """
    contract.validate(df, lazy=lazy)
    return df
