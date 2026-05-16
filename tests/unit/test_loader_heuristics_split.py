# ══════════════════════════════════════════════════════════════════════════════
#  tests.unit.test_loader_heuristics_split
#
#  Verifica la carga de heurísticas separadas por agente y la
#  compatibilidad con el archivo monolítico.
# ══════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

import pytest

from emoparse.knowledge.loader import KnowledgeError, KnowledgeLoader


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture()
def knowledge_dir(tmp_path):
    """Directorio temporal con estructura de heurísticas separadas."""
    hdir = tmp_path / "heuristicas"
    hdir.mkdir()

    # Archivos por agente.
    (hdir / "actors.md").write_text("Reglas para actores.", encoding="utf-8")
    (hdir / "emotions.md").write_text("Reglas para emociones.", encoding="utf-8")
    (hdir / "emotions_pass2.md").write_text("Reglas para emociones pase 2.", encoding="utf-8")
    (hdir / "characterizer.md").write_text("Reglas para characterizer.", encoding="utf-8")
    (hdir / "enunciation.md").write_text("Reglas para enunciación.", encoding="utf-8")
    (hdir / "judge.md").write_text("Reglas para judge.", encoding="utf-8")

    # Archivo monolítico legacy.
    (tmp_path / "heuristicas.md").write_text(
        "Reglas monolíticas legacy.", encoding="utf-8"
    )

    return tmp_path


@pytest.fixture()
def loader(knowledge_dir):
    return KnowledgeLoader(knowledge_dir)


# ── Tests: carga por agente ───────────────────────────────────────────────────

class TestLoadHeuristicsSplit:

    def test_actors_loads_correctly(self, loader: KnowledgeLoader) -> None:
        content = loader.load_heuristics("heuristicas/actors.md")
        assert content == "Reglas para actores."

    def test_emotions_loads_correctly(self, loader: KnowledgeLoader) -> None:
        content = loader.load_heuristics("heuristicas/emotions.md")
        assert content == "Reglas para emociones."

    def test_emotions_pass2_loads_correctly(self, loader: KnowledgeLoader) -> None:
        content = loader.load_heuristics("heuristicas/emotions_pass2.md")
        assert content == "Reglas para emociones pase 2."

    def test_characterizer_loads_correctly(self, loader: KnowledgeLoader) -> None:
        content = loader.load_heuristics("heuristicas/characterizer.md")
        assert content == "Reglas para characterizer."

    def test_enunciation_loads_correctly(self, loader: KnowledgeLoader) -> None:
        content = loader.load_heuristics("heuristicas/enunciation.md")
        assert content == "Reglas para enunciación."

    def test_judge_loads_correctly(self, loader: KnowledgeLoader) -> None:
        content = loader.load_heuristics("heuristicas/judge.md")
        assert content == "Reglas para judge."


# ── Tests: compatibilidad monolítica ─────────────────────────────────────────

class TestLoadHeuristicsMonolithicCompat:

    def test_monolithic_file_still_works(self, loader: KnowledgeLoader) -> None:
        """Pasar heuristicas.md sigue funcionando (compat hacia atrás)."""
        content = loader.load_heuristics("heuristicas.md")
        assert content == "Reglas monolíticas legacy."

    def test_split_and_monolithic_return_different_content(
        self, loader: KnowledgeLoader
    ) -> None:
        """Los archivos split y el monolítico devuelven contenido distinto."""
        split = loader.load_heuristics("heuristicas/emotions.md")
        mono = loader.load_heuristics("heuristicas.md")
        assert split != mono


# ── Tests: errores ───────────────────────────────────────────────────────────

class TestLoadHeuristicsErrors:

    def test_missing_file_raises_knowledge_error(
        self, loader: KnowledgeLoader
    ) -> None:
        with pytest.raises(KnowledgeError):
            loader.load_heuristics("heuristicas/no_existe.md")

    def test_missing_split_dir_raises_knowledge_error(
        self, loader: KnowledgeLoader
    ) -> None:
        with pytest.raises(KnowledgeError):
            loader.load_heuristics("heuristicas/no_existe_dir/actors.md")

    def test_empty_file_raises_knowledge_error(
        self, tmp_path: object
    ) -> None:
        """Un archivo de heurísticas vacío debe lanzar KnowledgeError."""
        import pathlib
        d = pathlib.Path(str(tmp_path)) / "heuristicas"
        d.mkdir(exist_ok=True)
        (d / "vacio.md").write_text("", encoding="utf-8")
        loader = KnowledgeLoader(d.parent)
        with pytest.raises(KnowledgeError):
            loader.load_heuristics("heuristicas/vacio.md")
