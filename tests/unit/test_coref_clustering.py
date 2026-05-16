# ══════════════════════════════════════════════════════════════════════════════
#  tests.unit.test_coref_clustering
#
#  Tests para `pipeline.coref`: clustering léxico conservador.
# ══════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

from emoparse.pipeline.coref import (
    cluster_mentions_within_discurso,
    pick_representative,
)


def _make(*items: tuple[int, list[dict]]) -> list[tuple[int, list[dict]]]:
    """Convierte la lista de tuplas a la forma esperada por el clustering."""
    return list(items)


class TestExactMatch:

    def test_groups_identical_normalized_mentions(self) -> None:
        actors_by_frase = _make(
            (0, [{"actor": "Milei"}]),
            (1, [{"actor": "milei"}]),    # mismo, distinto case
            (2, [{"actor": "Milei "}]),   # mismo, espacio extra
        )
        clusters = cluster_mentions_within_discurso(actors_by_frase)
        assert len(clusters) == 1
        assert clusters[0] == {(0, 0), (1, 0), (2, 0)}

    def test_groups_with_and_without_accent(self) -> None:
        actors_by_frase = _make(
            (0, [{"actor": "Cristina Fernández"}]),
            (1, [{"actor": "cristina fernandez"}]),
        )
        clusters = cluster_mentions_within_discurso(actors_by_frase)
        assert len(clusters) == 1


class TestTokenSubsetMatch:

    def test_groups_milei_with_javier_milei(self) -> None:
        """'Milei' y 'Javier Milei' comparten 'milei' → mismo cluster."""
        actors_by_frase = _make(
            (0, [{"actor": "Javier Milei"}]),
            (1, [{"actor": "Milei"}]),
        )
        clusters = cluster_mentions_within_discurso(actors_by_frase)
        assert len(clusters) == 1
        assert clusters[0] == {(0, 0), (1, 0)}

    def test_groups_three_variants_transitively(self) -> None:
        """Milei ↔ Javier Milei ↔ Javier Gerardo Milei se agrupan."""
        actors_by_frase = _make(
            (0, [{"actor": "Milei"}]),
            (1, [{"actor": "Javier Milei"}]),
            (2, [{"actor": "Javier Gerardo Milei"}]),
        )
        clusters = cluster_mentions_within_discurso(actors_by_frase)
        assert len(clusters) == 1


class TestConservativeDoesNotGroup:

    def test_does_not_group_role_description_without_overlap(self) -> None:
        """'el presidente' y 'Milei' no comparten tokens → NO se agrupan.

        El coref léxico es conservador a propósito. La resolución de
        descripciones por rol queda para el LLM (Paso B).
        """
        actors_by_frase = _make(
            (0, [{"actor": "el presidente"}]),
            (1, [{"actor": "Milei"}]),
        )
        clusters = cluster_mentions_within_discurso(actors_by_frase)
        # Dos clusters separados.
        assert len(clusters) == 2

    def test_does_not_group_when_only_stopwords_overlap(self) -> None:
        """'el gobierno' y 'el pueblo' solo comparten 'el' (stopword)."""
        actors_by_frase = _make(
            (0, [{"actor": "el gobierno"}]),
            (1, [{"actor": "el pueblo"}]),
        )
        clusters = cluster_mentions_within_discurso(actors_by_frase)
        assert len(clusters) == 2

    def test_different_entities_stay_separate(self) -> None:
        actors_by_frase = _make(
            (0, [{"actor": "Milei"}, {"actor": "Cristina"}]),
            (1, [{"actor": "Macri"}]),
        )
        clusters = cluster_mentions_within_discurso(actors_by_frase)
        assert len(clusters) == 3


class TestSingletons:

    def test_unique_mention_yields_singleton_cluster(self) -> None:
        actors_by_frase = _make(
            (0, [{"actor": "el FMI"}]),
        )
        clusters = cluster_mentions_within_discurso(actors_by_frase)
        assert len(clusters) == 1
        assert clusters[0] == {(0, 0)}


class TestEdgeCases:

    def test_empty_input(self) -> None:
        assert cluster_mentions_within_discurso([]) == []

    def test_empty_actors_lists(self) -> None:
        actors_by_frase = _make((0, []), (1, []))
        assert cluster_mentions_within_discurso(actors_by_frase) == []

    def test_skips_non_dict_actors(self) -> None:
        actors_by_frase = _make(
            (0, [{"actor": "Milei"}, "not_a_dict"]),  # type: ignore[list-item]
            (1, [{"actor": "Milei"}]),
        )
        clusters = cluster_mentions_within_discurso(actors_by_frase)
        # Solo cuenta el dict válido: 2 menciones, mismo cluster.
        assert len(clusters) == 1
        # Las claves: (0, 0) — la mención "not_a_dict" fue omitida, así
        # que su índice 1 no aparece.
        assert clusters[0] == {(0, 0), (1, 0)}

    def test_empty_actor_name_is_skipped(self) -> None:
        actors_by_frase = _make(
            (0, [{"actor": ""}, {"actor": "Milei"}]),
        )
        clusters = cluster_mentions_within_discurso(actors_by_frase)
        # Solo la mención válida cuenta.
        assert sum(len(c) for c in clusters) == 1


class TestPickRepresentative:

    def test_picks_longest_mention(self) -> None:
        actors_map = {
            0: [{"actor": "Milei"}],
            1: [{"actor": "Javier Milei"}],
            2: [{"actor": "Javier Gerardo Milei"}],
        }
        cluster = {(0, 0), (1, 0), (2, 0)}
        rep = pick_representative(cluster, actors_map)
        assert rep == "Javier Gerardo Milei"

    def test_tiebreaker_lowest_key(self) -> None:
        actors_map = {
            0: [{"actor": "Milei"}],
            5: [{"actor": "Milei"}],
        }
        cluster = {(0, 0), (5, 0)}
        rep = pick_representative(cluster, actors_map)
        assert rep == "Milei"

    def test_returns_empty_for_empty_cluster(self) -> None:
        assert pick_representative(set(), {}) == ""
