# ══════════════════════════════════════════════════════════════════════════════
#  emoparse.network
#
#  Análisis de redes de interacción sobre corpus de posts.
#
#  Sin LLM: grafos construidos desde `posts` y `tecno_entidades`, métricas,
#  comunidades y cliques con networkx (extra `network`), y acoplamiento con el
#  análisis emocional del run.
#
#  Tres criterios de agrupamiento, deliberadamente separados y comparables
#  entre sí porque los tres terminan en el mismo Louvain:
#
#  - interacción: quién responde, menciona, repostea, cita o sigue a quién.
#  - contenido: qué dicen los posts (`embeddings`, extra `embeddings`).
#  - narrativa: qué simulacro emocional montan (`simulacro_similarity`),
#    con los componentes del simulacro elegibles uno por uno.
#
#  Y dos lecturas de la circulación emocional: el perfil de cada comunidad
#  (`emotion_coupling`) y cómo la emoción se propaga entre ellas
#  (`emotion_flow`).
# ══════════════════════════════════════════════════════════════════════════════

from emoparse.network.builders import (
    GRAFO_FOLLOW,
    GRAFOS,
    GRAFOS_AUTOR,
    build_edges,
)
from emoparse.network.emotion_coupling import (
    community_emotion_profile,
    foria_by_post,
    foria_transition_matrix,
)
from emoparse.network.emotion_flow import (
    contagion_lift,
    flujo_entre_comunidades,
    foria_transition_by_scope,
    tipos_por_post,
)
from emoparse.network.metrics import (
    compute_node_metrics,
    detect_cliques,
    detect_communities,
    mutual_subgraph,
    to_graph,
)
from emoparse.network.simulacro_similarity import (
    COMPONENTES,
    COMPONENTES_DEFAULT,
    agrupar,
    build_features,
    componentes_disponibles,
    grupos_por_autor,
    perfil_grupos,
    similarity_pairs,
)

__all__ = [
    "GRAFOS",
    "GRAFOS_AUTOR",
    "GRAFO_FOLLOW",
    "build_edges",
    "to_graph",
    "compute_node_metrics",
    "detect_communities",
    "detect_cliques",
    "mutual_subgraph",
    "foria_by_post",
    "foria_transition_matrix",
    "community_emotion_profile",
    "tipos_por_post",
    "contagion_lift",
    "foria_transition_by_scope",
    "flujo_entre_comunidades",
    "COMPONENTES",
    "COMPONENTES_DEFAULT",
    "componentes_disponibles",
    "build_features",
    "similarity_pairs",
    "agrupar",
    "perfil_grupos",
    "grupos_por_autor",
]
