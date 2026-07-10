# ══════════════════════════════════════════════════════════════════════════════
#  tests.unit.test_genres_registry
#
#  Garantías del registry de géneros.
# ══════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

import pytest

from emoparse.genres import (
    DEFAULT_GENRE_ID,
    Genre,
    GenreRegistryError,
    all_genres,
    default_genre,
    get_genre,
    register,
    reset_for_tests,
)


@pytest.fixture(autouse=True)
def clean_registry() -> None:
    """Cada test arranca con el registry limpio."""
    reset_for_tests()
    yield
    reset_for_tests()


@pytest.fixture
def sample_genre() -> Genre:
    """Genre sintético para tests que no necesitan al builtin."""
    return Genre(
        genre_id="test_genre",
        display_name="Test Genre",
        unit="frase",
        enunciation_roles=("rol_a", "rol_b"),
    )


class TestRegister:
    def test_register_then_get(self, sample_genre: Genre) -> None:
        register(sample_genre)
        assert get_genre("test_genre") is sample_genre

    def test_register_overrides_same_id(self, sample_genre: Genre) -> None:
        register(sample_genre)
        other = Genre(
            genre_id="test_genre",
            display_name="Other",
            unit="documento",
            enunciation_roles=("x",),
        )
        register(other)
        assert get_genre("test_genre") is other


class TestGetGenre:
    def test_unknown_raises(self) -> None:
        with pytest.raises(GenreRegistryError) as exc:
            get_genre("inexistente_xyz")
        # Mensaje útil: lista los disponibles.
        assert "inexistente_xyz" in str(exc.value)
        assert "Disponibles" in str(exc.value)


class TestAllGenres:
    def test_includes_programmatic(self, sample_genre: Genre) -> None:
        register(sample_genre)
        genres = all_genres()
        assert "test_genre" in genres

    def test_programmatic_wins_over_discovered(self, sample_genre: Genre) -> None:
        # Aún si el descubrimiento devolviera un test_genre, el
        # programático tiene precedencia. Se prueba registrando y
        # confirmando identidad de instancia.
        register(sample_genre)
        genres = all_genres()
        assert genres["test_genre"] is sample_genre


class TestDefaultGenre:
    def test_default_id_is_discurso_presidencial(self) -> None:
        assert DEFAULT_GENRE_ID == "discurso_presidencial"

    def test_default_genre_works_when_registered(self) -> None:
        from emoparse.genres.discurso_presidencial import get_genre as builtin_factory
        register(builtin_factory())
        g = default_genre()
        assert g.genre_id == "discurso_presidencial"

    def test_default_genre_raises_actionable_error_when_missing(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # Forzar que el descubrimiento no encuentre el builtin (simula
        # instalación rota o ausencia del entry-point).
        from emoparse.genres import registry as reg_mod
        monkeypatch.setattr(reg_mod, "_discover", lambda: {})
        reset_for_tests()

        with pytest.raises(GenreRegistryError) as exc:
            default_genre()
        assert "discurso_presidencial" in str(exc.value)


class TestBuiltinDiscursoPresidencial:
    def test_factory_returns_expected_shape(self) -> None:
        from emoparse.genres.discurso_presidencial import get_genre as builtin_factory

        g = builtin_factory()
        assert g.genre_id == "discurso_presidencial"
        assert g.unit == "frase"
        assert set(g.enunciation_roles) == {
            "prodestinatario", "paradestinatario", "contradestinatario",
        }
        assert g.summarizer is True
        # No overrides → respeta config.yaml.
        assert g.models == {}
        assert g.batch_size == {
            "actors": 1,
            "emotions": 1,
            "emotions_pass2": 1,
            "deixis": 5,
            "semas": 2,
            "characterizer": 1,
            "actants": 1,
            "judge": 1,
        }


class TestExampleTuit:
    def test_factory_returns_expected_shape(self) -> None:
        from emoparse.genres_examples.tuit import get_genre as tuit_factory

        g = tuit_factory()
        assert g.genre_id == "tuit"
        assert g.unit == "documento"
        assert "seguidor" in g.enunciation_roles
        assert g.summarizer is False
        # Tuits tienen batch_size más grande en las stages batch.
        assert g.batch_size["actors"] == 10


class TestGenreModelValidation:
    """Validaciones que Pydantic impone sobre Genre."""

    def test_invalid_unit_rejected(self) -> None:
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            Genre(
                genre_id="x",
                display_name="X",
                unit="capitulo",  # type: ignore[arg-type]
                enunciation_roles=("a",),
            )

    def test_extra_fields_forbidden(self) -> None:
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            Genre(
                genre_id="x",
                display_name="X",
                unit="frase",
                enunciation_roles=("a",),
                unknown_field="oops",  # type: ignore[call-arg]
            )

    def test_genre_is_immutable(self, sample_genre: Genre) -> None:
        # frozen=True: cualquier intento de asignación falla.
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            sample_genre.unit = "documento"  # type: ignore[misc]
