# ══════════════════════════════════════════════════════════════════════════════
#  tests.unit.test_knowledge
#
#  Tests del KnowledgeLoader: carga de ontologías, diccionarios, heurísticas.
# ══════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

import json
from pathlib import Path

import pytest

from emoparse.knowledge import KnowledgeError, KnowledgeLoader


# ══════════════════════════════════════════════════════════════════════════════
#  Helpers
# ══════════════════════════════════════════════════════════════════════════════


def _write_json(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


# ══════════════════════════════════════════════════════════════════════════════
#  Ontologías — formato 1 (con clave top-level)
# ══════════════════════════════════════════════════════════════════════════════


class TestOntologyFormat1:
    """Formato típico del repo: {"<key_top>": {<id>: {...}}}."""

    def test_loads_emociones_style(self, tmp_path: Path) -> None:
        _write_json(tmp_path / "foria.json", {
            "foria": {
                "euforico": {
                    "nombre": "Eufórico",
                    "descripcion": "Tono positivo.",
                    "ejemplo": "Estoy feliz.",
                },
                "disforico": {
                    "nombre": "Disfórico",
                    "descripcion": "Tono negativo.",
                    "ejemplo": "Me preocupa.",
                },
            }
        })
        loader = KnowledgeLoader(tmp_path)
        result = loader.load_ontology("foria.json")

        assert "Eufórico" in result
        assert "Disfórico" in result
        assert "Tono positivo" in result
        assert "Estoy feliz" in result

    def test_format_consistency(self, tmp_path: Path) -> None:
        """El formato de salida es leíble: cada entrada en una línea con `- `."""
        _write_json(tmp_path / "x.json", {
            "x": {
                "a": {"nombre": "A", "descripcion": "Aaaa.", "ejemplo": "ej_a"},
                "b": {"nombre": "B", "descripcion": "Bbbb.", "ejemplo": "ej_b"},
            }
        })
        result = KnowledgeLoader(tmp_path).load_ontology("x.json")
        lines = result.splitlines()
        assert len(lines) == 2
        assert all(line.startswith("- ") for line in lines)


# ══════════════════════════════════════════════════════════════════════════════
#  Ontologías — formato 2 (sin clave top-level)
# ══════════════════════════════════════════════════════════════════════════════


class TestOntologyFormat2:
    """Top-level es directamente el diccionario de definiciones."""

    def test_loads_flat_format(self, tmp_path: Path) -> None:
        _write_json(tmp_path / "x.json", {
            "alpha": {"nombre": "Alpha", "descripcion": "El primero."},
            "beta": {"nombre": "Beta", "descripcion": "El segundo."},
        })
        result = KnowledgeLoader(tmp_path).load_ontology("x.json")
        assert "Alpha" in result
        assert "Beta" in result


# ══════════════════════════════════════════════════════════════════════════════
#  Diccionario de tipos: devuelve dict, no string
# ══════════════════════════════════════════════════════════════════════════════


class TestDiccionarioTipos:

    def test_returns_dict(self, tmp_path: Path) -> None:
        _write_json(tmp_path / "tipos.json", {
            "asuncion": "Discurso de toma de posesión.",
            "campana": "Discurso de campaña.",
        })
        result = KnowledgeLoader(tmp_path).load_diccionario_tipos("tipos.json")
        assert isinstance(result, dict)
        assert result["asuncion"] == "Discurso de toma de posesión."


# ══════════════════════════════════════════════════════════════════════════════
#  Heurísticas: texto libre
# ══════════════════════════════════════════════════════════════════════════════


class TestHeuristics:

    def test_loads_markdown(self, tmp_path: Path) -> None:
        content = "# Heurísticas\n\n- Regla 1: ...\n- Regla 2: ..."
        (tmp_path / "h.md").write_text(content, encoding="utf-8")

        result = KnowledgeLoader(tmp_path).load_heuristics("h.md")
        assert "Regla 1" in result
        assert "Regla 2" in result

    def test_strips_outer_whitespace(self, tmp_path: Path) -> None:
        (tmp_path / "h.md").write_text("\n\n  texto  \n\n", encoding="utf-8")
        result = KnowledgeLoader(tmp_path).load_heuristics("h.md")
        assert result == "texto"

    def test_empty_file_raises(self, tmp_path: Path) -> None:
        (tmp_path / "vacio.md").write_text("   \n\n  ", encoding="utf-8")
        with pytest.raises(KnowledgeError, match="vacío"):
            KnowledgeLoader(tmp_path).load_heuristics("vacio.md")


# ══════════════════════════════════════════════════════════════════════════════
#  Cache
# ══════════════════════════════════════════════════════════════════════════════


class TestCache:

    def test_second_load_uses_cache(self, tmp_path: Path) -> None:
        """Si modificás el archivo después de cargar, la versión cacheada
        sigue activa hasta clear_cache()."""
        path = tmp_path / "x.json"
        _write_json(path, {"x": {"a": {"nombre": "Original"}}})
        loader = KnowledgeLoader(tmp_path)
        first = loader.load_ontology("x.json")

        # Modificar archivo en disco.
        _write_json(path, {"x": {"a": {"nombre": "Modificado"}}})
        cached = loader.load_ontology("x.json")
        assert cached == first  # cache: no se enteró del cambio

        loader.clear_cache()
        fresh = loader.load_ontology("x.json")
        assert "Modificado" in fresh


# ══════════════════════════════════════════════════════════════════════════════
#  Errores
# ══════════════════════════════════════════════════════════════════════════════


class TestErrors:

    def test_file_not_found(self, tmp_path: Path) -> None:
        loader = KnowledgeLoader(tmp_path)
        with pytest.raises(KnowledgeError, match="no encontrado"):
            loader.load_ontology("inexistente.json")

    def test_invalid_json(self, tmp_path: Path) -> None:
        (tmp_path / "bad.json").write_text("{ esto no es json }", encoding="utf-8")
        with pytest.raises(KnowledgeError, match="JSON inválido"):
            KnowledgeLoader(tmp_path).load_ontology("bad.json")

    def test_json_not_a_dict(self, tmp_path: Path) -> None:
        (tmp_path / "x.json").write_text("[1, 2, 3]", encoding="utf-8")
        with pytest.raises(KnowledgeError, match="mapping"):
            KnowledgeLoader(tmp_path).load_ontology("x.json")

    def test_cannot_infer_structure(self, tmp_path: Path) -> None:
        """Si el JSON tiene varias claves top-level con valores no-dict,
        no es ninguno de los formatos esperados."""
        _write_json(tmp_path / "x.json", {"a": "str", "b": 42})
        with pytest.raises(KnowledgeError, match="estructura"):
            KnowledgeLoader(tmp_path).load_ontology("x.json")


# ══════════════════════════════════════════════════════════════════════════════
#  Path resolution
# ══════════════════════════════════════════════════════════════════════════════


class TestPathResolution:

    def test_relative_path_resolves_against_dir(self, tmp_path: Path) -> None:
        sub = tmp_path / "sub"
        sub.mkdir()
        _write_json(sub / "x.json", {"x": {"a": {"nombre": "A"}}})

        loader = KnowledgeLoader(sub)
        result = loader.load_ontology("x.json")
        assert "A" in result

    def test_absolute_path_used_as_is(self, tmp_path: Path) -> None:
        """Pasar un path absoluto override del knowledge_dir."""
        elsewhere = tmp_path / "elsewhere"
        elsewhere.mkdir()
        target = elsewhere / "x.json"
        _write_json(target, {"x": {"a": {"nombre": "A"}}})

        # Loader configurado con un dir distinto.
        loader = KnowledgeLoader(tmp_path / "no_existe")
        # Pero se pasa path absoluto.
        result = loader.load_ontology(str(target))
        assert "A" in result
