# ══════════════════════════════════════════════════════════════════════════════
#  emoparse.app
#
#  API pública del dashboard Streamlit.
#
#  Reexporta helpers de lectura y estructuras utilizadas por la capa
#  visual para explorar runs ya ejecutados.
# ══════════════════════════════════════════════════════════════════════════════

from emoparse.app.data import (
    RunInfo,
    StageStatus,
    get_discursos,
    get_emociones,
    get_frases,
    get_run_stats,
    get_stage_statuses,
    list_runs,
)

__all__ = [
    "RunInfo",
    "StageStatus",
    "get_discursos",
    "get_emociones",
    "get_frases",
    "get_run_stats",
    "get_stage_statuses",
    "list_runs",
]
