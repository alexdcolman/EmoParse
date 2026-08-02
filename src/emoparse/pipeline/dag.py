# ══════════════════════════════════════════════════════════════════════════════
#  emoparse.pipeline.dag
#
#  DAG declarativo de stages del pipeline.
# ══════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class StageNode:
    """Nodo del DAG de stages.

    `deps` son dependencias duras: la stage no puede correr sin ellas y
    habilitarla exige habilitarlas. `soft_deps` son de orden: si la otra
    stage está habilitada, corre antes; si no, esta corre igual. Sirven para
    los enriquecedores opcionales —una stage que mejora su salida con el
    output de otra pero funciona sin él— sin volver obligatoria a la otra.
    """

    name: str
    deps: tuple[str, ...] = field(default_factory=tuple)
    soft_deps: tuple[str, ...] = field(default_factory=tuple)


class StageDAG:
    """Grafo dirigido acíclico de stages del pipeline."""

    def __init__(self, nodes: list[StageNode]) -> None:
        names = [n.name for n in nodes]
        if len(set(names)) != len(names):
            dupes = {n for n in names if names.count(n) > 1}
            raise ValueError(f"Nombres de stage duplicados en el DAG: {dupes}")

        all_names = set(names)
        for node in nodes:
            unknown = (set(node.deps) | set(node.soft_deps)) - all_names
            if unknown:
                raise ValueError(
                    f"Stage '{node.name}' depende de stages inexistentes: "
                    f"{sorted(unknown)}. Definidas: {sorted(all_names)}"
                )

        self._nodes: dict[str, StageNode] = {n.name: n for n in nodes}
        self._order: tuple[str, ...] = self._compute_toposort()

    # ── API ──────────────────────────────────────────────────────────────────

    def toposort(self) -> tuple[str, ...]:
        """Devuelve los nombres de stages en orden topológico."""
        return self._order

    def deps_of(self, name: str) -> tuple[str, ...]:
        """Dependencias directas de una stage."""
        if name not in self._nodes:
            raise KeyError(f"Stage desconocida: {name}")
        return self._nodes[name].deps

    def transitive_deps(self, name: str) -> set[str]:
        """Dependencias duras transitivas de una stage.

        Solo las duras: son las que hay que habilitar junto con la stage. Las
        blandas ordenan pero no arrastran, así que no entran acá.
        """
        if name not in self._nodes:
            raise KeyError(f"Stage desconocida: {name}")
        result: set[str] = set()
        stack = list(self._nodes[name].deps)
        while stack:
            d = stack.pop()
            if d in result:
                continue
            result.add(d)
            stack.extend(self._nodes[d].deps)
        return result

    def names(self) -> tuple[str, ...]:
        """Todos los nombres del DAG, en orden topológico."""
        return self._order

    def validate_subset(self, enabled: tuple[str, ...]) -> None:
        """Verifica coherencia de un subset de stages habilitadas."""
        enabled_set = set(enabled)
        unknown = enabled_set - set(self._nodes)
        if unknown:
            raise ValueError(
                f"Stages desconocidas: {sorted(unknown)}. Definidas: {sorted(self._nodes)}"
            )
        for name in enabled:
            missing = set(self._nodes[name].deps) - enabled_set
            if missing:
                raise ValueError(
                    f"Stage '{name}' está habilitada pero sus deps "
                    f"{sorted(missing)} no lo están. Habilitalas también "
                    f"o desactivá '{name}'."
                )

    # ── Helpers internos ─────────────────────────────────────────────────────

    def _compute_toposort(self) -> tuple[str, ...]:
        """Topological sort de Kahn.

        Ordena por dependencias duras y blandas: ambas imponen orden. La
        diferencia entre una y otra es de habilitación, no de secuencia, y
        se resuelve en `validate_subset` (la dura exige a su dep, la blanda
        no). Como todo el grafo es acíclico incluyendo las blandas, sumarlas
        acá no puede introducir ciclos.
        """
        indegree: dict[str, int] = {n: 0 for n in self._nodes}
        consumers: dict[str, list[str]] = {n: [] for n in self._nodes}
        for node in self._nodes.values():
            for dep in (*node.deps, *node.soft_deps):
                indegree[node.name] += 1
                consumers[dep].append(node.name)

        order_decl = list(self._nodes)
        ready = [n for n in order_decl if indegree[n] == 0]

        result: list[str] = []
        while ready:
            current = ready.pop(0)
            result.append(current)
            for cons in consumers[current]:
                indegree[cons] -= 1
                if indegree[cons] == 0:
                    ready.append(cons)
                    ready.sort(key=order_decl.index)

        if len(result) != len(self._nodes):
            ciclo = set(self._nodes) - set(result)
            raise ValueError(f"Ciclo detectado en el DAG. Stages involucradas: {sorted(ciclo)}")
        return tuple(result)


# ══════════════════════════════════════════════════════════════════════════════
#  EMOPARSE_DAG — declaración canónica del pipeline.
# ══════════════════════════════════════════════════════════════════════════════

EMOPARSE_DAG = StageDAG(
    [
        # Determinista, sin LLM: primera del pipeline en géneros de discurso
        # nativo digital (genre.technoparse=True). Sin dependientes duros:
        # anota tecnolingüísticos que las stages LLM consumen si están.
        StageNode("technoparse", deps=()),
        # Reframing clasifica citas/reposts desde `posts`: puede correr sola.
        # Cuando hay emociones materializadas, las del post citado entran al
        # prompt (el agente juzga su estatuto en vez de reinferirlas) y, si
        # además corrió characterizer, con su foria. Ambas son blandas: la
        # stage funciona sin ellas, solo con menos evidencia.
        StageNode(
            "reframing",
            deps=(),
            soft_deps=("explode_emotions", "characterizer"),
        ),
        # Ambas consumen `tecno_entidades`.
        StageNode("emoji_affect", deps=("technoparse",)),
        StageNode("hashtag_semiotics", deps=("technoparse",)),
        # Uso pragmático de menciones y tecnografismos en contexto.
        StageNode("tecno_usage", deps=("technoparse",)),
        # Multimodal: describe media adjunta; corre temprano para servir de
        # contexto a las stages de emociones. Requiere backend con --mmproj.
        StageNode("vision_describe", deps=()),
        StageNode("summarizer", deps=()),
        StageNode("metadata", deps=("summarizer",)),
        StageNode("enunciation", deps=("metadata",)),
        # actors enriquece a emotions pero no la condiciona: EmotionsStage
        # tolera su ausencia (pasa el contexto de actores vacío). Es soft_dep
        # para que, cuando ambas corran, actors vaya primero, sin volver
        # obligatorio a actors.
        StageNode("actors", deps=("enunciation",)),
        StageNode("emotions", deps=("enunciation",), soft_deps=("actors",)),
        StageNode("emotions_pass2", deps=("emotions",)),
        StageNode("explode_emotions", deps=("emotions",)),
        StageNode("deixis", deps=("explode_emotions",)),
        StageNode("modalidad", deps=("explode_emotions",)),
        StageNode("normalize_emotions", deps=("explode_emotions",)),
        StageNode("characterizer", deps=("normalize_emotions",)),
        StageNode("actants", deps=("explode_emotions",)),
        # El juez consume la operación de reframing como contexto: blanda,
        # porque corrige igual sin ella.
        StageNode("judge", deps=("characterizer",), soft_deps=("reframing",)),
        StageNode("semas", deps=("explode_emotions",)),
    ]
)
