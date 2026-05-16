# ══════════════════════════════════════════════════════════════════════════════
#  tests.unit.test_normalize_emotions_stage
#
#  Tests de NormalizeEmotionsStage.
# ══════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

from unittest.mock import MagicMock, call

import pytest

from emoparse.pipeline.stages import NormalizeEmotionsStage


# ── Ontología mínima de fixture ───────────────────────────────────────────────

ONTOLOGY = {
    "emociones": {
        "ira": {
            "aliases": ["enojo", "rabia", "Bronca"],
        },
        "miedo": {
            "aliases": ["temor", "terror"],
        },
    }
}


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_repo(pending: list[tuple[str, int, int]], rows: dict) -> MagicMock:
    """Crea un mock de EmocionesRepository con pending y rows configurados."""
    repo = MagicMock()
    repo.list_pending_normalization.return_value = pending
    repo.get_emocion.side_effect = lambda c, f, e: rows.get((c, f, e))
    return repo


# ── Tests ─────────────────────────────────────────────────────────────────────

class TestNormalizeEmotionsStage:

    def test_alias_lowercase_maps_to_canonical(self) -> None:
        repo = _make_repo(
            [("d1", 0, 0)],
            {("d1", 0, 0): {"tipo_emocion": "enojo"}},
        )
        stage = NormalizeEmotionsStage(repo, ONTOLOGY, agent_version="v1")
        n = stage.run_pending()

        assert n == 1
        repo.set_normalized_emotion.assert_called_once_with(
            "d1", 0, 0, tipo_emocion_canonico="ira", version="v1"
        )

    def test_alias_with_leading_spaces_stripped(self) -> None:
        repo = _make_repo(
            [("d1", 0, 0)],
            {("d1", 0, 0): {"tipo_emocion": "  rabia  "}},
        )
        stage = NormalizeEmotionsStage(repo, ONTOLOGY)
        stage.run_pending()

        repo.set_normalized_emotion.assert_called_once_with(
            "d1", 0, 0, tipo_emocion_canonico="ira", version=None
        )

    def test_unknown_emotion_leaves_canonico_none(self) -> None:
        repo = _make_repo(
            [("d1", 0, 0)],
            {("d1", 0, 0): {"tipo_emocion": "nostalgia_inexistente"}},
        )
        stage = NormalizeEmotionsStage(repo, ONTOLOGY)
        stage.run_pending()

        repo.set_normalized_emotion.assert_called_once_with(
            "d1", 0, 0, tipo_emocion_canonico=None, version=None
        )

    def test_unknown_emotion_does_not_raise(self) -> None:
        """Emoción no cubierta no lanza excepción."""
        repo = _make_repo(
            [("d1", 0, 0)],
            {("d1", 0, 0): {"tipo_emocion": "no_existe"}},
        )
        stage = NormalizeEmotionsStage(repo, ONTOLOGY)
        assert stage.run_pending() == 1

    def test_empty_pending_returns_zero(self) -> None:
        repo = _make_repo([], {})
        stage = NormalizeEmotionsStage(repo, ONTOLOGY)
        assert stage.run_pending() == 0
        repo.set_normalized_emotion.assert_not_called()

    def test_multiple_emotions_processed(self) -> None:
        pending = [("d1", 0, 0), ("d1", 0, 1), ("d1", 1, 0)]
        rows = {
            ("d1", 0, 0): {"tipo_emocion": "ira"},
            ("d1", 0, 1): {"tipo_emocion": "temor"},
            ("d1", 1, 0): {"tipo_emocion": "desconocida"},
        }
        repo = _make_repo(pending, rows)
        stage = NormalizeEmotionsStage(repo, ONTOLOGY, agent_version="v2")
        n = stage.run_pending()

        assert n == 3
        assert repo.set_normalized_emotion.call_count == 3
        calls = repo.set_normalized_emotion.call_args_list
        assert call("d1", 0, 0, tipo_emocion_canonico="ira",   version="v2") in calls
        assert call("d1", 0, 1, tipo_emocion_canonico="miedo", version="v2") in calls
        assert call("d1", 1, 0, tipo_emocion_canonico=None,    version="v2") in calls

    def test_rerun_only_processes_pending(self) -> None:
        """Idempotencia: si no hay pendientes, no hace nada."""
        repo = _make_repo([], {})
        stage = NormalizeEmotionsStage(repo, ONTOLOGY)
        stage.run_pending()
        stage.run_pending()  # segunda ejecución
        repo.set_normalized_emotion.assert_not_called()

    def test_missing_emocion_in_repo_skipped(self) -> None:
        """Si get_emocion devuelve None, la fila se saltea sin error."""
        repo = _make_repo([("d1", 0, 0)], {})  # get_emocion → None
        stage = NormalizeEmotionsStage(repo, ONTOLOGY)
        assert stage.run_pending() == 1  # se procesó el pending (sin set)
        # set_normalized_emotion no se llamó porque row es None
        repo.set_normalized_emotion.assert_not_called()

    def test_metrics_record_ok_per_emotion(self) -> None:
        pending = [("d1", 0, 0), ("d1", 0, 1)]
        rows = {
            ("d1", 0, 0): {"tipo_emocion": "ira"},
            ("d1", 0, 1): {"tipo_emocion": "miedo"},
        }
        repo = _make_repo(pending, rows)
        stage = NormalizeEmotionsStage(repo, ONTOLOGY)
        stage.run_pending()
        assert stage.metrics.snapshot().n_items_ok == 2

    def test_canonical_maps_via_canonical_name(self) -> None:
        """El nombre canónico mismo es resoluble."""
        repo = _make_repo(
            [("d1", 0, 0)],
            {("d1", 0, 0): {"tipo_emocion": "ira"}},
        )
        stage = NormalizeEmotionsStage(repo, ONTOLOGY)
        stage.run_pending()
        repo.set_normalized_emotion.assert_called_once_with(
            "d1", 0, 0, tipo_emocion_canonico="ira", version=None
        )
