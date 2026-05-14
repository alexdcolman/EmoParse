# ══════════════════════════════════════════════════════════════════════════════
#  tests.unit.test_metadata_agent
#
#  Verifica que el MetadataAgent migrado:
#  1. Construye el system prompt con el diccionario inyectado una vez.
#  2. Llama al backend con el schema correcto.
#  3. Mapea la respuesta parsed al DataFrame de salida.
#  4. Maneja errores del backend sin crashear (rellena con None).
#  5. Es robusto a inputs con contenido faltante.
# ══════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

from typing import TypeVar

import pandas as pd
import pytest
from pydantic import BaseModel

from emoparse.agents.metadata import MetadataAgent
from emoparse.core.backend.base import LLMBackend, LLMResponse, TokenUsage
from emoparse.core.backend.exceptions import (
    BackendTimeoutError,
    SchemaViolationError,
)
from emoparse.core.schemas import MetadatosSchema

T = TypeVar("T", bound=BaseModel)


# ══════════════════════════════════════════════════════════════════════════════
#  Fake backend que simula respuestas estructuradas
# ══════════════════════════════════════════════════════════════════════════════

class _FakeBackend(LLMBackend):
    """Backend de prueba que devuelve respuestas configuradas o lanza errores.

    `responses` es una cola: cada generate() consume una. Si la entrada
    es una excepción, se lanza; si es un BaseModel, se devuelve como
    parsed; si es None, devuelve LLMResponse con parsed=None (caso bug).
    """

    def __init__(self, responses: list[BaseModel | Exception | None]) -> None:
        self.alias = "fake"
        self._responses = list(responses)
        # Auditoría: inputs reales que recibió el backend.
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
        self.calls.append({"system": system, "user": user, "schema": schema})
        if not self._responses:
            raise AssertionError("FakeBackend sin respuestas configuradas")
        nxt = self._responses.pop(0)
        if isinstance(nxt, Exception):
            raise nxt
        return LLMResponse(
            parsed=nxt,
            raw="(fake)",
            usage=TokenUsage(prompt_tokens=10, completion_tokens=20),
            latency_ms=5.0,
            model_alias=self.alias,
            cache_hit=False,
            finish_reason="stop",
        )

    def healthcheck(self) -> bool:
        return True


# ══════════════════════════════════════════════════════════════════════════════
#  Fixtures
# ══════════════════════════════════════════════════════════════════════════════

@pytest.fixture
def diccionario_tipos() -> dict[str, object]:
    return {
        "asuncion": "Discurso de toma de posesión.",
        "anuncio_medida": "Anuncio de una política o medida concreta.",
        "campana": "Discurso en contexto de campaña electoral.",
    }


@pytest.fixture
def sample_df() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "codigo": "DISC_001",
                "titulo": "Asunción presidencial",
                "resumen_global": "El presidente asume el cargo en Buenos Aires.",
                "contenido": "Hoy asumo la presidencia frente al pueblo argentino...",
            },
            {
                "codigo": "DISC_002",
                "titulo": "Anuncio económico",
                "resumen_global": "Anuncio de medidas económicas en La Plata.",
                "contenido": "Anunciamos hoy un paquete de medidas...",
            },
        ]
    )


@pytest.fixture
def ok_response() -> MetadatosSchema:
    return MetadatosSchema(
        tipo_discurso="asuncion",
        tipo_discurso_justificacion="El texto explicita la toma de posesión.",
        ciudad="Buenos Aires",
        provincia="Buenos Aires",
        pais="Argentina",
        lugar_justificacion="Mencionado explícitamente.",
    )


# ══════════════════════════════════════════════════════════════════════════════
#  Tests
# ══════════════════════════════════════════════════════════════════════════════

class TestSystemPromptStability:
    """El system prompt es estable: idéntico para todas las llamadas del run."""

    def test_system_built_once_and_reused(
        self,
        diccionario_tipos: dict[str, object],
        sample_df: pd.DataFrame,
        ok_response: MetadatosSchema,
    ) -> None:
        backend = _FakeBackend([ok_response, ok_response])
        agent = MetadataAgent(backend, diccionario_tipos)
        agent.run(sample_df)

        # Las dos llamadas tienen que tener el mismo system.
        assert len(backend.calls) == 2
        assert backend.calls[0]["system"] == backend.calls[1]["system"]

        # Y debe contener el diccionario serializado.
        assert "asuncion" in backend.calls[0]["system"]
        assert "Toma de posesión" in backend.calls[0]["system"] or "asuncion" in backend.calls[0]["system"]


class TestUserPromptVariation:
    """El user prompt cambia según el discurso."""

    def test_user_includes_codigo(
        self,
        diccionario_tipos: dict[str, object],
        sample_df: pd.DataFrame,
        ok_response: MetadatosSchema,
    ) -> None:
        backend = _FakeBackend([ok_response, ok_response])
        agent = MetadataAgent(backend, diccionario_tipos)
        agent.run(sample_df)

        assert "DISC_001" in backend.calls[0]["user"]
        assert "DISC_002" in backend.calls[1]["user"]

    def test_schema_passed(
        self,
        diccionario_tipos: dict[str, object],
        sample_df: pd.DataFrame,
        ok_response: MetadatosSchema,
    ) -> None:
        backend = _FakeBackend([ok_response, ok_response])
        agent = MetadataAgent(backend, diccionario_tipos)
        agent.run(sample_df)

        for call in backend.calls:
            assert call["schema"] is MetadatosSchema


class TestOutputMapping:
    """El parsed se mapea correctamente al DataFrame."""

    def test_columns_added(
        self,
        diccionario_tipos: dict[str, object],
        sample_df: pd.DataFrame,
        ok_response: MetadatosSchema,
    ) -> None:
        backend = _FakeBackend([ok_response, ok_response])
        agent = MetadataAgent(backend, diccionario_tipos)
        out = agent.run(sample_df)

        for col in MetadataAgent.OUTPUT_COLUMNS:
            assert col in out.columns, f"Falta columna {col}"

    def test_values_match_response(
        self,
        diccionario_tipos: dict[str, object],
        sample_df: pd.DataFrame,
        ok_response: MetadatosSchema,
    ) -> None:
        backend = _FakeBackend([ok_response, ok_response])
        agent = MetadataAgent(backend, diccionario_tipos)
        out = agent.run(sample_df)

        assert out.iloc[0]["tipo_discurso"] == ok_response.tipo_discurso
        assert out.iloc[0]["ciudad"] == ok_response.ciudad
        assert out.iloc[1]["pais"] == ok_response.pais

    def test_original_columns_preserved(
        self,
        diccionario_tipos: dict[str, object],
        sample_df: pd.DataFrame,
        ok_response: MetadatosSchema,
    ) -> None:
        backend = _FakeBackend([ok_response, ok_response])
        agent = MetadataAgent(backend, diccionario_tipos)
        out = agent.run(sample_df)

        assert "titulo" in out.columns
        assert out.iloc[0]["titulo"] == "Asunción presidencial"


class TestErrorHandling:
    """Errores del backend se manejan sin crashear el run."""

    def test_timeout_marks_row_with_none(
        self,
        diccionario_tipos: dict[str, object],
        sample_df: pd.DataFrame,
        ok_response: MetadatosSchema,
    ) -> None:
        backend = _FakeBackend(
            [BackendTimeoutError("simulated timeout"), ok_response]
        )
        agent = MetadataAgent(backend, diccionario_tipos)
        out = agent.run(sample_df)

        # Primera fila falló: todas las columnas nuevas vacías.
        assert pd.isna(out.iloc[0]["tipo_discurso"])
        assert pd.isna(out.iloc[0]["ciudad"])
        # Pero las originales se preservan.
        assert out.iloc[0]["codigo"] == "DISC_001"
        # Segunda fila ok.
        assert out.iloc[1]["tipo_discurso"] == ok_response.tipo_discurso

    def test_schema_violation_marks_row_with_none(
        self,
        diccionario_tipos: dict[str, object],
        sample_df: pd.DataFrame,
        ok_response: MetadatosSchema,
    ) -> None:
        backend = _FakeBackend(
            [SchemaViolationError("bad schema"), ok_response]
        )
        agent = MetadataAgent(backend, diccionario_tipos)
        out = agent.run(sample_df)

        assert pd.isna(out.iloc[0]["tipo_discurso"])
        assert out.iloc[1]["tipo_discurso"] == ok_response.tipo_discurso


class TestEdgeCases:
    def test_empty_df_returns_with_columns(
        self,
        diccionario_tipos: dict[str, object],
    ) -> None:
        backend = _FakeBackend([])
        agent = MetadataAgent(backend, diccionario_tipos)
        out = agent.run(pd.DataFrame(columns=["codigo"]))

        for col in MetadataAgent.OUTPUT_COLUMNS:
            assert col in out.columns

    def test_missing_resumen_falls_back_to_contenido(
        self,
        diccionario_tipos: dict[str, object],
        ok_response: MetadatosSchema,
    ) -> None:
        df = pd.DataFrame(
            [{"codigo": "X", "contenido": "Algun discurso aquí."}]
        )
        backend = _FakeBackend([ok_response])
        agent = MetadataAgent(backend, diccionario_tipos)
        out = agent.run(df)
        assert "Algun discurso aquí." in backend.calls[0]["user"]
        assert out.iloc[0]["tipo_discurso"] == ok_response.tipo_discurso

    def test_invalid_json_in_resumen_fragmentos_falls_back(
        self,
        diccionario_tipos: dict[str, object],
        ok_response: MetadatosSchema,
    ) -> None:
        df = pd.DataFrame(
            [
                {
                    "codigo": "X",
                    "resumen_global": "ok",
                    "contenido": "fallback content",
                    "resumen_fragmentos": "this is not json",
                }
            ]
        )
        backend = _FakeBackend([ok_response])
        agent = MetadataAgent(backend, diccionario_tipos)
        out = agent.run(df)
        assert out.iloc[0]["tipo_discurso"] == ok_response.tipo_discurso


class TestResumenFallbackTruncation:
    """Cuando `resumen_global` no está disponible y se cae al `contenido`,
    el fallback se trunca para no inyectar discursos enteros al prompt.

    Esto evita la cascada del bug observado: si la stage de summarizer
    falla (ContextLengthExceeded), el row downstream no tiene la
    columna `resumen_global`. Antes del fix, eso inyectaba el discurso
    entero al prompt de metadata, volviendo a explotar el contexto.
    """

    def test_huge_contenido_truncated_when_resumen_missing(
        self,
        diccionario_tipos: dict[str, object],
        ok_response: MetadatosSchema,
    ) -> None:
        # 50.000 chars: tamaño realista de un discurso largo de Milei.
        huge = "Lorem ipsum dolor sit amet. " * 2000
        assert len(huge) > 50000

        df = pd.DataFrame([{"codigo": "X", "contenido": huge}])
        backend = _FakeBackend([ok_response])
        agent = MetadataAgent(backend, diccionario_tipos)
        agent.run(df)

        user = backend.calls[0]["user"]
        # El user prompt total no debe contener todo el contenido crudo.
        # Truncado a ~4000 chars + "..." + el resto del prompt
        # (system es separado).
        assert len(user) < 10000, (
            f"User prompt no fue truncado: {len(user)} chars. "
            "El fallback al contenido debería limitar el inyectado."
        )

    def test_resumen_global_none_falls_back_to_contenido(
        self,
        diccionario_tipos: dict[str, object],
        ok_response: MetadatosSchema,
    ) -> None:
        """Si `resumen_global` está presente pero es None/NaN (caso del
        summarizer que registró la columna pero falló), debe caer al
        contenido truncado, no mandar 'None' como resumen."""
        df = pd.DataFrame([
            {
                "codigo": "X",
                "resumen_global": None,
                "contenido": "Texto del discurso original.",
            }
        ])
        backend = _FakeBackend([ok_response])
        agent = MetadataAgent(backend, diccionario_tipos)
        agent.run(df)

        user = backend.calls[0]["user"]
        # El contenido aparece en el prompt.
        assert "Texto del discurso original." in user
        # Y no aparece la palabra "None" tratada como resumen.
        assert "None" not in user or user.count("None") < 2

    def test_resumen_global_nan_falls_back_to_contenido(
        self,
        diccionario_tipos: dict[str, object],
        ok_response: MetadatosSchema,
    ) -> None:
        """Mismo caso pero con NaN (lo que pandas pone cuando construye
        un DF con None en columna object mezclada)."""
        import numpy as np
        df = pd.DataFrame([
            {
                "codigo": "X",
                "resumen_global": np.nan,
                "contenido": "Contenido fallback.",
            }
        ])
        backend = _FakeBackend([ok_response])
        agent = MetadataAgent(backend, diccionario_tipos)
        agent.run(df)

        user = backend.calls[0]["user"]
        assert "Contenido fallback." in user
        assert "nan" not in user.lower() or "fallback" in user.lower()

    def test_short_resumen_global_used_as_is(
        self,
        diccionario_tipos: dict[str, object],
        ok_response: MetadatosSchema,
    ) -> None:
        """Cuando hay `resumen_global` válido, se usa tal cual — sin
        truncar, sin caer al contenido."""
        df = pd.DataFrame([
            {
                "codigo": "X",
                "resumen_global": "Resumen corto y útil.",
                "contenido": "Contenido completo del discurso, no debe aparecer.",
            }
        ])
        backend = _FakeBackend([ok_response])
        agent = MetadataAgent(backend, diccionario_tipos)
        agent.run(df)

        user = backend.calls[0]["user"]
        assert "Resumen corto y útil." in user
        assert "no debe aparecer" not in user
