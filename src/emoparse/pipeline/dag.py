# ══════════════════════════════════════════════════════════════════════════════
#  emoparse.pipeline.dag
#
#  DAG declarativo de stages del pipeline.
# ══════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class StageNode:
    """Nodo del DAG de stages."""

    name: str
    deps: tuple[str, ...] = field(default_factory=tuple)


class StageDAG:
    """Grafo dirigido acíclico de stages del pipeline."""

    def __init__(self, nodes: list[StageNode]) -> None:
        names = [n.name for n in nodes]
        if len(set(names)) != len(names):
            dupes = {n for n in names if names.count(n) > 1}
            raise ValueError(f"Nombres de stage duplicados en el DAG: {dupes}")

        all_names = set(names)
        for node in nodes:
            unknown = set(node.deps) - all_names
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
        """Dependencias transitivas de una stage."""
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
                f"Stages desconocidas: {sorted(unknown)}. "
                f"Definidas: {sorted(self._nodes)}"
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
        """Topological sort de Kahn."""
        indegree: dict[str, int] = {n: 0 for n in self._nodes}
        consumers: dict[str, list[str]] = {n: [] for n in self._nodes}
        for node in self._nodes.values():
            for dep in node.deps:
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
            raise ValueError(
                f"Ciclo detectado en el DAG. Stages involucradas: "
                f"{sorted(ciclo)}"
            )
        return tuple(result)


# ══════════════════════════════════════════════════════════════════════════════
#  EMOPARSE_DAG — declaración canónica del pipeline.
# ══════════════════════════════════════════════════════════════════════════════

EMOPARSE_DAG = StageDAG(
    [
        StageNode("summarizer", deps=()),
        StageNode("metadata", deps=("summarizer",)),
        StageNode("enunciation", deps=("metadata",)),
        StageNode("actors", deps=("enunciation",)),
        StageNode("emotions", deps=("actors",)),
        StageNode("emotions_pass2", deps=("emotions",)),
        StageNode("explode_emociones", deps=("emotions",)),
        StageNode("characterizer", deps=("explode_emociones",)),
        StageNode("judge", deps=("characterizer",)),
    ]
)
