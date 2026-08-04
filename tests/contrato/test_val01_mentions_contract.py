"""Contratos de menciones derivados del smoke de posts VAL-01."""

from __future__ import annotations

from emoparse.storage.menciones import derivar_menciones


def test_mentions_ignore_unknown_marks_and_prefer_inference_matching_the_mark() -> None:
    mentions = derivar_menciones(
        actores_by_unit={},
        emociones_by_unit={
            0: [
                {
                    "experienciador": "@cali2027.bsky.social",
                    "experienciador_marca": "El pueblo",
                    "fuente_marca": "no identificado",
                    "fuente_inferencia": "no identificado",
                },
                {
                    "experienciador": "el pueblo",
                    "experienciador_marca": "el pueblo",
                    "fuente_marca": "no identificado",
                    "fuente_inferencia": "no identificado",
                },
            ]
        },
    )

    assert len(mentions) == 1
    assert mentions[0]["marca"] == "El pueblo"
    assert mentions[0]["llm_inferencia"] == "el pueblo"
    assert mentions[0]["canonical_proposed"] == "pueblo"
    assert mentions[0]["funciones"] == {"experienciador"}
