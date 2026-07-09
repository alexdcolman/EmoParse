# ══════════════════════════════════════════════════════════════════════════════
#  tests.unit.test_pipeline_dag
#
#  Tests del DAG declarativo de stages.
# ══════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

import pytest

from emoparse.pipeline.dag import EMOPARSE_DAG, StageDAG, StageNode


# ══════════════════════════════════════════════════════════════════════════════
#  Construcción y validación del grafo
# ══════════════════════════════════════════════════════════════════════════════


class TestStageDAGConstruction:

    def test_simple_linear(self) -> None:
        dag = StageDAG([
            StageNode("a"),
            StageNode("b", deps=("a",)),
            StageNode("c", deps=("b",)),
        ])
        assert dag.toposort() == ("a", "b", "c")

    def test_independent_branches_preserve_declaration_order(self) -> None:
        """Cuando varios nodos están listos a la vez, el orden de
        declaración manda (determinístico)."""
        dag = StageDAG([
            StageNode("a"),
            StageNode("b"),
            StageNode("c"),
        ])
        assert dag.toposort() == ("a", "b", "c")

    def test_diamond(self) -> None:
        dag = StageDAG([
            StageNode("root"),
            StageNode("left", deps=("root",)),
            StageNode("right", deps=("root",)),
            StageNode("merge", deps=("left", "right")),
        ])
        order = dag.toposort()
        assert order[0] == "root"
        assert order[-1] == "merge"
        assert set(order[1:3]) == {"left", "right"}

    def test_duplicate_names_rejected(self) -> None:
        with pytest.raises(ValueError, match="duplicados"):
            StageDAG([StageNode("a"), StageNode("a")])

    def test_unknown_dep_rejected(self) -> None:
        with pytest.raises(ValueError, match="inexistentes"):
            StageDAG([StageNode("a", deps=("missing",))])

    def test_cycle_rejected(self) -> None:
        with pytest.raises(ValueError, match="[Cc]iclo"):
            StageDAG([
                StageNode("a", deps=("b",)),
                StageNode("b", deps=("a",)),
            ])

    def test_self_cycle_rejected(self) -> None:
        with pytest.raises(ValueError, match="[Cc]iclo|inexistentes"):
            StageDAG([StageNode("a", deps=("a",))])


# ══════════════════════════════════════════════════════════════════════════════
#  Queries del DAG
# ══════════════════════════════════════════════════════════════════════════════


class TestStageDAGQueries:

    def test_deps_of_returns_direct_deps(self) -> None:
        dag = StageDAG([
            StageNode("a"),
            StageNode("b", deps=("a",)),
            StageNode("c", deps=("a", "b")),
        ])
        assert dag.deps_of("a") == ()
        assert dag.deps_of("b") == ("a",)
        assert dag.deps_of("c") == ("a", "b")

    def test_transitive_deps(self) -> None:
        dag = StageDAG([
            StageNode("a"),
            StageNode("b", deps=("a",)),
            StageNode("c", deps=("b",)),
            StageNode("d", deps=("c",)),
        ])
        assert dag.transitive_deps("a") == set()
        assert dag.transitive_deps("d") == {"a", "b", "c"}

    def test_deps_of_unknown_raises(self) -> None:
        dag = StageDAG([StageNode("a")])
        with pytest.raises(KeyError):
            dag.deps_of("missing")


class TestValidateSubset:

    def test_valid_subset(self) -> None:
        dag = StageDAG([
            StageNode("a"),
            StageNode("b", deps=("a",)),
        ])
        # Solo 'a' es válido.
        dag.validate_subset(("a",))
        # 'a' + 'b' es válido.
        dag.validate_subset(("a", "b"))

    def test_missing_dep_raises(self) -> None:
        dag = StageDAG([
            StageNode("a"),
            StageNode("b", deps=("a",)),
        ])
        with pytest.raises(ValueError, match="deps"):
            dag.validate_subset(("b",))  # falta 'a'

    def test_unknown_stage_in_subset_raises(self) -> None:
        dag = StageDAG([StageNode("a")])
        with pytest.raises(ValueError, match="desconocidas"):
            dag.validate_subset(("a", "ghost"))


# ══════════════════════════════════════════════════════════════════════════════
#  EMOPARSE_DAG concreto
# ══════════════════════════════════════════════════════════════════════════════


class TestEmoparseDAG:

    def test_canonical_order(self) -> None:
        """El toposort del DAG real preserva el orden histórico del
        pipeline. Si esto cambia, hay que revisar que ningún consumidor
        downstream dependa del orden viejo."""
        order = EMOPARSE_DAG.toposort()
        # Posiciones relativas que importan (deps lógicas):
        idx = {name: i for i, name in enumerate(order)}
        assert idx["summarizer"] < idx["metadata"]
        assert idx["metadata"] < idx["enunciation"]
        assert idx["enunciation"] < idx["actors"]
        assert idx["actors"] < idx["emotions"]
        assert idx["emotions"] < idx["explode_emotions"]
        assert idx["explode_emotions"] < idx["characterizer"]
        assert idx["characterizer"] < idx["judge"]
        assert idx["emotions"] < idx["emotions_pass2"]

    def test_judge_is_leaf(self) -> None:
        """Nada depende de judge: es la stage final del DAG."""
        order = EMOPARSE_DAG.toposort()
        for name in order:
            assert "judge" not in EMOPARSE_DAG.deps_of(name), (
                f"Stage '{name}' depende de 'judge'; pero judge debe ser hoja."
            )

    def test_emotions_pass2_optional(self) -> None:
        """emotions_pass2 NO está en el camino crítico: explode_emotions
        depende solo de emotions, no de emotions_pass2."""
        assert "emotions_pass2" not in EMOPARSE_DAG.transitive_deps(
            "explode_emotions"
        )
        assert "emotions_pass2" not in EMOPARSE_DAG.transitive_deps(
            "characterizer"
        )
