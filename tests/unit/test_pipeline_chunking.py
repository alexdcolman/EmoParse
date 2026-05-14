# ══════════════════════════════════════════════════════════════════════════════
#  tests.unit.test_pipeline_chunking
#
#  Tests del splitter por oraciones del pipeline.
# ══════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

from emoparse.pipeline.chunking import split_into_sentences


# ══════════════════════════════════════════════════════════════════════════════
#  Casos básicos
# ══════════════════════════════════════════════════════════════════════════════


class TestBasic:

    def test_simple_two_sentences(self) -> None:
        text = "Esta es la primera. Esta es la segunda."
        result = split_into_sentences(text)
        assert len(result) == 2
        assert "primera" in result[0]
        assert "segunda" in result[1]

    def test_question_and_exclamation(self) -> None:
        text = "¿Cómo están? ¡Bienvenidos! Ahora empezamos."
        result = split_into_sentences(text, min_chars=5)
        assert len(result) == 3

    def test_empty_returns_empty(self) -> None:
        assert split_into_sentences("") == []
        assert split_into_sentences("   \n\n  ") == []

    def test_single_sentence(self) -> None:
        text = "Una sola oración sin terminador real"
        result = split_into_sentences(text)
        assert len(result) == 1
        assert result[0] == text

    def test_preserves_order(self) -> None:
        text = "Primera. Segunda. Tercera."
        result = split_into_sentences(text, min_chars=5)
        assert "Primera" in result[0]
        assert "Segunda" in result[1]
        assert "Tercera" in result[2]


# ══════════════════════════════════════════════════════════════════════════════
#  Abreviaciones
# ══════════════════════════════════════════════════════════════════════════════


class TestAbbreviations:

    def test_sr_does_not_split(self) -> None:
        """`Sr.` no debe terminar una oración."""
        text = "El Sr. Pérez llegó tarde. Ayer también."
        result = split_into_sentences(text, min_chars=5)
        # Esperamos 2 oraciones, no 3.
        assert len(result) == 2
        # La primera contiene "Sr. Pérez".
        assert "Sr. Pérez" in result[0]

    def test_dr_does_not_split(self) -> None:
        text = "El Dr. González habló. Después contestó preguntas."
        result = split_into_sentences(text, min_chars=5)
        assert len(result) == 2
        assert "Dr. González" in result[0]

    def test_etc_does_not_split(self) -> None:
        """`etc.` es abreviación: NO termina oración. Como no hay otro
        signo de fin, todo queda en una unidad."""
        text = "Trajeron café, té, etc. Después llegaron más invitados."
        result = split_into_sentences(text, min_chars=5)
        # `etc.` no parte; el texto queda como una unidad.
        assert len(result) == 1
        assert "café" in result[0]
        assert "invitados" in result[0]

    def test_abbreviation_case_insensitive(self) -> None:
        """`SR.` y `sr.` y `Sr.` se reconocen igual."""
        text = "El SR. Pérez llegó. Bien."
        result = split_into_sentences(text, min_chars=3)
        assert len(result) == 2


# ══════════════════════════════════════════════════════════════════════════════
#  División de oraciones largas
# ══════════════════════════════════════════════════════════════════════════════


class TestLongSentences:

    def test_long_sentence_splits_by_semicolon(self) -> None:
        text = (
            "La situación es compleja por varios motivos: "
            "primero, la economía no acompaña; "
            "segundo, hay tensiones políticas internas; "
            "tercero, los acuerdos previos están en revisión."
        )
        result = split_into_sentences(text, max_chars=80, min_chars=20)
        # Debe partirse en varias unidades.
        assert len(result) >= 2
        assert all(len(s) <= 160 for s in result)

    def test_long_sentence_falls_back_to_comma(self) -> None:
        """Sin `;`, fallback a `,`."""
        text = "Vinieron Juan, María, Pedro, Lucía, y todos los demás amigos del barrio."
        result = split_into_sentences(text, max_chars=40, min_chars=10)
        assert len(result) >= 2

    def test_long_sentence_without_separators_kept_intact(self) -> None:
        """Si una oración es larga pero no tiene `;` ni `,`, se deja."""
        text = "Esta es una oración bastante larga sin separadores internos para dividir."
        result = split_into_sentences(text, max_chars=20, min_chars=10)
        assert len(result) == 1


# ══════════════════════════════════════════════════════════════════════════════
#  Fusión de oraciones cortas
# ══════════════════════════════════════════════════════════════════════════════


class TestMergeShort:

    def test_merge_short_with_next(self) -> None:
        """Una oración muy corta se combina con la siguiente."""
        text = "Sí. Esta es la oración principal del párrafo."
        result = split_into_sentences(text, min_chars=20)
        # "Sí." se fusiona.
        assert len(result) == 1
        assert "Sí." in result[0]
        assert "principal" in result[0]

    def test_last_short_merges_with_previous(self) -> None:
        """Si la última oración es corta y no hay siguiente, se fusiona
        con la anterior."""
        text = "Esta es una oración bastante larga. No."
        result = split_into_sentences(text, min_chars=20)
        assert len(result) == 1
        assert "No." in result[0]

    def test_multiple_short_combine(self) -> None:
        text = "Sí. No. Quizás. Esta es la idea principal."
        result = split_into_sentences(text, min_chars=20)
        # Las 3 cortas se combinan con la principal.
        assert len(result) == 1


# ══════════════════════════════════════════════════════════════════════════════
#  Caso real del integration test.
# ══════════════════════════════════════════════════════════════════════════════


class TestRealCase:

    def test_presidential_paragraph_splits(self) -> None:
        text = (
            "Compatriotas, hoy asumo la presidencia de la Nación. "
            "Sé que muchos de ustedes están preocupados por el futuro. "
            "Yo también lo estaba. "
            "Pero hoy estoy esperanzado."
        )
        result = split_into_sentences(text, max_chars=200, min_chars=15)
        # Esperamos varias unidades — no una sola.
        assert len(result) >= 3, (
            f"El párrafo se mantuvo en {len(result)} unidad(es). "
            "El splitter no está haciendo su trabajo."
        )
        # Cada unidad menciona una idea distinta.
        joined = " | ".join(result)
        assert "asumo" in joined
        assert "preocupados" in joined
        assert "esperanzado" in joined
