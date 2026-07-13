# ══════════════════════════════════════════════════════════════════════════════
#  emoparse.evaluation
#
#  Infraestructura de evaluación: golden sets de regresión, acuerdo
#  inter-anotador (alpha de Krippendorff), muestreo para anotación a ciegas
#  y controles de sobre-detección. CLI: `emoparse eval`.
# ══════════════════════════════════════════════════════════════════════════════

from emoparse.evaluation.agreement import krippendorff_alpha
from emoparse.evaluation.matching import MatchReport, build_alias_map, match_units

__all__ = [
    "krippendorff_alpha",
    "MatchReport",
    "build_alias_map",
    "match_units",
]
