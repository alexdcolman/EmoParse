"""Contratos del referente emisor y de la autoría periodística."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from emoparse.core.prompts import enunciation as prompts
from emoparse.core.schemas import EnunciadorSchema
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
    assert "enunciador" not in justification.lower()


def test_article_authorship_accepts_json_and_multiple_signatures() -> None:
    actor, _ = resolve_from_input_field(
        {"autoria": '["Ana Pérez", "Luis Gómez"]'},
        "autoria",
    )

    assert actor == "Ana Pérez y Luis Gómez"


@pytest.mark.parametrize(
    ("actor", "justification"),
    [
        ("el enunciador", "La firma aparece en la cabecera."),
        ("enunciador institucional", "La institución firma la nota."),
        ("Luis Bruschtein", "El enunciador está firmado en la cabecera."),
        ("autor", "La firma aparece en la cabecera."),
    ],
)
def test_schema_rejects_metalinguistic_placeholders(
    actor: str,
    justification: str,
) -> None:
    with pytest.raises(ValidationError):
        EnunciadorSchema(actor=actor, justificacion=justification)


def test_schema_accepts_concrete_referent_and_evidence() -> None:
    parsed = EnunciadorSchema(
        actor="Luis Bruschtein",
        justificacion="La firma de la cabecera identifica a Luis Bruschtein.",
    )

    assert parsed.actor == "Luis Bruschtein"


def test_identification_prompt_forbids_metalinguistic_values() -> None:
    text = prompts.render_enunciator_id_system()

    assert 'No escribas la palabra "enunciador"' in text
    assert "`actor`" in text
    assert "`justificacion`" in text
