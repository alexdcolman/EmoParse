# ══════════════════════════════════════════════════════════════════════════════
#  Tests de emoparse.inputs.posts_loader
# ══════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

import json
from pathlib import Path

import pytest

from emoparse.inputs.loader import InputError
from emoparse.inputs.posts_loader import load_posts, posts_to_discursos

pytestmark = pytest.mark.unit


def _write_jsonl(path: Path, rows: list[dict]) -> Path:
    with path.open("w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    return path


BASE = {"plataforma": "bluesky", "fecha": "2026-05-01T10:00:00Z", "lang": "es"}


class TestLoadPosts:
    def test_carga_normal(self, tmp_path):
        p = _write_jsonl(tmp_path / "c.jsonl", [
            {**BASE, "id": "p1", "texto": "hola mundo", "autor_handle": "ana"},
            {**BASE, "id": "p2", "texto": "respondo", "autor_handle": "@luis",
             "en_respuesta_a": "p1"},
        ])
        bundle = load_posts(p)
        assert len(bundle.posts) == 2
        # El '@' inicial del handle se normaliza.
        assert set(bundle.posts["autor_handle"]) == {"ana", "luis"}
        # El tipo se infiere de las referencias cuando no viene dado.
        assert bundle.posts.set_index("post_id").loc["p2", "tipo"] == "reply"
        assert len(bundle.autores) == 2

    def test_repost_puro_permite_texto_vacio(self, tmp_path):
        p = _write_jsonl(tmp_path / "c.jsonl", [
            {**BASE, "id": "p1", "texto": "original", "autor_handle": "ana"},
            {**BASE, "id": "p2", "texto": "", "autor_handle": "medio",
             "tipo": "repost", "reposteo_a": "p1"},
        ])
        bundle = load_posts(p)
        assert bundle.posts.set_index("post_id").loc["p2", "es_repost_puro"] == 1

    def test_texto_vacio_no_repost_falla(self, tmp_path):
        p = _write_jsonl(tmp_path / "c.jsonl", [
            {**BASE, "id": "p1", "texto": "", "autor_handle": "ana"},
        ])
        with pytest.raises(InputError, match="texto"):
            load_posts(p)

    def test_ids_duplicados_fallan(self, tmp_path):
        p = _write_jsonl(tmp_path / "c.jsonl", [
            {**BASE, "id": "p1", "texto": "a", "autor_handle": "ana"},
            {**BASE, "id": "p1", "texto": "b", "autor_handle": "luis"},
        ])
        with pytest.raises(InputError, match="duplicados"):
            load_posts(p)

    def test_campo_obligatorio_faltante(self, tmp_path):
        p = _write_jsonl(tmp_path / "c.jsonl", [
            {**BASE, "id": "p1", "texto": "sin autor"},
        ])
        with pytest.raises(InputError, match="obligatorios"):
            load_posts(p)

    def test_fixture_del_repo(self):
        fixture = Path(__file__).resolve().parents[2] / "data" / "ejemplos" / "tuits_ejemplo.jsonl"
        if not fixture.is_file():
            pytest.skip("fixture de ejemplo no presente")
        bundle = load_posts(fixture)
        assert len(bundle.posts) >= 20
        assert int(bundle.posts["es_repost_puro"].sum()) >= 2


class TestPostsToDiscursos:
    def test_excluye_reposts_puros(self, tmp_path):
        p = _write_jsonl(tmp_path / "c.jsonl", [
            {**BASE, "id": "p1", "texto": "original", "autor_handle": "ana"},
            {**BASE, "id": "p2", "texto": "", "autor_handle": "medio",
             "tipo": "repost", "reposteo_a": "p1"},
        ])
        bundle = load_posts(p)
        df = posts_to_discursos(bundle.posts)
        assert df["codigo"].tolist() == ["p1"]
        assert df["contenido"].tolist() == ["original"]

    def test_corpus_solo_reposts_falla(self, tmp_path):
        p = _write_jsonl(tmp_path / "c.jsonl", [
            {**BASE, "id": "p2", "texto": "", "autor_handle": "medio",
             "tipo": "repost", "reposteo_a": "p1"},
        ])
        bundle = load_posts(p)
        with pytest.raises(InputError, match="analizables"):
            posts_to_discursos(bundle.posts)
