# ══════════════════════════════════════════════════════════════════════════════
#  tests.unit.test_kb_editor
#
#  Tests del editor de la KB de actores: validaciones, idempotencia,
#  backup, escritura atómica.
# ══════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

import json
from pathlib import Path

import pytest

from emoparse.knowledge.kb_editor import (
    KbEditorError,
    backup_kb,
    discard,
    load_kb,
    merge,
    promote,
)


@pytest.fixture
def kb_path(tmp_path: Path) -> Path:
    """KB inicial con 2 canónicos."""
    p = tmp_path / "actors_kb.json"
    p.write_text(json.dumps({
        "version": "v1",
        "actors": {
            "gobierno_argentino": {
                "display_name": "Gobierno argentino",
                "aliases": ["el gobierno"],
                "tipo": "institucion",
            },
            "pueblo_argentino": {
                "display_name": "Pueblo argentino",
                "aliases": ["el pueblo", "los argentinos"],
                "tipo": "colectivo",
            },
        },
    }, indent=2), encoding="utf-8")
    return p


class TestLoadKb:

    def test_loads_valid_kb(self, kb_path: Path) -> None:
        data = load_kb(kb_path)
        assert "actors" in data
        assert "gobierno_argentino" in data["actors"]

    def test_raises_on_missing_file(self, tmp_path: Path) -> None:
        with pytest.raises(KbEditorError, match="no encontrada"):
            load_kb(tmp_path / "nope.json")

    def test_raises_on_invalid_json(self, tmp_path: Path) -> None:
        p = tmp_path / "broken.json"
        p.write_text("{not json")
        with pytest.raises(KbEditorError, match="JSON inválido"):
            load_kb(p)

    def test_raises_on_missing_actors_key(self, tmp_path: Path) -> None:
        p = tmp_path / "no_actors.json"
        p.write_text(json.dumps({"version": "v1"}))
        with pytest.raises(KbEditorError, match="actors"):
            load_kb(p)


class TestPromote:

    def test_promotes_new_canonical(self, kb_path: Path) -> None:
        promote(
            kb_path,
            canonical_id="javier_milei",
            display_name="Javier Milei",
            aliases_iniciales=["Milei", "el presidente"],
            tipo="individuo",
        )
        data = load_kb(kb_path)
        e = data["actors"]["javier_milei"]
        assert e["display_name"] == "Javier Milei"
        assert "Milei" in e["aliases"]
        assert e["tipo"] == "individuo"

    def test_promote_idempotent_merges_aliases(self, kb_path: Path) -> None:
        promote(
            kb_path,
            canonical_id="javier_milei",
            display_name="Javier Milei",
            aliases_iniciales=["Milei"],
        )
        promote(
            kb_path,
            canonical_id="javier_milei",
            display_name="Javier Milei",
            aliases_iniciales=["Milei", "JM"],
        )
        data = load_kb(kb_path)
        aliases = data["actors"]["javier_milei"]["aliases"]
        # "Milei" no debe estar duplicado.
        assert sum(1 for a in aliases if a.lower() == "milei") == 1
        assert "JM" in aliases

    def test_promote_rejects_display_name_conflict(self, kb_path: Path) -> None:
        promote(
            kb_path,
            canonical_id="javier_milei",
            display_name="Javier Milei",
        )
        with pytest.raises(KbEditorError, match="display_name"):
            promote(
                kb_path,
                canonical_id="javier_milei",
                display_name="Otro Nombre",
            )

    def test_promote_rejects_invalid_canonical_id(self, kb_path: Path) -> None:
        with pytest.raises(KbEditorError, match="canonical_id inválido"):
            promote(kb_path, canonical_id="Mayúsculas!", display_name="X")

    def test_promote_rejects_id_with_spaces(self, kb_path: Path) -> None:
        with pytest.raises(KbEditorError, match="canonical_id inválido"):
            promote(kb_path, canonical_id="con espacio", display_name="X")

    def test_promote_rejects_id_starting_with_number(self, kb_path: Path) -> None:
        with pytest.raises(KbEditorError, match="canonical_id inválido"):
            promote(kb_path, canonical_id="123abc", display_name="X")

    def test_promote_accepts_alphanumeric_slug(self, kb_path: Path) -> None:
        promote(
            kb_path,
            canonical_id="actor_42",
            display_name="Actor 42",
        )
        data = load_kb(kb_path)
        assert "actor_42" in data["actors"]


class TestMerge:

    def test_merge_adds_alias(self, kb_path: Path) -> None:
        merge(
            kb_path,
            canonical_id="gobierno_argentino",
            alias_to_add="el Ejecutivo",
        )
        data = load_kb(kb_path)
        assert "el Ejecutivo" in data["actors"]["gobierno_argentino"]["aliases"]

    def test_merge_idempotent_case_insensitive(self, kb_path: Path) -> None:
        merge(
            kb_path,
            canonical_id="gobierno_argentino",
            alias_to_add="el gobierno",  # ya está
        )
        merge(
            kb_path,
            canonical_id="gobierno_argentino",
            alias_to_add="EL GOBIERNO",  # variante case
        )
        data = load_kb(kb_path)
        aliases = data["actors"]["gobierno_argentino"]["aliases"]
        # No debe duplicar.
        assert sum(1 for a in aliases if a.lower() == "el gobierno") == 1

    def test_merge_rejects_nonexistent_canonical(self, kb_path: Path) -> None:
        with pytest.raises(KbEditorError, match="no existe"):
            merge(kb_path, canonical_id="no_existe", alias_to_add="x")

    def test_merge_rejects_empty_alias(self, kb_path: Path) -> None:
        with pytest.raises(KbEditorError, match="vacío"):
            merge(kb_path, canonical_id="gobierno_argentino", alias_to_add="   ")


class TestDiscard:

    def test_discard_does_not_modify_kb(self, kb_path: Path) -> None:
        before = kb_path.read_text(encoding="utf-8")
        discard(kb_path, mencion="ruido")
        after = kb_path.read_text(encoding="utf-8")
        assert before == after

    def test_discard_raises_on_missing_kb(self, tmp_path: Path) -> None:
        with pytest.raises(KbEditorError, match="no encontrada"):
            discard(tmp_path / "nope.json", mencion="x")


class TestBackup:

    def test_backup_creates_copy(self, kb_path: Path) -> None:
        bak = backup_kb(kb_path)
        assert bak.exists()
        assert ".bak." in bak.name
        # Mismo contenido.
        assert bak.read_text(encoding="utf-8") == kb_path.read_text(encoding="utf-8")

    def test_backup_of_missing_file_returns_none_path(self, tmp_path: Path) -> None:
        bak = backup_kb(tmp_path / "nope.json")
        assert not bak.exists()
        assert ".bak.NONE" in bak.name

    def test_multiple_backups_have_distinct_names(self, kb_path: Path) -> None:
        b1 = backup_kb(kb_path)
        promote(kb_path, canonical_id="otro_canonico", display_name="Otro")
        b2 = backup_kb(kb_path)
        assert b1.exists()
        assert b2.exists()


class TestAtomicWrite:

    def test_kb_remains_valid_after_many_writes(self, kb_path: Path) -> None:
        """Tras muchas operaciones, el JSON sigue siendo parseable."""
        for i in range(10):
            promote(
                kb_path,
                canonical_id=f"actor_{i}",
                display_name=f"Actor {i}",
                aliases_iniciales=[f"a{i}"],
            )
        data = load_kb(kb_path)
        assert all(f"actor_{i}" in data["actors"] for i in range(10))

    def test_no_tmp_file_left_behind(self, kb_path: Path) -> None:
        promote(kb_path, canonical_id="x_actor", display_name="X")
        # No debe quedar .tmp
        tmp = kb_path.with_suffix(kb_path.suffix + ".tmp")
        assert not tmp.exists()
