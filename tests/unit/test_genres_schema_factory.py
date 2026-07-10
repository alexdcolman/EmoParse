# ══════════════════════════════════════════════════════════════════════════════
#  tests.unit.test_genres_schema_factory
#
#  El schema de Enunciacion debe parametrizarse por género, de
#  modo que el sampler (vía GBNF) restrinja la salida al subset de
#  roles válidos.
# ══════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

import pytest
from pydantic import ValidationError

from emoparse.genres.base import Genre
from emoparse.genres.schema_factory import (
    enunciacion_schema,
    enunciacion_schema_for,
    enunciatario_schema_for,
)


@pytest.fixture
def politico() -> Genre:
    return Genre(
        genre_id="politico_test",
        display_name="Político (test)",
        unit="frase",
        enunciation_roles=(
            "prodestinatario", "paradestinatario", "contradestinatario",
        ),
    )


@pytest.fixture
def tuit() -> Genre:
    return Genre(
        genre_id="tuit_test",
        display_name="Tuit (test)",
        unit="documento",
        enunciation_roles=("seguidor", "oponente", "audiencia_general"),
    )


class TestEnunciatarioDynamic:
    def test_accepts_role_in_genre_universe(self, politico: Genre) -> None:
        Model = enunciatario_schema_for(politico.genre_id, politico.enunciation_roles)
        instance = Model(
            actor="el pueblo",
            tipo="prodestinatario",
            justificacion="se dirige a los simpatizantes",
        )
        assert instance.tipo == "prodestinatario"

    def test_rejects_role_outside_genre_universe(self, politico: Genre) -> None:
        Model = enunciatario_schema_for(politico.genre_id, politico.enunciation_roles)
        # 'seguidor' es un rol válido GLOBALMENTE (existe en TipoEnunciatario),
        # pero NO está en el universo del género político — debe rechazarse.
        with pytest.raises(ValidationError):
            Model(actor="X", tipo="seguidor", justificacion="...")

    def test_different_genres_get_different_models(
        self, politico: Genre, tuit: Genre,
    ) -> None:
        ModelPol = enunciatario_schema_for(politico.genre_id, politico.enunciation_roles)
        ModelTuit = enunciatario_schema_for(tuit.genre_id, tuit.enunciation_roles)
        assert ModelPol is not ModelTuit
        # Nombres deben distinguirse — el cache LLM los usa como clave.
        assert "politico_test" in ModelPol.__name__
        assert "tuit_test" in ModelTuit.__name__

    def test_same_genre_returns_same_class(self, politico: Genre) -> None:
        # Crítico para que el cache LLM no se invalide en cada llamada.
        a = enunciatario_schema_for(politico.genre_id, politico.enunciation_roles)
        b = enunciatario_schema_for(politico.genre_id, politico.enunciation_roles)
        assert a is b

    def test_empty_roles_rejected(self) -> None:
        with pytest.raises(ValueError, match="al menos un rol"):
            enunciatario_schema_for("x", ())


class TestEnunciacionDynamic:
    def test_full_response_validates(self, politico: Genre) -> None:
        Model = enunciacion_schema(politico)
        payload = {
            "enunciador": {
                "actor": "Presidente Pérez",
                "justificacion": "se identifica al inicio",
            },
            "enunciatarios": [
                {
                    "actor": "el pueblo",
                    "tipo": "prodestinatario",
                    "justificacion": "se dirige a los simpatizantes",
                },
                {
                    "actor": "la oposición",
                    "tipo": "contradestinatario",
                    "justificacion": "los menciona como adversarios",
                },
            ],
            "auditorio": [],
            "colectivos": [],
        }
        instance = Model.model_validate(payload)
        assert len(instance.enunciatarios) == 2
        assert instance.enunciador.actor == "Presidente Pérez"

    def test_response_with_wrong_genre_role_rejected(
        self, politico: Genre,
    ) -> None:
        Model = enunciacion_schema(politico)
        payload = {
            "enunciador": {
                "actor": "X", "justificacion": "Y",
            },
            "enunciatarios": [
                {
                    "actor": "X",
                    # 'seguidor' es de tuit, no de político.
                    "tipo": "seguidor",
                    "justificacion": "Y",
                },
            ],
        }
        with pytest.raises(ValidationError):
            Model.model_validate(payload)

    def test_tuit_accepts_seguidor(self, tuit: Genre) -> None:
        Model = enunciacion_schema(tuit)
        payload = {
            "enunciador": {
                "actor": "@usuario", "justificacion": "screen name",
            },
            "enunciatarios": [
                {
                    "actor": "los followers",
                    "tipo": "seguidor",
                    "justificacion": "usa 'familia'",
                },
            ],
            "auditorio": [],
            "colectivos": [],
        }
        instance = Model.model_validate(payload)
        assert instance.enunciatarios[0].tipo == "seguidor"

    def test_tuit_rejects_prodestinatario(self, tuit: Genre) -> None:
        Model = enunciacion_schema(tuit)
        payload = {
            "enunciador": {"actor": "X", "justificacion": "Y"},
            "enunciatarios": [
                {
                    "actor": "X",
                    "tipo": "prodestinatario",
                    "justificacion": "Y",
                },
            ],
        }
        with pytest.raises(ValidationError):
            Model.model_validate(payload)


class TestSchemaInheritsConfig:
    """Las subclases dinámicas heredan el ConfigDict de la base
    (extra='forbid', str_strip_whitespace, etc)."""

    def test_extra_field_rejected_in_enunciatario(self, politico: Genre) -> None:
        Model = enunciatario_schema_for(politico.genre_id, politico.enunciation_roles)
        with pytest.raises(ValidationError):
            Model(
                actor="X",
                tipo="prodestinatario",
                justificacion="Y",
                extra_field="oops",  # type: ignore[call-arg]
            )

    def test_str_strip_whitespace_applied(self, politico: Genre) -> None:
        Model = enunciatario_schema_for(politico.genre_id, politico.enunciation_roles)
        instance = Model(
            actor="  el pueblo  ",
            tipo="prodestinatario",
            justificacion="  J  ",
        )
        assert instance.actor == "el pueblo"
        assert instance.justificacion == "J"
