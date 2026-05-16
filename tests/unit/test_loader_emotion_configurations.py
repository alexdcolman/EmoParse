# ══════════════════════════════════════════════════════════════════════════════
#  tests.unit.test_loader_emotion_configurations
#
#  Verifica load_emotion_configurations: parseo, formato, caching, errores.
# ══════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

import json
from pathlib import Path

import pytest

from emoparse.knowledge.loader import KnowledgeError, KnowledgeLoader


def _write_json(dir_: Path, name: str, data: dict) -> Path:
    p = dir_ / name
    p.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return p


def _sample_configs() -> dict:
    return {
        "version": "v1",
        "configuraciones": {
            "sostenido_en_sustantivos": {
                "id": 1,
                "definicion": "Sustantivos como núcleo.",
                "heuristica_deteccion": "Buscar nominales afectivos.",
                "ejemplos": ["un profundo dolor"],
            },
            "sostenido_en_adjetivos": {
                "id": 2,
                "definicion": "Adjetivos evaluativos.",
                "heuristica_deteccion": "Buscar adjetivos afectivos.",
                "ejemplos": ["situación inquietante", "ambiente angustiante"],
            },
        },
    }


class TestLoadEmotionConfigurations:

    def test_returns_formatted_string(self, tmp_path: Path) -> None:
        _write_json(tmp_path, "configuraciones_emocion.json", _sample_configs())
        loader = KnowledgeLoader(tmp_path)

        out = loader.load_emotion_configurations()

        assert "sostenido_en_sustantivos (id 1)" in out
        assert "sostenido_en_adjetivos (id 2)" in out
        assert "Sustantivos como núcleo." in out
        assert "Detección: Buscar nominales afectivos." in out
        assert "Ejemplos: un profundo dolor" in out
        assert "situación inquietante; ambiente angustiante" in out

    def test_cache_reuses_result(self, tmp_path: Path) -> None:
        path = _write_json(
            tmp_path, "configuraciones_emocion.json", _sample_configs()
        )
        loader = KnowledgeLoader(tmp_path)

        out1 = loader.load_emotion_configurations()
        path.write_text("{}", encoding="utf-8")  # rompe el JSON
        out2 = loader.load_emotion_configurations()

        assert out1 == out2  # vino del cache, no re-leyó

    def test_missing_file_raises(self, tmp_path: Path) -> None:
        loader = KnowledgeLoader(tmp_path)
        with pytest.raises(KnowledgeError):
            loader.load_emotion_configurations()

    def test_empty_configuraciones_raises(self, tmp_path: Path) -> None:
        _write_json(
            tmp_path, "configuraciones_emocion.json",
            {"version": "v1", "configuraciones": {}},
        )
        loader = KnowledgeLoader(tmp_path)
        with pytest.raises(KnowledgeError):
            loader.load_emotion_configurations()

    def test_entry_without_ejemplos_still_renders(self, tmp_path: Path) -> None:
        _write_json(
            tmp_path, "configuraciones_emocion.json",
            {
                "configuraciones": {
                    "x": {"id": 1, "definicion": "d", "heuristica_deteccion": "h"},
                },
            },
        )
        loader = KnowledgeLoader(tmp_path)
        out = loader.load_emotion_configurations()
        assert "x (id 1): d" in out
        assert "Ejemplos:" not in out
