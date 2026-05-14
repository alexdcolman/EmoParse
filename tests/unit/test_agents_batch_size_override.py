# ══════════════════════════════════════════════════════════════════════════════
#  tests.unit.test_agents_batch_size_override
#
#  Cuando el género declara `batch_size["<stage>"]`, el agente
#  correspondiente debe usar ese valor en lugar del default histórico.
#  Sin género o sin override en el género, debe quedar el default.
# ══════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

import pytest

from emoparse.agents.actors import ActorsAgent
from emoparse.agents.characterizer import CharacterizerAgent
from emoparse.agents.emotions import EmotionsAgent
from emoparse.agents.emotions_pass2 import EmotionsAgentPass2
from emoparse.agents.judge import JudgeAgent
from emoparse.core.backend.base import LLMBackend, LLMResponse
from emoparse.genres.base import Genre


class _NoopBackend(LLMBackend):
    """Backend que no se invoca — solo necesitamos pasarlo al constructor."""
    alias = "noop"

    def generate(self, *args, **kwargs) -> LLMResponse:  # type: ignore[override]
        raise NotImplementedError

    def healthcheck(self) -> bool:
        return True


def _genre(batch_size: dict[str, int] | None = None) -> Genre:
    """Construye un Genre mínimo, opcionalmente con batch_size override."""
    return Genre(
        genre_id="test_g",
        display_name="Test",
        unit="frase",
        enunciation_roles=("a",),
        batch_size=batch_size or {},
    )


@pytest.fixture
def backend() -> LLMBackend:
    return _NoopBackend()


# ══════════════════════════════════════════════════════════════════════════════
#  Defaults preservados sin género
# ══════════════════════════════════════════════════════════════════════════════

class TestDefaultsWithoutGenre:
    def test_actors_default(self, backend: LLMBackend) -> None:
        a = ActorsAgent(backend)
        assert a.BATCH_SIZE == 5

    def test_emotions_default(self, backend: LLMBackend) -> None:
        a = EmotionsAgent(backend, ontologia="o", heuristicas="h")
        assert a.BATCH_SIZE == 3

    def test_emotions_pass2_default(self, backend: LLMBackend) -> None:
        a = EmotionsAgentPass2(backend, ontologia="o", heuristicas="h")
        assert a.BATCH_SIZE == 3

    def test_characterizer_default(self, backend: LLMBackend) -> None:
        a = CharacterizerAgent(backend)
        assert a.BATCH_SIZE == 5

    def test_judge_default(self, backend: LLMBackend) -> None:
        a = JudgeAgent(backend)
        assert a.BATCH_SIZE == 5


# ══════════════════════════════════════════════════════════════════════════════
#  Override aplicado cuando el género lo declara
# ══════════════════════════════════════════════════════════════════════════════

class TestOverrideAppliedFromGenre:
    def test_actors_overridden(self, backend: LLMBackend) -> None:
        a = ActorsAgent(backend, genre=_genre({"actors": 10}))
        assert a.BATCH_SIZE == 10

    def test_emotions_overridden(self, backend: LLMBackend) -> None:
        a = EmotionsAgent(
            backend, ontologia="o", heuristicas="h",
            genre=_genre({"emotions": 8}),
        )
        assert a.BATCH_SIZE == 8

    def test_characterizer_overridden(self, backend: LLMBackend) -> None:
        a = CharacterizerAgent(backend, genre=_genre({"characterizer": 12}))
        assert a.BATCH_SIZE == 12

    def test_judge_overridden(self, backend: LLMBackend) -> None:
        a = JudgeAgent(backend, genre=_genre({"judge": 7}))
        assert a.BATCH_SIZE == 7


# ══════════════════════════════════════════════════════════════════════════════
#  emotions_pass2 con fallback a 'emotions'
# ══════════════════════════════════════════════════════════════════════════════

class TestEmotionsPass2Fallback:
    """Si el género declara batch_size para 'emotions' pero no para
    'emotions_pass2', pass2 hereda el valor de pase 1."""

    def test_explicit_pass2_wins(self, backend: LLMBackend) -> None:
        a = EmotionsAgentPass2(
            backend, ontologia="o", heuristicas="h",
            genre=_genre({"emotions": 6, "emotions_pass2": 11}),
        )
        assert a.BATCH_SIZE == 11

    def test_fallback_to_emotions_key(self, backend: LLMBackend) -> None:
        a = EmotionsAgentPass2(
            backend, ontologia="o", heuristicas="h",
            genre=_genre({"emotions": 9}),  # solo 'emotions'
        )
        assert a.BATCH_SIZE == 9


# ══════════════════════════════════════════════════════════════════════════════
#  Sin override en el género (genero con batch_size vacío)
# ══════════════════════════════════════════════════════════════════════════════

class TestGenreWithoutOverride:
    def test_actors_keeps_default(self, backend: LLMBackend) -> None:
        a = ActorsAgent(backend, genre=_genre())  # batch_size={}
        assert a.BATCH_SIZE == 5

    def test_emotions_keeps_default(self, backend: LLMBackend) -> None:
        a = EmotionsAgent(
            backend, ontologia="o", heuristicas="h", genre=_genre(),
        )
        assert a.BATCH_SIZE == 3
