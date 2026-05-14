# ══════════════════════════════════════════════════════════════════════════════
#  tests.integration.test_backend_llamacpp
#
#  Tests de integración del LlamaCppBackend con un GGUF real (phi-4-mini).
#
#  Estos tests:
#   - SE EJECUTAN automáticamente si phi-4-mini está disponible en models/.
#   - SE SALTEAN limpiamente si no (no son fallos, son skips).
#   - Verifican el comportamiento end-to-end: chat template aplicado,
#     gramática GBNF efectiva, idempotencia con seed, métricas pobladas.
#
#  El modelo se carga UNA SOLA VEZ por sesión de pytest (fixture
#  session-scoped) para no pagar el costo de carga en cada test.
#  Esto significa que los tests COMPARTEN estado del backend, así que
#  cada test debe ser independiente del orden en que se ejecuten.
#
#  Ejecución:
#       pytest tests/integration/test_backend_llamacpp.py -v
#       pytest -m integration -v          (solo integration)
#       pytest -m "not integration"       (saltea estos)
# ══════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

from typing import Any

import pytest

from emoparse.core.backend.base import LLMResponse
from emoparse.core.backend.llamacpp import LlamaCppBackend
from emoparse.core.schemas import MetadatosSchema

# Marker que aplica a TODOS los tests de este archivo.
# Cumple doble función: documenta intención y permite filtrar.
pytestmark = pytest.mark.integration


# ══════════════════════════════════════════════════════════════════════════════
#  Fixtures locales (la del modelo está en conftest.py)
# ══════════════════════════════════════════════════════════════════════════════

@pytest.fixture(scope="module")
def backend(phi4_mini_config: dict[str, Any]) -> LlamaCppBackend:
    """Backend cargado UNA VEZ por módulo de tests.

    Module-scoped en lugar de session-scoped: si tenemos varios módulos
    de integration con phi-4-mini, cada uno carga su instancia. Esto es
    a propósito — evita acoplar tests entre módulos vía estado del
    backend (caches de gramáticas, etc.).
    """
    b = LlamaCppBackend(alias="phi4-mini-test", model_config=phi4_mini_config)
    yield b
    b.close()


@pytest.fixture
def diccionario_str() -> str:
    """Diccionario mínimo de tipos de discurso, formateado como string."""
    return (
        "asuncion: Discurso de toma de posesión.\n"
        "anuncio_medida: Anuncio de una política o medida concreta.\n"
        "campana: Discurso en contexto de campaña electoral."
    )


@pytest.fixture
def discurso_test() -> dict[str, str]:
    """Discurso de prueba corto. Diseñado para ser inequívocamente
    una asunción en Buenos Aires, así los asserts pueden ser fuertes
    sin depender de capacidad de razonamiento del modelo."""
    return {
        "codigo": "TEST_001",
        "resumen": (
            "Discurso de asunción presidencial pronunciado en la Casa Rosada, "
            "Buenos Aires, Argentina. El presidente toma posesión del cargo "
            "frente al Congreso de la Nación."
        ),
        "fragmentos": (
            "- Hoy asumo la presidencia de la Nación Argentina.\n"
            "- Desde esta Casa Rosada, en el corazón de Buenos Aires, "
            "comenzamos una nueva etapa.\n"
            "- Juro por Dios y la Patria desempeñar con lealtad este cargo."
        ),
    }


# ══════════════════════════════════════════════════════════════════════════════
#  Test 1 — Health check no se cuelga ni lanza
# ══════════════════════════════════════════════════════════════════════════════

class TestHealthcheck:
    def test_healthcheck_returns_true_on_loaded_model(
        self,
        backend: LlamaCppBackend,
    ) -> None:
        """El healthcheck debe devolver True con un modelo recién cargado.

        Un False acá indicaría un bug en cómo construimos messages/params
        en la implementación de healthcheck (no en la calidad del modelo).
        """
        assert backend.healthcheck() is True


# ══════════════════════════════════════════════════════════════════════════════
#  Test 2 — Generación con schema produce Pydantic válido
# ══════════════════════════════════════════════════════════════════════════════

class TestStructuredGeneration:
    """La cadena completa: chat template + GBNF + parseo Pydantic."""

    def test_generate_with_schema_returns_valid_pydantic(
        self,
        backend: LlamaCppBackend,
        diccionario_str: str,
        discurso_test: dict[str, str],
    ) -> None:
        """`response.parsed` debe ser una instancia válida del schema."""
        system = (
            "Sos un analista de discurso. Identificá tipo de discurso y lugar.\n"
            "Diccionario:\n" + diccionario_str
        )
        user = (
            f"CÓDIGO: {discurso_test['codigo']}\n"
            f"RESUMEN: {discurso_test['resumen']}\n"
            f"FRAGMENTOS:\n{discurso_test['fragmentos']}"
        )
        response = backend.generate(
            system=system,
            user=user,
            schema=MetadatosSchema,
        )

        # ── Asserts estructurales (qué garantiza GBNF) ──────────────────
        assert isinstance(response, LLMResponse)
        assert isinstance(response.parsed, MetadatosSchema), (
            f"parsed no es MetadatosSchema: type={type(response.parsed).__name__} "
            f"raw={response.raw[:200]!r}"
        )
        # Todos los campos requeridos llenos (no string vacío).
        assert response.parsed.tipo_discurso.strip() != ""
        assert response.parsed.tipo_discurso_justificacion.strip() != ""
        assert response.parsed.ciudad.strip() != ""
        assert response.parsed.provincia.strip() != ""
        assert response.parsed.pais.strip() != ""
        assert response.parsed.lugar_justificacion.strip() != ""

        # ── Asserts de telemetría ───────────────────────────────────────
        # finish_reason "stop" es lo esperado; "length" indicaría que
        # max_tokens fue muy bajo y el JSON quedó truncado (en cuyo caso
        # el LlamaCppBackend ya habría lanzado ContextLengthExceededError,
        # así que llegar acá significa stop).
        assert response.finish_reason == "stop", (
            f"finish_reason inesperado: {response.finish_reason}"
        )
        assert response.usage.completion_tokens > 0
        assert response.usage.prompt_tokens > 0
        assert response.latency_ms > 0
        assert response.cache_hit is False  # no cache en este path
        assert response.model_alias == "phi4-mini-test"

    def test_generate_without_schema_returns_text(
        self,
        backend: LlamaCppBackend,
    ) -> None:
        """Sin schema, parsed=None y raw es texto libre."""
        response = backend.generate(
            system="Respondé con una sola palabra.",
            user="Capital de Francia?",
            max_tokens=20,
        )
        assert response.parsed is None
        assert isinstance(response.raw, str)
        assert response.raw.strip() != ""


# ══════════════════════════════════════════════════════════════════════════════
#  Test 3 — Determinismo con seed
#
#  Crítico: si esto falla, hay no-determinismo en algún lado del stack
#  (sampler, KV-cache compartido, threading) y es fundamental detectarlo
#  ANTES de armar tests downstream que dependan de outputs estables.
# ══════════════════════════════════════════════════════════════════════════════

class TestDeterminism:
    """Misma seed + mismo prompt + mismo schema → misma salida bit a bit
    cuando se pide reset explícito del estado del backend.
    """

    def test_same_seed_with_reset_produces_identical_raw(
        self,
        backend: LlamaCppBackend,
        diccionario_str: str,
        discurso_test: dict[str, str],
    ) -> None:
        """Dos llamadas con misma seed + reset_before=True → raw idéntico.

        La garantía de determinismo bit-a-bit del backend es CONDICIONAL
        a `reset_before=True`. Sin reset, el KV-cache acumulado entre
        llamadas puede generar pequeñas divergencias en la distribución
        del primer token (especialmente con prompts largos compartiendo
        prefijo). Con reset, ambas llamadas parten del mismo estado
        interno y producen exactamente los mismos tokens.

        Si este test falla, indica un bug serio en el determinismo del
        backend: hay alguna fuente de no-determinismo que reset() no
        cubre (ej: threading no determinístico, sampling con randomness
        externa al seed). En ese caso hay que investigar antes de
        confiar en el caching de respuestas.
        """
        system = "Sos un analista de discurso.\n" + diccionario_str
        user = (
            f"CÓDIGO: {discurso_test['codigo']}\n"
            f"RESUMEN: {discurso_test['resumen']}"
        )
        kwargs: dict[str, Any] = dict(
            system=system,
            user=user,
            schema=MetadatosSchema,
            temperature=0.0,
            seed=42,
            reset_before=True,
        )
        r1 = backend.generate(**kwargs)
        r2 = backend.generate(**kwargs)

        assert r1.raw == r2.raw, (
            "Misma seed + reset_before=True produjo outputs distintos. "
            "Esto NO debería pasar y sugiere no-determinismo en el "
            "backend que reset() no cubre. Diff:\n"
            f"  r1: {r1.raw[:200]!r}\n  r2: {r2.raw[:200]!r}"
        )

    def test_different_seed_produces_different_raw(
        self,
        backend: LlamaCppBackend,
        diccionario_str: str,
        discurso_test: dict[str, str],
    ) -> None:
        """Seeds distintas con temp>0 producen outputs distintos.

        Con temperature=0.0 (greedy), cambiar la seed NO cambia el output
        porque no hay sampling random — siempre se elige el token de
        máxima probabilidad. Por eso este test usa temp=0.7.

        Si este test fallara, indicaría que la seed no se está propagando
        al sampler (bug grave: invalidaría el test anterior por trivialidad).
        """
        system = "Escribí una historia corta de exactamente 3 oraciones."
        user = "Tema: un viaje en tren."
        # Sin schema: queremos texto libre, hay margen para variación.
        # reset_before=True para aislar el efecto de la seed del estado
        # acumulado del KV-cache.
        r1 = backend.generate(
            system=system, user=user, temperature=0.7, seed=1,
            max_tokens=200, reset_before=True,
        )
        r2 = backend.generate(
            system=system, user=user, temperature=0.7, seed=999,
            max_tokens=200, reset_before=True,
        )

        # No exigimos que sean RADICALMENTE distintos, solo que difieran.
        # El espacio de salidas con temp=0.7 es enorme; coincidir bit a
        # bit con seeds distintas requeriría que la seed no esté siendo
        # aplicada.
        assert r1.raw != r2.raw, (
            "Seeds distintas produjeron output idéntico — "
            "la seed no se está propagando al sampler."
        )


# ══════════════════════════════════════════════════════════════════════════════
#  Test 4 — Chat template aplicado (sanity check del bug del v1)
#
#  Este test es un proxy: detecta el caso "el modelo ignora el system
#  prompt completamente", que es lo que pasa si el chat template del
#  GGUF no se está aplicando.
# ══════════════════════════════════════════════════════════════════════════════

class TestChatTemplate:
    """Verificación indirecta de que el chat template del GGUF se aplica."""

    def test_system_prompt_is_respected(
        self,
        backend: LlamaCppBackend,
    ) -> None:
        """Si el system instruye fuertemente, la respuesta debe respetarlo.

        Con chat template aplicado, phi-4-mini sigue instrucciones de
        sistema con alta consistencia. Sin chat template (bug del v1
        que estamos arreglando), el modelo ve un blob de texto sin
        delimitadores y ignora el rol.

        Usamos una instrucción extrema: "responde solo con OK". Con temp=0
        y la cadena bien aplicada, la respuesta arranca con OK.

        Es un test imperfecto — el modelo podría desobedecer aunque la
        cadena esté bien — pero detecta el caso patológico de "system
        completamente ignorado", que es el bug que importa.
        """
        response = backend.generate(
            system='Respondé únicamente con la palabra "OK". Nada más.',
            user="hola",
            temperature=0.0,
            max_tokens=10,
        )
        # Comparación tolerante: el modelo puede agregar puntuación o
        # whitespace, pero el primer token alfabético debería ser OK.
        first_word = response.raw.strip().split()[0] if response.raw.strip() else ""
        # Limpiar puntuación común.
        first_word_clean = first_word.strip(".,!?\"'`").upper()
        assert first_word_clean == "OK", (
            f"El modelo no respetó el system. raw={response.raw[:200]!r}. "
            "Posible causa: chat template no aplicado."
        )
