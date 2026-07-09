# ══════════════════════════════════════════════════════════════════════════════
#  emoparse.app.components._emofilter
#
#  Panel de filtrado de emociones reutilizable: por referente (experienciador /
#  fuente) canónico, por sema de cada uno y por valores de caracterización. Opera
#  sobre las emociones enriquecidas (`data.get_emociones_enriched`).
#
#  Semántica: dentro de una dimensión, unión (OR) de los valores elegidos; entre
#  dimensiones/secciones, intersección (AND). Un selector vacío no restringe.
# ══════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

import unicodedata
from typing import Any

import pandas as pd
import streamlit as st


#: Dimensiones de caracterización expuestas como filtro (columna, etiqueta, Literal).
_CARAC_DIMS: tuple[tuple[str, str, str], ...] = (
    ("modo_existencia", "Modo de existencia", "ModoExistenciaEmocion"),
    ("foria", "Foria", "Foria"),
    ("dominancia", "Dominancia", "Dominancia"),
    ("intensidad", "Intensidad", "Intensidad"),
    ("duracion", "Duración", "TipoDuracion"),
    ("temporalidad", "Temporalidad", "Temporalidad"),
    ("aspecto", "Aspecto", "Aspecto"),
    ("tipo_atribucion", "Tipo de atribución", "TipoAtribucion"),
)


def _fold(s: Any) -> str:
    txt = unicodedata.normalize("NFKD", str(s or ""))
    return "".join(c for c in txt if not unicodedata.combining(c)).strip().lower()


def _safe_opts(litname: str) -> list[str]:
    """Valores de un `Literal` del schema (única fuente de verdad del vocabulario)."""
    try:
        from typing import get_args

        from emoparse.core import schemas as _sc

        return [str(v) for v in get_args(getattr(_sc, litname))]
    except Exception:
        return []


def _dim_options(df: pd.DataFrame, col: str, litname: str) -> list[str]:
    """Opciones de una dimensión: las del schema, más cualquier valor presente."""
    opts = list(_safe_opts(litname))
    if col in df.columns:
        seen = {str(v) for v in df[col].dropna().unique() if str(v).strip()}
        for v in sorted(seen):
            if v not in opts:
                opts.append(v)
    return opts


def _uniq_list_col(df: pd.DataFrame, col: str) -> list[str]:
    """Valores distintos de una columna de listas (canónicos por emoción)."""
    out: set[str] = set()
    if col in df.columns:
        for v in df[col]:
            if isinstance(v, (list, tuple, set)):
                out.update(str(x) for x in v if str(x).strip())
    return sorted(out)


def _mask_list_col(df: pd.DataFrame, col: str, selected: list[str]) -> pd.Series:
    """Fila conservada si la lista de `col` interseca `selected`."""
    sel = set(selected)
    return df[col].apply(
        lambda v: bool(sel & set(v)) if isinstance(v, (list, tuple, set)) else False
    )


def filter_panel(
    df: pd.DataFrame,
    *,
    key: str,
    semas_options: list[str],
    title: str | None = None,
    expanded: bool = False,
) -> pd.DataFrame:
    """Renderiza un panel de filtro y devuelve el sub-DataFrame filtrado.

    `df` debe venir de `data.get_emociones_enriched` (trae los canónicos y semas
    resueltos por emoción). Cada panel es independiente: usar un `key` distinto por
    discurso permite filtrar cada uno por su cuenta en la comparación.
    """
    if df.empty:
        return df

    with st.expander(title or "Filtros", expanded=expanded):
        c1, c2 = st.columns(2)
        with c1:
            exp_refs = st.multiselect(
                "Experienciador — referentes",
                _uniq_list_col(df, "experienciador_canonicos"),
                key=f"{key}_expref",
            )
            exp_semas = st.multiselect(
                "Experienciador — semas", semas_options, key=f"{key}_expsem",
            )
        with c2:
            fte_refs = st.multiselect(
                "Fuente — referentes",
                _uniq_list_col(df, "fuente_canonicos"),
                key=f"{key}_fteref",
            )
            fte_semas = st.multiselect(
                "Fuente — semas", semas_options, key=f"{key}_ftesem",
            )

        carac_sel: dict[str, list[str]] = {}
        cols = st.columns(2)
        for i, (col, label, lit) in enumerate(_CARAC_DIMS):
            opts = _dim_options(df, col, lit)
            if not opts:
                continue
            with cols[i % 2]:
                sel = st.multiselect(label, opts, key=f"{key}_{col}")
            if sel:
                carac_sel[col] = sel

    out = df
    if exp_refs:
        out = out[_mask_list_col(out, "experienciador_canonicos", exp_refs)]
    if exp_semas:
        out = out[_mask_list_col(out, "experienciador_semas", exp_semas)]
    if fte_refs:
        out = out[_mask_list_col(out, "fuente_canonicos", fte_refs)]
    if fte_semas:
        out = out[_mask_list_col(out, "fuente_semas", fte_semas)]
    for col, sel in carac_sel.items():
        folded = {_fold(v) for v in sel}
        out = out[out[col].apply(lambda v: _fold(v) in folded)]
    return out
