# ══════════════════════════════════════════════════════════════════════════════
#  tests.unit.test_summarizer_agent
#
#  El SummarizerAgent es el caso especial del proyecto:
#  - No usa schema (texto libre).
#  - Tiene dos pasadas (fragmentos + global).
#  - Implementa su propio chunking.
#
#  Estos tests verifican cada una de esas piezas de forma aislada.
# ══════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

import json
from typing import TypeVar

import pandas as pd
import pytest
from pydantic import BaseModel

from emoparse.agents.summarizer import SummarizerAgent, _split_into_chunks
from emoparse.core.backend.base import LLMBackend, LLMResponse, TokenUsage
from emoparse.core.backend.exceptions import BackendTimeoutError

T = TypeVar("T", bound=BaseModel)


# ══════════════════════════════════════════════════════════════════════════════
#  FakeBackend con respuestas de texto libre (no schema)
# ══════════════════════════════════════════════════════════════════════════════


class _FakeBackend(LLMBackend):
    """Cola de respuestas para summarizer. Cada generate() consume una.

    A diferencia de los otros agentes, las respuestas son strings (raw),
    no schemas Pydantic.
    """

    def __init__(self, responses: list[str | Exception]) -> None:
        self.alias = "fake"
        self._responses = list(responses)
        self.calls: list[dict[str, object]] = []

    def generate(
        self,
        system: str,
        user: str,
        *,
        schema: type[T] | None = None,
        max_tokens: int | None = None,
        temperature: float | None = None,
        seed: int | None = None,
        stop: list[str] | None = None,
        reset_before: bool = False,
    ) -> LLMResponse:
        self.calls.append({
            "system": system,
            "user": user,
            "schema": schema,
        })
        if not self._responses:
            raise AssertionError("FakeBackend sin respuestas")
        nxt = self._responses.pop(0)
        if isinstance(nxt, Exception):
            raise nxt
        return LLMResponse(
            parsed=None,  # sin schema
            raw=nxt,
            usage=TokenUsage(prompt_tokens=10, completion_tokens=20),
            latency_ms=1.0,
            model_alias=self.alias,
            cache_hit=False,
            finish_reason="stop",
        )

    def healthcheck(self) -> bool:
        return True


# ══════════════════════════════════════════════════════════════════════════════
#  Tests de los métodos individuales
# ══════════════════════════════════════════════════════════════════════════════


class TestSummarizeFragment:

    def test_returns_raw_stripped(self) -> None:
        backend = _FakeBackend(["  resumen del fragmento  "])
        agent = SummarizerAgent(backend)
        result = agent.summarize_fragment("texto largo")
        assert result == "resumen del fragmento"

    def test_no_schema_passed(self) -> None:
        backend = _FakeBackend(["x"])
        agent = SummarizerAgent(backend)
        agent.summarize_fragment("y")
        # Verifica explícitamente que no se manda schema.
        assert backend.calls[0]["schema"] is None

    def test_propagates_backend_error(self) -> None:
        backend = _FakeBackend([BackendTimeoutError("up")])
        agent = SummarizerAgent(backend)
        with pytest.raises(BackendTimeoutError):
            agent.summarize_fragment("texto")


class TestSummarizeGlobal:

    def test_joins_partials_with_index(self) -> None:
        backend = _FakeBackend(["resumen global"])
        agent = SummarizerAgent(backend)
        agent.summarize_global(
            titulo="Discurso X",
            fecha="2024-01-01",
            resumenes_parciales=["primero", "segundo", "tercero"],
        )
        user = backend.calls[0]["user"]
        # Verifica que los parciales aparezcan numerados [1] [2] [3].
        assert "[1] primero" in user
        assert "[2] segundo" in user
        assert "[3] tercero" in user

    def test_includes_titulo_and_fecha(self) -> None:
        backend = _FakeBackend(["x"])
        agent = SummarizerAgent(backend)
        agent.summarize_global(
            titulo="Discurso de Asunción",
            fecha="2024-12-10",
            resumenes_parciales=["a"],
        )
        user = backend.calls[0]["user"]
        assert "Discurso de Asunción" in user
        assert "2024-12-10" in user


# ══════════════════════════════════════════════════════════════════════════════
#  Tests del chunking
# ══════════════════════════════════════════════════════════════════════════════


class TestChunking:

    def test_short_text_one_chunk(self) -> None:
        text = "Un solo párrafo corto."
        chunks = _split_into_chunks(text, char_limit=1000)
        assert chunks == ["Un solo párrafo corto."]

    def test_multiple_paragraphs_grouped(self) -> None:
        text = "Párrafo uno.\n\nPárrafo dos.\n\nPárrafo tres."
        chunks = _split_into_chunks(text, char_limit=1000)
        # Todos juntos: cabe en un solo chunk.
        assert len(chunks) == 1
        assert "Párrafo uno." in chunks[0]
        assert "Párrafo tres." in chunks[0]

    def test_split_when_exceeds_limit(self) -> None:
        # Cada párrafo de ~50 chars; límite de 100 → ~2 chunks.
        p1 = "A" * 50
        p2 = "B" * 50
        p3 = "C" * 50
        text = f"{p1}\n\n{p2}\n\n{p3}"
        chunks = _split_into_chunks(text, char_limit=100)
        assert len(chunks) >= 2
        assert all(p1 in chunks[0] or p1 in chunks[1] for _ in [0])

    def test_empty_text_returns_empty_list(self) -> None:
        assert _split_into_chunks("", 1000) == []
        assert _split_into_chunks("   \n\n  ", 1000) == []

    def test_paragraph_larger_than_limit_split_by_sentences(self) -> None:
        """Un párrafo solo más grande que el límite se sub-divide por
        oraciones (vía split_into_sentences). Caso real: discursos
        scrapeados que vienen sin `\\n\\n` y forman un único "párrafo"
        gigante — si no se sub-dividieran, el chunk único excedería
        el contexto del modelo.
        """
        # Cinco oraciones de ~80 chars cada una, sin \n\n entre ellas:
        # son un solo párrafo grande para _split_into_chunks.
        oraciones = [
            "Esta es la primera oración con suficiente texto para llegar al objetivo.",
            "Esta es la segunda oración con suficiente texto para llegar al objetivo.",
            "Esta es la tercera oración con suficiente texto para llegar al objetivo.",
            "Esta es la cuarta oración con suficiente texto para llegar al objetivo.",
            "Esta es la quinta oración con suficiente texto para llegar al objetivo.",
        ]
        big = " ".join(oraciones)
        assert len(big) > 200  # sanity

        chunks = _split_into_chunks(big, char_limit=200)

        # Debe haberse partido en múltiples chunks (no uno solo gigante).
        assert len(chunks) > 1
        # Ningún chunk debe ser el párrafo entero.
        assert all(c != big for c in chunks)
        # Cada chunk respeta razonablemente el límite.
        for c in chunks:
            assert len(c) <= 400, f"chunk excede tolerancia: {len(c)} chars"

    def test_no_paragraph_breaks_splits_by_sentences(self) -> None:
        """Texto sin `\\n\\n` (caso del discurso de Milei en Expo EFI):
        debe partirse por oraciones, no devolver un único chunk gigante.
        """
        # Simular un discurso largo sin saltos de párrafo: una sola
        # línea con muchas oraciones.
        text = ". ".join(
            f"Oración número {i} con texto razonablemente largo para el test"
            for i in range(50)
        ) + "."
        assert "\n\n" not in text
        assert len(text) > 2000

        chunks = _split_into_chunks(text, char_limit=400)

        assert len(chunks) > 1
        for c in chunks:
            assert len(c) <= 600  # tolerancia razonable

    def test_extremely_long_unsplittable_text_falls_back(self) -> None:
        """Caso degenerado: texto largo sin puntuación final (split_into_sentences
        no puede partirlo). El fallback es preservar el texto como chunk único —
        se prefiere un chunk grande a perder contenido."""
        weird = "X" * 5000
        chunks = _split_into_chunks(weird, char_limit=1000)
        assert chunks
        assert "".join(chunks).replace("\n\n", "").count("X") == 5000


# ══════════════════════════════════════════════════════════════════════════════
#  Tests del run() completo
# ══════════════════════════════════════════════════════════════════════════════


class TestSummarizerRun:

    def test_single_chunk_skips_global_call(self) -> None:
        """Si hay un solo chunk, su resumen es el global (no llama dos veces)."""
        backend = _FakeBackend(["resumen único"])
        agent = SummarizerAgent(backend, chunk_char_limit=10000)
        df = pd.DataFrame([
            {"codigo": "A", "contenido": "Texto corto."},
        ])
        out = agent.run(df)

        # Una sola llamada (al fragmento).
        assert len(backend.calls) == 1
        # El global == el parcial.
        assert out.iloc[0]["resumen_global"] == "resumen único"
        # resumen_fragmentos es JSON list de 1 elemento.
        frags = json.loads(out.iloc[0]["resumen_fragmentos"])
        assert frags == ["resumen único"]

    def test_multiple_chunks_two_pass(self) -> None:
        """Múltiples chunks → N llamadas a fragmento + 1 global."""
        # Texto que se divide en 2 chunks con char_limit=50.
        text = ("Párrafo uno con texto suficiente para llegar al límite.\n\n"
                "Párrafo dos con texto suficiente para llegar al límite.\n\n"
                "Párrafo tres con texto suficiente para llegar al límite.")
        backend = _FakeBackend([
            "parcial 1",
            "parcial 2",
            "parcial 3",
            "global integrado",
        ])
        agent = SummarizerAgent(backend, chunk_char_limit=80)
        df = pd.DataFrame([
            {"codigo": "A", "contenido": text, "titulo": "T", "fecha": "F"},
        ])
        out = agent.run(df)

        # Las llamadas deben ser: fragmentos + 1 global.
        assert len(backend.calls) >= 3  # al menos los fragmentos
        assert out.iloc[0]["resumen_global"] == "global integrado"

        frags = json.loads(out.iloc[0]["resumen_fragmentos"])
        assert "parcial 1" in frags
        assert "parcial 2" in frags

    def test_uses_precomputed_chunks_column(self) -> None:
        """Si la columna 'chunks' existe, se usa esa en lugar de partir."""
        backend = _FakeBackend(["r1", "r2", "global"])
        agent = SummarizerAgent(backend)
        df = pd.DataFrame([
            {
                "codigo": "A",
                "contenido": "ignorado",
                "chunks": json.dumps(["chunk uno", "chunk dos"]),
                "titulo": "T",
                "fecha": "F",
            },
        ])
        out = agent.run(df)

        # Debe haber llamado: 2 fragmentos + 1 global = 3.
        assert len(backend.calls) == 3
        # Y los fragmentos deben provenir de la columna chunks.
        frags = json.loads(out.iloc[0]["resumen_fragmentos"])
        assert frags == ["r1", "r2"]

    def test_empty_content_marks_none(self) -> None:
        """Discurso sin contenido → ambos campos en None, sin crashear."""
        backend = _FakeBackend([])
        agent = SummarizerAgent(backend)
        df = pd.DataFrame([{"codigo": "A", "contenido": ""}])
        out = agent.run(df)

        assert pd.isna(out.iloc[0]["resumen_fragmentos"])
        assert pd.isna(out.iloc[0]["resumen_global"])
        assert backend.calls == []

    def test_error_in_one_discurso_does_not_break_others(self) -> None:
        """Si el LLM falla en un discurso, el siguiente se procesa normal."""
        backend = _FakeBackend([
            BackendTimeoutError("simulated"),  # primer fragmento del primer discurso
            "resumen B",  # primer fragmento del segundo discurso
        ])
        agent = SummarizerAgent(backend, chunk_char_limit=10000)
        df = pd.DataFrame([
            {"codigo": "A", "contenido": "Texto A."},
            {"codigo": "B", "contenido": "Texto B."},
        ])
        out = agent.run(df)

        # Discurso A: failed.
        assert pd.isna(out.iloc[0]["resumen_fragmentos"])
        assert pd.isna(out.iloc[0]["resumen_global"])
        # Discurso B: ok.
        assert out.iloc[1]["resumen_global"] == "resumen B"

    def test_empty_df_returns_with_columns(self) -> None:
        backend = _FakeBackend([])
        agent = SummarizerAgent(backend)
        out = agent.run(pd.DataFrame(columns=["codigo"]))
        for col in SummarizerAgent.OUTPUT_COLUMNS:
            assert col in out.columns
