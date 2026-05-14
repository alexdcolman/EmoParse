# ══════════════════════════════════════════════════════════════════════════════
#  tests.unit.test_prompts_jinja_snapshot
#
#  Garantiza que los wrappers Jinja2 producen output BYTE-IDÉNTICO
#  al de los `string.Template` originales del proyecto (versión 0.1.0).
#  La migración es por contrato un no-op semántico; cualquier divergencia
#  de output rompe este test y bloquea el merge.
# ══════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

import pytest

from emoparse.core.prompts import (
    actors as actors_new,
    characterizer as characterizer_new,
    emotions as emotions_new,
    emotions_pass2 as emotions_pass2_new,
    enunciation as enunciation_new,
    judge as judge_new,
    metadata as metadata_new,
    summarizer as summarizer_new,
)

from tests.unit._legacy_prompts import (
    actors_legacy,
    characterizer_legacy,
    emotions_legacy,
    emotions_pass2_legacy,
    enunciation_legacy,
    judge_legacy,
    metadata_legacy,
    summarizer_legacy,
)


# ══════════════════════════════════════════════════════════════════════════════
#  Valores de muestra (con edge-cases deliberados)
# ══════════════════════════════════════════════════════════════════════════════

# Llaves literales en el contenido para verificar que Jinja2 no las
# interpreta como sintaxis (solo `{{` y `{%` son sintaxis).
DICCIONARIO = """{
  "asuncion": "Toma de posesión.",
  "anuncio_medida": "Anuncio de política concreta."
}"""

# Unicode + comillas + newlines internos.
RESUMEN = 'El presidente "Pérez" anunció medidas:\nreducción del IVA y aumento de jubilaciones.'

FRAGMENTOS = """- Primera frase del discurso.
- Segunda frase con caracteres ñáéíóú.
- Tercera frase con "comillas dobles" y 'simples'."""

ONTOLOGIA = """- Miedo: emoción ante amenaza percibida.
- Alegría: emoción ante éxito o ganancia."""

HEURISTICAS = """1. Si el sujeto tiembla o tiene taquicardia → miedo.
2. Si sonríe espontáneamente → alegría."""

UNIDADES_BLOCK = """UNIDAD [0] (codigo=D001):
"Tengo miedo del futuro," dijo el presidente.

UNIDAD [1] (codigo=D001):
Pero hoy celebramos {un nuevo comienzo}."""


# ══════════════════════════════════════════════════════════════════════════════
#  Tests por módulo. Uno por render_system + uno por render_user.
# ══════════════════════════════════════════════════════════════════════════════

class TestMetadata:
    def test_system_byte_identical(self) -> None:
        legacy = metadata_legacy.render_system(diccionario=DICCIONARIO)
        new = metadata_new.render_system(diccionario=DICCIONARIO)
        assert new == legacy

    def test_user_byte_identical(self) -> None:
        legacy = metadata_legacy.render_user(
            codigo="D001", resumen=RESUMEN, fragmentos=FRAGMENTOS,
        )
        new = metadata_new.render_user(
            codigo="D001", resumen=RESUMEN, fragmentos=FRAGMENTOS,
        )
        assert new == legacy


class TestEnunciation:
    def test_system_byte_identical(self) -> None:
        legacy = enunciation_legacy.render_system(diccionario=DICCIONARIO)
        new = enunciation_new.render_system(diccionario=DICCIONARIO)
        assert new == legacy

    def test_user_byte_identical(self) -> None:
        legacy = enunciation_legacy.render_user(
            codigo="D001", resumen=RESUMEN, fragmentos=FRAGMENTOS,
        )
        new = enunciation_new.render_user(
            codigo="D001", resumen=RESUMEN, fragmentos=FRAGMENTOS,
        )
        assert new == legacy


class TestActors:
    def test_system_byte_identical(self) -> None:
        legacy = actors_legacy.render_system(
            titulo="Asunción", tipo_discurso="asuncion", enunciador="Pérez",
        )
        new = actors_new.render_system(
            titulo="Asunción", tipo_discurso="asuncion", enunciador="Pérez",
        )
        assert new == legacy

    def test_user_byte_identical(self) -> None:
        legacy = actors_legacy.render_user(unidades_block=UNIDADES_BLOCK)
        new = actors_new.render_user(unidades_block=UNIDADES_BLOCK)
        assert new == legacy

    def test_system_empty_context_byte_identical(self) -> None:
        # Caso edge: contexto en blanco (el agente lo permite como default).
        legacy = actors_legacy.render_system(
            titulo="", tipo_discurso="", enunciador="",
        )
        new = actors_new.render_system(
            titulo="", tipo_discurso="", enunciador="",
        )
        assert new == legacy


class TestEmotions:
    def test_system_byte_identical(self) -> None:
        legacy = emotions_legacy.render_system(
            ontologia=ONTOLOGIA, heuristicas=HEURISTICAS,
            titulo="Asunción", tipo_discurso="asuncion", enunciador="Pérez",
        )
        new = emotions_new.render_system(
            ontologia=ONTOLOGIA, heuristicas=HEURISTICAS,
            titulo="Asunción", tipo_discurso="asuncion", enunciador="Pérez",
        )
        assert new == legacy

    def test_user_byte_identical(self) -> None:
        legacy = emotions_legacy.render_user(unidades_block=UNIDADES_BLOCK)
        new = emotions_new.render_user(unidades_block=UNIDADES_BLOCK)
        assert new == legacy


class TestEmotionsPass2:
    def test_system_byte_identical(self) -> None:
        legacy = emotions_pass2_legacy.render_system(
            ontologia=ONTOLOGIA, heuristicas=HEURISTICAS,
            titulo="Asunción", tipo_discurso="asuncion", enunciador="Pérez",
        )
        new = emotions_pass2_new.render_system(
            ontologia=ONTOLOGIA, heuristicas=HEURISTICAS,
            titulo="Asunción", tipo_discurso="asuncion", enunciador="Pérez",
        )
        assert new == legacy

    def test_user_byte_identical(self) -> None:
        legacy = emotions_pass2_legacy.render_user(unidades_block=UNIDADES_BLOCK)
        new = emotions_pass2_new.render_user(unidades_block=UNIDADES_BLOCK)
        assert new == legacy


class TestCharacterizer:
    def test_system_byte_identical(self) -> None:
        legacy = characterizer_legacy.render_system(
            titulo="Asunción", tipo_discurso="asuncion",
        )
        new = characterizer_new.render_system(
            titulo="Asunción", tipo_discurso="asuncion",
        )
        assert new == legacy

    def test_user_byte_identical(self) -> None:
        legacy = characterizer_legacy.render_user(unidades_block=UNIDADES_BLOCK)
        new = characterizer_new.render_user(unidades_block=UNIDADES_BLOCK)
        assert new == legacy


class TestJudge:
    def test_system_byte_identical(self) -> None:
        legacy = judge_legacy.render_system(
            titulo="Asunción", tipo_discurso="asuncion",
        )
        new = judge_new.render_system(
            titulo="Asunción", tipo_discurso="asuncion",
        )
        assert new == legacy

    def test_system_falls_back_to_no_identificado(self) -> None:
        # Caso explícito: el wrapper convierte "" → "no identificado".
        legacy = judge_legacy.render_system(titulo="", tipo_discurso="")
        new = judge_new.render_system(titulo="", tipo_discurso="")
        assert new == legacy
        assert "no identificado" in new

    def test_user_byte_identical(self) -> None:
        legacy = judge_legacy.render_user(unidades_block=UNIDADES_BLOCK)
        new = judge_new.render_user(unidades_block=UNIDADES_BLOCK)
        assert new == legacy


class TestSummarizer:
    """El summarizer mantiene los SYSTEMs como constantes Python — no
    pasan por Jinja2. Verificamos identidad como constantes."""

    def test_system_fragmento_constant(self) -> None:
        assert summarizer_new.SYSTEM_FRAGMENTO == summarizer_legacy.SYSTEM_FRAGMENTO

    def test_system_global_constant(self) -> None:
        assert summarizer_new.SYSTEM_GLOBAL == summarizer_legacy.SYSTEM_GLOBAL

    def test_user_fragmento_byte_identical(self) -> None:
        legacy = summarizer_legacy.render_user_fragmento(
            fragmento="Un fragmento con ñ, é, y \"comillas\".",
        )
        new = summarizer_new.render_user_fragmento(
            fragmento="Un fragmento con ñ, é, y \"comillas\".",
        )
        assert new == legacy

    def test_user_global_byte_identical(self) -> None:
        parciales = "[1] Primer resumen.\n\n[2] Segundo resumen."
        legacy = summarizer_legacy.render_user_global(
            titulo="Asunción presidencial",
            fecha="2024-12-10",
            resumenes_parciales=parciales,
        )
        new = summarizer_new.render_user_global(
            titulo="Asunción presidencial",
            fecha="2024-12-10",
            resumenes_parciales=parciales,
        )
        assert new == legacy


# ══════════════════════════════════════════════════════════════════════════════
#  Garantías estructurales del loader (no del contenido)
# ══════════════════════════════════════════════════════════════════════════════

class TestLoaderBehavior:
    """StrictUndefined: un placeholder ausente explota."""

    def test_missing_variable_raises(self) -> None:
        from jinja2 import UndefinedError

        from emoparse.core.prompts._loader import render

        with pytest.raises(UndefinedError):
            # `metadata_user` espera codigo, resumen, fragmentos.
            render("metadata_user", codigo="X")  # faltan 2

    def test_extra_kwargs_ignored(self) -> None:
        from emoparse.core.prompts._loader import render

        out = render(
            "metadata_user", codigo="X", resumen="Y", fragmentos="Z",
            extra="ignorado",
        )
        assert "X" in out and "Y" in out and "Z" in out
