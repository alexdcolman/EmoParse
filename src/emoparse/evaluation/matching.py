# ══════════════════════════════════════════════════════════════════════════════
#  emoparse.evaluation.matching
#
#  Alineación de emociones detectadas contra un golden set y scoring.
#
#  Estrategia por unidad (codigo, unit_idx):
#  1. Se emparejan golden↔predichas de forma greedy por score descendente:
#     +2 si el tipo coincide (canonicalizado por la ontología de alias),
#     +1 si el experienciador coincide (igualdad laxa por solapamiento de
#     tokens normalizados). Solo se aceptan pares con score > 0.
#  2. Detección: TP = pares aceptados; FP = predichas sin par; FN = golden
#     sin par. De ahí precisión, recall y F1.
#  3. Dimensiones: sobre los pares aceptados se mide accuracy de tipo
#     (canónico), experienciador (laxo), modo_existencia y foria (si el
#     golden las trae).
# ══════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any

#: Dimensiones evaluables sobre pares emparejados.
DIMENSIONES: tuple[str, ...] = ("tipo", "experienciador", "modo_existencia", "foria")


@dataclass
class MatchReport:
    """Resultado agregado de la comparación golden vs run."""
    tp: int = 0
    fp: int = 0
    fn: int = 0
    dim_correctas: dict[str, int] = field(default_factory=dict)
    dim_evaluadas: dict[str, int] = field(default_factory=dict)
    unidades: int = 0
    desacuerdos: list[dict[str, Any]] = field(default_factory=list)

    @property
    def precision(self) -> float | None:
        d = self.tp + self.fp
        return self.tp / d if d else None

    @property
    def recall(self) -> float | None:
        d = self.tp + self.fn
        return self.tp / d if d else None

    @property
    def f1(self) -> float | None:
        p, r = self.precision, self.recall
        if p is None or r is None or (p + r) == 0:
            return None
        return 2 * p * r / (p + r)

    def dim_accuracy(self, dim: str) -> float | None:
        n = self.dim_evaluadas.get(dim, 0)
        return self.dim_correctas.get(dim, 0) / n if n else None


def build_alias_map(ontologia: dict[str, Any]) -> dict[str, str]:
    """alias normalizado → emoción canónica, desde emociones_ontologia.json."""
    alias_map: dict[str, str] = {}
    for canonico, entry in (ontologia.get("emociones") or {}).items():
        alias_map[_norm_token(canonico)] = canonico
        if isinstance(entry, dict):
            for alias in entry.get("aliases") or []:
                alias_map[_norm_token(str(alias))] = canonico
    return alias_map


def match_units(
    golden_units: dict[tuple[str, int], list[dict[str, Any]]],
    pred_units: dict[tuple[str, int], list[dict[str, Any]]],
    alias_map: dict[str, str],
) -> MatchReport:
    """Compara golden vs predicciones sobre las unidades del golden.

    Las unidades ausentes en `pred_units` cuentan sus golden como FN
    (el run no las procesó o no detectó nada).
    """
    report = MatchReport()
    for key, golds in golden_units.items():
        preds = list(pred_units.get(key, []))
        report.unidades += 1
        _match_one_unit(key, golds, preds, alias_map, report)
    return report


# ══════════════════════════════════════════════════════════════════════════════
#  Emparejamiento por unidad
# ══════════════════════════════════════════════════════════════════════════════

def _match_one_unit(
    key: tuple[str, int],
    golds: list[dict[str, Any]],
    preds: list[dict[str, Any]],
    alias_map: dict[str, str],
    report: MatchReport,
) -> None:
    candidatos: list[tuple[int, int, int]] = []  # (score, g_idx, p_idx)
    for g_idx, g in enumerate(golds):
        for p_idx, p in enumerate(preds):
            score = 0
            if _tipo_eq(g, p, alias_map):
                score += 2
            if _exp_eq(g, p):
                score += 1
            if score > 0:
                candidatos.append((score, g_idx, p_idx))

    usados_g: set[int] = set()
    usados_p: set[int] = set()
    pares: list[tuple[int, int]] = []
    for score, g_idx, p_idx in sorted(candidatos, key=lambda t: -t[0]):
        if g_idx in usados_g or p_idx in usados_p:
            continue
        usados_g.add(g_idx)
        usados_p.add(p_idx)
        pares.append((g_idx, p_idx))

    report.tp += len(pares)
    report.fp += len(preds) - len(usados_p)
    report.fn += len(golds) - len(usados_g)

    for g_idx, p_idx in pares:
        g, p = golds[g_idx], preds[p_idx]
        _score_dim(report, "tipo", _tipo_eq(g, p, alias_map), g, p, key)
        _score_dim(report, "experienciador", _exp_eq(g, p), g, p, key)
        for dim in ("modo_existencia", "foria"):
            g_val = _norm_token(str(g.get(dim) or ""))
            if not g_val:
                continue  # el golden no anota esa dimensión para este caso
            p_val = _norm_token(str(p.get(dim) or ""))
            _score_dim(report, dim, g_val == p_val, g, p, key)


def _score_dim(
    report: MatchReport,
    dim: str,
    correcto: bool,
    g: dict[str, Any],
    p: dict[str, Any],
    key: tuple[str, int],
) -> None:
    report.dim_evaluadas[dim] = report.dim_evaluadas.get(dim, 0) + 1
    if correcto:
        report.dim_correctas[dim] = report.dim_correctas.get(dim, 0) + 1
    elif len(report.desacuerdos) < 200:
        report.desacuerdos.append({
            "codigo": key[0], "unit_idx": key[1], "dimension": dim,
            "golden": g.get(dim if dim != "tipo" else "tipo_emocion"),
            "prediccion": p.get(dim if dim != "tipo" else "tipo_emocion"),
        })


# ══════════════════════════════════════════════════════════════════════════════
#  Igualdades
# ══════════════════════════════════════════════════════════════════════════════

def _tipo_eq(g: dict[str, Any], p: dict[str, Any], alias_map: dict[str, str]) -> bool:
    g_tipo = _canonico(str(g.get("tipo_emocion") or ""), alias_map)
    p_tipo = _canonico(
        str(p.get("tipo_emocion_canonico") or p.get("tipo_emocion") or ""),
        alias_map,
    )
    return bool(g_tipo) and g_tipo == p_tipo


def _exp_eq(g: dict[str, Any], p: dict[str, Any]) -> bool:
    """Igualdad laxa de experienciador: solapamiento de tokens de contenido."""
    g_toks = _tokens(str(g.get("experienciador") or ""))
    p_toks = _tokens(
        str(p.get("experienciador_canonico") or p.get("experienciador") or "")
    )
    if not g_toks or not p_toks:
        return False
    inter = g_toks & p_toks
    return len(inter) / min(len(g_toks), len(p_toks)) >= 0.5


def _canonico(valor: str, alias_map: dict[str, str]) -> str:
    tok = _norm_token(valor)
    return alias_map.get(tok, tok)


_STOP = {"el", "la", "los", "las", "un", "una", "de", "del", "al", "y", "e"}


def _tokens(valor: str) -> set[str]:
    return {
        t for t in re.split(r"[^\w@]+", _norm_token(valor))
        if t and t not in _STOP
    }


def _norm_token(valor: str) -> str:
    s = unicodedata.normalize("NFKD", valor.strip().lower())
    return "".join(ch for ch in s if not unicodedata.combining(ch))
