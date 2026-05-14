# ══════════════════════════════════════════════════════════════════════════════
#  tests.unit.test_grammar
#
#  Verifica que el converter Pydantic→GBNF produce gramáticas:
#  1. Sintácticamente bien formadas (parseables como GBNF).
#  2. Que aceptan instancias válidas de cada schema.
#  3. Que rechazan estructuras claramente inválidas.
# ══════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

from typing import List, Optional  # noqa: UP035 — se testea el converter

import pytest
from pydantic import BaseModel, Field, RootModel

from emoparse.core.grammar import GrammarError, schema_to_gbnf


class _MetadatosSchema(BaseModel):
    tipo_discurso: str = Field(description="Tipo de discurso")
    tipo_discurso_justificacion: str = Field(description="Justificación del tipo")
    ciudad: str = Field(description="Ciudad del discurso")
    provincia: str
    pais: str
    lugar_justificacion: str


class _ActorSchema(BaseModel):
    actor: str
    tipo: str  # humano_individual | colectivo | institucional
    modo: str  # explícito | inferido
    justificacion: str


class _ActoresBatchItemSchema(BaseModel):
    unit_idx: int
    actores: List[_ActorSchema]


class _ListaActoresBatchSchema(RootModel[List[_ActoresBatchItemSchema]]):
    """Caso real de EmoParse: top-level es array de objetos."""


class _OpcionalSchema(BaseModel):
    name: str
    age: Optional[int] = None  # noqa: UP045 — se testea el converter


# ══════════════════════════════════════════════════════════════════════════════
#  Tests estructurales
# ══════════════════════════════════════════════════════════════════════════════


class TestStructure:
    """La gramática siempre tiene `root` y las primitivas mínimas."""

    def test_simple_schema_has_root(self) -> None:
        g = schema_to_gbnf(_MetadatosSchema)
        assert g.startswith("root ::=") or "\nroot ::=" in g

    def test_primitives_are_present(self) -> None:
        g = schema_to_gbnf(_MetadatosSchema)
        # Las primitivas tienen que estar al final.
        for name in ("string", "integer", "number", "boolean", "null", "ws"):
            assert f"{name} ::=" in g, f"Falta primitiva '{name}' en gramática"

    def test_no_placeholder_remains(self) -> None:
        """Ningún placeholder debe quedar sin resolver."""
        g = schema_to_gbnf(_ListaActoresBatchSchema)
        assert "<<placeholder>>" not in g

    def test_required_fields_appear_as_literals(self) -> None:
        """Todos los campos required del schema deben aparecer como
        literales JSON en la gramática."""
        g = schema_to_gbnf(_MetadatosSchema)
        for field in (
            "tipo_discurso",
            "tipo_discurso_justificacion",
            "ciudad",
            "provincia",
            "pais",
            "lugar_justificacion",
        ):
            # En la gramática los nombres se emiten como literales JSON
            # con escape: \"tipo_discurso\".
            assert f'\\"{field}\\"' in g, f"Falta campo '{field}' en gramática"

    def test_string_rule_forbids_empty(self) -> None:
        """La regla `string` debe usar `+` (uno-o-más) en lugar de `*`
        para que el sampler no pueda emitir cadenas vacías.

        Esto es defensa-en-profundidad: garantiza a nivel sampler la
        decisión de diseño de no permitir strings vacíos como atajo
        para "no hay valor".
        """
        g = schema_to_gbnf(_MetadatosSchema)
        # Se busca específicamente el patrón cierre-paréntesis-más-comillas
        # que es la firma de la regla string al final. Si en algún momento
        # alguien la cambia a `*`, este test falla.
        assert ")+ \"\\\"\"" in g, (
            "La regla `string` no usa `+`: el sampler podría emitir "
            "cadenas vacías. Revisar PRIMITIVE_RULES en core/grammar.py."
        )
        # Y el caso negativo: que no esté la versión con `*`.
        assert ")* \"\\\"\"" not in g, (
            "Encontrado `)* \"\"` en la gramática: alguna regla permite "
            "vacíos. Revisar PRIMITIVE_RULES."
        )


# ══════════════════════════════════════════════════════════════════════════════
#  RootModel[List[...]]
# ══════════════════════════════════════════════════════════════════════════════


class TestRootModelList:
    """Verifica el caso más complejo: top-level es un array (RootModel)."""

    def test_root_is_array(self) -> None:
        g = schema_to_gbnf(_ListaActoresBatchSchema)
        # El root debería contener un array, es decir referenciar una
        # regla `arr_*` o expandir `[ ... ]`.
        # La forma robusta: el primer non-empty body después de `root ::=`
        # debería incluir la apertura de array `[`.
        root_line = next(
            line for line in g.splitlines() if line.startswith("root ::=")
        )
        # Se busca la regla referenciada por root y se verifica que
        # contiene `"["`.
        rule_ref = root_line.replace("root ::=", "").strip()
        # Root ahora puede ser una referencia a otra regla o ser inline.
        # Si es referencia, se busca esa regla.
        if " " not in rule_ref and "::" not in rule_ref:
            # Es solo un nombre de regla.
            target = next(
                line for line in g.splitlines()
                if line.startswith(f"{rule_ref} ::=")
            )
            assert '"["' in target or "[" in target
        else:
            assert '"["' in rule_ref

    def test_inner_object_fields_present(self) -> None:
        """Los campos de _ActoresBatchItemSchema deben estar presentes."""
        g = schema_to_gbnf(_ListaActoresBatchSchema)
        assert '\\"unit_idx\\"' in g
        assert '\\"actores\\"' in g

    def test_nested_actor_fields_present(self) -> None:
        """Los campos de _ActorSchema (anidado) deben estar presentes."""
        g = schema_to_gbnf(_ListaActoresBatchSchema)
        for field in ("actor", "tipo", "modo", "justificacion"):
            assert f'\\"{field}\\"' in g


# ══════════════════════════════════════════════════════════════════════════════
#  Optional / nullable
# ══════════════════════════════════════════════════════════════════════════════


class TestOptionals:
    def test_optional_emits_anyof_with_null(self) -> None:
        """`Optional[int] = None` debería traducirse a (integer | null)."""
        g = schema_to_gbnf(_OpcionalSchema)
        assert '\\"name\\"' in g
        assert '\\"age\\"' not in g


# ══════════════════════════════════════════════════════════════════════════════
#  Casos de error
# ══════════════════════════════════════════════════════════════════════════════


class TestErrorCases:
    def test_enum_with_non_string_raises(self) -> None:
        from typing import Literal

        class M(BaseModel):
            x: Literal[1, 2, 3]  # enum int — no soportado

        with pytest.raises(GrammarError, match="no-string"):
            schema_to_gbnf(M)


# ══════════════════════════════════════════════════════════════════════════════
#  Test de integración real con llama.cpp (skip si no instalado)
# ══════════════════════════════════════════════════════════════════════════════


@pytest.mark.integration
class TestLlamaGrammarIntegration:
    """Verifica que llama.cpp acepta nuestras gramáticas como válidas.

    No requiere modelo cargado: solo `LlamaGrammar.from_string()`,
    que parsea la gramática y devuelve un objeto utilizable.
    """

    def test_llamacpp_accepts_metadatos_grammar(self) -> None:
        try:
            from llama_cpp import LlamaGrammar
        except ImportError:
            pytest.skip("llama-cpp-python no instalado")
        g = schema_to_gbnf(_MetadatosSchema)
        # Si la sintaxis es inválida, llama.cpp lanza al parsear.
        grammar = LlamaGrammar.from_string(g, verbose=False)
        assert grammar is not None

    def test_llamacpp_accepts_root_array_grammar(self) -> None:
        try:
            from llama_cpp import LlamaGrammar
        except ImportError:
            pytest.skip("llama-cpp-python no instalado")
        g = schema_to_gbnf(_ListaActoresBatchSchema)
        grammar = LlamaGrammar.from_string(g, verbose=False)
        assert grammar is not None
