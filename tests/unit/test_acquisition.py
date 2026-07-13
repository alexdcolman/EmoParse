# ══════════════════════════════════════════════════════════════════════════════
#  Tests de emoparse.acquisition (appender, seudonimización, importadores)
# ══════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

import json

import pytest

from emoparse.acquisition.jsonl_appender import JsonlAppender
from emoparse.acquisition.post_record import PostRecord
from emoparse.acquisition.pseudonym import Pseudonymizer
from emoparse.acquisition.sources.jsonl_import import JsonlImportAdapter

pytestmark = pytest.mark.unit


def _record(pid: str, **kw) -> PostRecord:
    defaults = {"plataforma": "bluesky", "autor_handle": "ana", "texto": "hola"}
    defaults.update(kw)
    return PostRecord(id=pid, **defaults)


class TestJsonlAppender:
    def test_append_y_dedupe(self, tmp_path):
        out = tmp_path / "corpus.jsonl"
        with JsonlAppender(out) as app:
            assert app.append(_record("p1"))
            assert not app.append(_record("p1"))
            assert app.append(_record("p2"))
        lines = out.read_text(encoding="utf-8").strip().splitlines()
        assert len(lines) == 2

    def test_reanudacion(self, tmp_path):
        out = tmp_path / "corpus.jsonl"
        with JsonlAppender(out) as app:
            app.append(_record("p1"))
        with JsonlAppender(out) as app:
            assert app.has_id("p1")
            assert not app.append(_record("p1"))
            assert app.append(_record("p3"))
        assert len(out.read_text(encoding="utf-8").strip().splitlines()) == 2

    def test_roundtrip_es_cargable(self, tmp_path):
        from emoparse.inputs.posts_loader import load_posts
        out = tmp_path / "corpus.jsonl"
        with JsonlAppender(out) as app:
            app.append(_record("p1", texto="con 😡 y #tag"))
        bundle = load_posts(out)
        assert bundle.posts.iloc[0]["texto"] == "con 😡 y #tag"


class TestPseudonymizer:
    def test_alias_estable(self, tmp_path):
        ps = Pseudonymizer(tmp_path / "s.salt")
        assert ps.alias("Ana") == ps.alias("@ana")
        ps2 = Pseudonymizer(tmp_path / "s.salt")  # misma sal → mismos alias
        assert ps.alias("ana") == ps2.alias("ana")

    def test_apply_reescribe_menciones_conocidas(self, tmp_path):
        ps = Pseudonymizer(tmp_path / "s.salt")
        ps.apply(_record("p0", autor_handle="luis"))  # conoce a luis
        rec = ps.apply(_record(
            "p1", autor_handle="ana",
            texto="hola @luis y @desconocido",
            autor_display="Ana", url="https://x/1",
        ))
        assert rec.autor_handle.startswith("u_")
        assert "@" + ps.alias("luis") in rec.texto
        assert "@desconocido" in rec.texto  # no visto: no se toca
        assert rec.autor_display is None
        assert rec.url is None


class TestJsonlImport:
    def test_autodeteccion_formas(self, tmp_path):
        f = tmp_path / "dump.jsonl"
        lines = [
            # normalizado
            {"id": "n1", "texto": "normalizado", "autor_handle": "ana",
             "plataforma": "bluesky"},
            # tweet v2 suelto
            {"id": "100", "text": "tweet suelto", "author_id": "u9",
             "conversation_id": "100"},
            # página v2 con includes
            {"data": [{"id": "200", "text": "de página", "author_id": "u1",
                       "referenced_tweets": [{"type": "replied_to", "id": "100"}]}],
             "includes": {"users": [{"id": "u1", "username": "luis"}]}},
        ]
        f.write_text(
            "\n".join(json.dumps(x, ensure_ascii=False) for x in lines),
            encoding="utf-8",
        )
        records = list(JsonlImportAdapter(str(f)).search(""))
        assert [r.id for r in records] == ["n1", "100", "200"]
        assert records[0].plataforma == "bluesky"
        assert records[2].autor_handle == "luis"
        assert records[2].tipo == "reply"
        assert records[2].en_respuesta_a == "100"

    def test_fetch_user_filtra(self, tmp_path):
        f = tmp_path / "dump.jsonl"
        rows = [
            {"id": "a", "texto": "x", "autor_handle": "ana"},
            {"id": "b", "texto": "y", "autor_handle": "luis"},
        ]
        f.write_text(
            "\n".join(json.dumps(x) for x in rows), encoding="utf-8"
        )
        records = list(JsonlImportAdapter(str(f)).fetch_user("@ANA"))
        assert [r.id for r in records] == ["a"]
