# ══════════════════════════════════════════════════════════════════════════════
#  tests/unit/test_revision_overlay.py
#
#  Tests de RevisionOverlay, la clase que maneja las correcciones manuales a los datos exportados.
# ══════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

import json

import pytest

from emoparse.app.revision_overlay import (
    OverlayCorruptError,
    RevisionOverlay,
    default_overlay_path,
)


def _ov(tmp_path):
    return RevisionOverlay(tmp_path / "run" / "revision_overlay.json")


def test_default_path_uses_db_stem(tmp_path):
    db = tmp_path / "runs" / "milei2024.sqlite"
    p = default_overlay_path(db)
    assert p.parent.name == "milei2024"
    assert p.parent.parent.name == "runs"
    assert p.name == "revision_overlay.json"


def test_empty_when_no_file(tmp_path):
    ov = _ov(tmp_path)
    assert ov.get_discurso("d1") == {"overrides": {}, "confirmado": {}}
    assert ov.list_new_emociones("d1", 0) == []


def test_discurso_override_and_confirm(tmp_path):
    ov = _ov(tmp_path)
    ov.set_discurso_override("d1", "tipo_discurso", "asunción")
    ov.confirm_discurso_field("d1", "tipo_discurso", True)
    again = RevisionOverlay(ov.path)
    d = again.get_discurso("d1")
    assert d["overrides"]["tipo_discurso"] == "asunción"
    assert d["confirmado"]["tipo_discurso"] is True


def test_frase_actor_remove_restore_add(tmp_path):
    ov = _ov(tmp_path)
    ov.remove_actor("d1", 2, "0")
    assert "0" in ov.get_frase("d1", 2)["actores_removidos"]
    ov.restore_actor("d1", 2, "0")
    assert ov.get_frase("d1", 2)["actores_removidos"] == []
    ov.add_actor("d1", 2, {"actor_mencionado": "X", "actor_canonico": "x"})
    assert len(ov.get_frase("d1", 2)["actores_agregados"]) == 1
    ov.remove_added_actor("d1", 2, 0)
    assert ov.get_frase("d1", 2)["actores_agregados"] == []


def test_emocion_override_nested_and_effective(tmp_path):
    ov = _ov(tmp_path)
    db_rec = {
        "experienciador": "yo",
        "caracterizacion": {"foria": "euforico", "fuente": "x"},
        "actantes": {"mediador": {"presencia": "ausente"}},
    }
    ov.set_emocion_override("d1", 1, 0, "experienciador", "Milei")
    ov.set_emocion_override_path("d1", 1, 0, ["caracterizacion", "foria"], "disforico")
    ov.set_emocion_override_path("d1", 1, 0, ["actantes", "mediador", "presencia"], "presente")
    eff = ov.effective_emocion("d1", 1, 0, db_rec)
    assert eff["experienciador"] == "Milei"
    assert eff["caracterizacion"]["foria"] == "disforico"
    assert eff["caracterizacion"]["fuente"] == "x"           # no pisado
    assert eff["actantes"]["mediador"]["presencia"] == "presente"
    # no muta el registro original
    assert db_rec["experienciador"] == "yo"
    assert db_rec["caracterizacion"]["foria"] == "euforico"


def test_emocion_delete_restore(tmp_path):
    ov = _ov(tmp_path)
    assert ov.is_emocion_deleted("d1", 0, 0) is False
    ov.delete_emocion("d1", 0, 0)
    assert ov.is_emocion_deleted("d1", 0, 0) is True
    ov.restore_emocion("d1", 0, 0)
    assert ov.is_emocion_deleted("d1", 0, 0) is False


def test_new_emociones(tmp_path):
    ov = _ov(tmp_path)
    ov.add_emocion("d1", 3, {"tipo_emocion": "ira", "experienciador": "Milei"})
    assert len(ov.list_new_emociones("d1", 3)) == 1
    ov.remove_new_emocion("d1", 3, 0)
    assert ov.list_new_emociones("d1", 3) == []


def test_propose_actor_no_overwrite(tmp_path):
    ov = _ov(tmp_path)
    ov.propose_actor("nuevo_actor", "Nuevo Actor", "colectivo", existing_kb_ids=set())
    assert "nuevo_actor" in ov.list_proposed_actors()
    # no se puede pisar uno de la KB
    with pytest.raises(ValueError):
        ov.propose_actor("javier_milei", "X", "individuo", {"javier_milei"})
    # no se puede re-proponer el mismo
    with pytest.raises(ValueError):
        ov.propose_actor("nuevo_actor", "Otro", "individuo", set())


def test_atomic_save_creates_backup_and_roundtrips(tmp_path):
    ov = _ov(tmp_path)
    ov.set_discurso_override("d1", "lugar", "Buenos Aires")
    assert ov.path.exists()
    ov.set_discurso_override("d1", "lugar", "Córdoba")          # 2do save → .bak
    bak = ov.path.with_suffix(ov.path.suffix + ".bak")
    assert bak.exists()
    reloaded = json.loads(ov.path.read_text(encoding="utf-8"))
    assert reloaded["discursos"]["d1"]["overrides"]["lugar"] == "Córdoba"


def test_corrupt_file_raises_and_is_not_clobbered(tmp_path):
    p = tmp_path / "run" / "revision_overlay.json"
    p.parent.mkdir(parents=True)
    p.write_text("{ esto no es json", encoding="utf-8")
    with pytest.raises(OverlayCorruptError):
        RevisionOverlay(p)
    # el archivo corrupto sigue intacto (no se pisó)
    assert p.read_text(encoding="utf-8") == "{ esto no es json"
