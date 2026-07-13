# ══════════════════════════════════════════════════════════════════════════════
#  emoparse.evaluation.agreement
#
#  Alpha de Krippendorff para acuerdo inter-anotador.
#
#  Implementación propia (sin dependencias) del algoritmo canónico por matriz
#  de coincidencias, con soporte de valores faltantes y tres métricas de
#  distancia: nominal (categorías), ordinal (rangos) e interval (numérica).
#  Verificada contra los valores publicados del ejemplo clásico de
#  Krippendorff (4 anotadores, 12 unidades): nominal ≈ 0.743,
#  interval ≈ 0.849, ordinal ≈ 0.815.
# ══════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

from collections import Counter
from typing import Any, Hashable, Literal, Sequence

Metric = Literal["nominal", "ordinal", "interval"]

#: Marcadores tratados como valor faltante.
_MISSING = {None, "", "na", "n/a", "nan", "none"}


def krippendorff_alpha(
    reliability_data: Sequence[Sequence[Any]],
    metric: Metric = "nominal",
) -> float | None:
    """Alpha de Krippendorff sobre una matriz anotadores × unidades.

    Args:
        reliability_data: Una fila por anotador, una columna por unidad.
            Los faltantes se marcan con None/''/'NA' (insensible a caso).
        metric: 'nominal' para categorías, 'ordinal' para escalas ordenadas
            (los valores deben ser comparables/casteables a float para
            ordenar), 'interval' para numéricas.

    Returns:
        Alpha en [-1, 1] aproximadamente (1 = acuerdo perfecto, 0 = azar),
        o None si no hay suficientes datos apareables (menos de dos
        unidades con dos o más anotaciones, o una sola categoría en uso:
        con una única categoría el desacuerdo esperado es 0 y alpha es
        indefinido).
    """
    # Unidades con al menos dos anotaciones.
    n_units = max((len(fila) for fila in reliability_data), default=0)
    unidades: list[list[Any]] = []
    for u in range(n_units):
        valores = []
        for fila in reliability_data:
            if u < len(fila) and not _is_missing(fila[u]):
                valores.append(_norm(fila[u], metric))
        if len(valores) >= 2:
            unidades.append(valores)
    if len(unidades) < 2:
        return None

    # Matriz de coincidencias.
    coincidencias: Counter[tuple[Hashable, Hashable]] = Counter()
    for valores in unidades:
        m = len(valores)
        for i, c in enumerate(valores):
            for j, k in enumerate(valores):
                if i != j:
                    coincidencias[(c, k)] += 1.0 / (m - 1)  # type: ignore[assignment]

    categorias = sorted({c for c, _ in coincidencias})
    n_c = {c: sum(v for (a, _), v in coincidencias.items() if a == c)
           for c in categorias}
    n_total = sum(n_c.values())
    if len(categorias) < 2 or n_total <= 1:
        return None

    delta = _delta_fn(metric, categorias, n_c)

    do = sum(
        v * delta(c, k) for (c, k), v in coincidencias.items() if c != k
    ) / n_total
    de = sum(
        n_c[c] * n_c[k] * delta(c, k)
        for c in categorias for k in categorias if c != k
    ) / (n_total * (n_total - 1))
    if de == 0:
        return None
    return 1.0 - do / de


def _delta_fn(metric: Metric, categorias: list, n_c: dict):
    """Función de distancia al cuadrado según la métrica."""
    if metric == "nominal":
        return lambda c, k: 0.0 if c == k else 1.0
    if metric == "interval":
        return lambda c, k: (float(c) - float(k)) ** 2
    # ordinal: delta = (suma de marginales entre c y k - (n_c+n_k)/2)^2
    orden = sorted(categorias, key=float)
    pos = {c: i for i, c in enumerate(orden)}

    def delta(c, k):
        i, j = sorted((pos[c], pos[k]))
        acumulado = sum(n_c[orden[g]] for g in range(i, j + 1))
        return (acumulado - (n_c[c] + n_c[k]) / 2.0) ** 2

    return delta


def _is_missing(valor: Any) -> bool:
    if valor is None:
        return True
    if isinstance(valor, float) and valor != valor:  # NaN
        return True
    return str(valor).strip().lower() in _MISSING


def _norm(valor: Any, metric: Metric) -> Hashable:
    """Normaliza el valor: numérico para ordinal/interval, string en nominal."""
    if metric in ("ordinal", "interval"):
        return float(valor)
    return str(valor).strip().lower()
