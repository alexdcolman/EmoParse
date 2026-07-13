# ══════════════════════════════════════════════════════════════════════════════
#  emoparse.network
#
#  Análisis de redes de interacción sobre corpus de posts.
#
#  Sin LLM: grafos construidos desde `posts` y `tecno_entidades`, métricas y
#  comunidades con networkx (extra `network`), y acoplamiento con el análisis
#  emocional del run (perfiles fóricos por comunidad, matrices de transición
#  fórica en hilos).
# ══════════════════════════════════════════════════════════════════════════════

from emoparse.network.builders import GRAFOS, build_edges
from emoparse.network.emotion_coupling import (
    community_emotion_profile,
    foria_by_post,
    foria_transition_matrix,
)
from emoparse.network.metrics import (
    compute_node_metrics,
    detect_communities,
    to_graph,
)

__all__ = [
    "GRAFOS",
    "build_edges",
    "to_graph",
    "compute_node_metrics",
    "detect_communities",
    "foria_by_post",
    "foria_transition_matrix",
    "community_emotion_profile",
]
