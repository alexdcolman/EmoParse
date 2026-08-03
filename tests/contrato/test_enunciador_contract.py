"""Contratos del referente emisor y de la autoría periodística."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from emoparse.core.prompts import enunciation as prompts
from emoparse.core.schemas import (
    ColectivoIdentificacionSchema,
    EnunciadorSchema,
)
from emoparse.genres.articulo_periodistico import get_genre
from emoparse.genres.enunciator import resolve_from_input_field


def test_article_declares_authorship_as_deterministic_emitter() -> None:
    genre = get_genre()

    assert genre.enunciador_from_input_field == "autoria"
    assert "autoria" in genre.input_metadata_model.model_fields


def test_article_authorship_fixes_concrete_person_without_llm() -> None:
    actor, justification = resolve_from_input_field(
        {"autoria": ["Luis Bruschtein"]},
        "autoria",
    )

    assert actor == "Luis Bruschtein"
    assert justification == "Autoría declarada en la metadata del campo `autoria`."


def test_article_authorship_accepts_json_and_multiple_signatures() -> None:
    actor, _ = resolve_from_input_field(
        {"autoria": '["Ana Pérez", "Luis Gómez"]'},
        "autoria",
    )

    assert actor == "Ana Pérez y Luis Gómez"


@pytest.mark.parametrize(
    "actor",
    [
        "el enunciador",
        "enunciador institucional",
        "enunciatario",
        "prodestinatario",
        "autor",
    ],
)
def test_schema_rejects_metalinguistic_placeholders_in_categories(
    actor: str,
) -> None:
    with pytest.raises(ValidationError):
        EnunciadorSchema(
            actor=actor,
            justificacion="La firma aparece en la cabecera.",
        )


def test_schema_accepts_analytic_term_in_justification() -> None:
    parsed = EnunciadorSchema(
        actor="Javier Milei",
        justificacion=("El enunciador se identifica como Presidente de la Nación al inicio."),
    )

    assert parsed.actor == "Javier Milei"
    assert "enunciador" in parsed.justificacion.lower()


def test_collective_name_rejects_metalinguistic_category() -> None:
    with pytest.raises(ValidationError):
        ColectivoIdentificacionSchema(
            clase="institucional",
            nombre="el enunciador",
            justificacion="El enunciador usa la primera persona plural.",
        )


def test_schema_accepts_concrete_referent_and_evidence() -> None:
    parsed = EnunciadorSchema(
        actor="Luis Bruschtein",
        justificacion="La firma de la cabecera identifica a Luis Bruschtein.",
    )

    assert parsed.actor == "Luis Bruschtein"


def test_identification_prompt_forbids_metalinguistic_categories_only() -> None:
    text = prompts.render_enunciator_id_system()

    assert "No escribas la palabra" in text
    assert "`actor`" in text
