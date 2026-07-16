# ══════════════════════════════════════════════════════════════════════════════
#  emoparse.core.backend.llamacpp
#
#  Backend para modelos GGUF locales vía llama-cpp-python.
#
#  Soporta generación estructurada (GBNF), aplicación de chat templates,
#  configuración de seed/temperatura, errores tipados y métricas en LLMResponse.
# ══════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any, TypeVar

from loguru import logger
from pydantic import BaseModel, ValidationError

from emoparse.core.backend.base import (
    FinishReason,
    LLMBackend,
    LLMResponse,
    TokenUsage,
)
from emoparse.core.backend.exceptions import (
    BackendConfigError,
    BackendError,
    ContextLengthExceededError,
    SchemaViolationError,
)
from emoparse.core.grammar import GrammarError, schema_to_gbnf

if TYPE_CHECKING:
    # Solo se importa al chequear tipos.
    from llama_cpp import Llama, LlamaGrammar

T = TypeVar("T", bound=BaseModel)

#: Defaults de temperatura, max_tokens y seed; config puede override.
_DEFAULT_TEMPERATURE = 0.0
_DEFAULT_MAX_TOKENS = 2048
_DEFAULT_SEED = 42


class LlamaCppBackend(LLMBackend):
    """Backend llama.cpp para GGUFs locales con generación estructurada.

    Usa caché de gramáticas GBNF compiladas.
    """

    def __init__(
            self,
            alias: str,
            model_config: dict[str, Any],
            *,
            verbose: bool = False,
        ) -> None:
            try:
                from llama_cpp import Llama, llama_supports_gpu_offload
            except ImportError as e:
                raise BackendConfigError(
                    "llama-cpp-python no está instalado. "
                    "Instalar con: CMAKE_ARGS='-DGGML_CUDA=on' pip install llama-cpp-python"
                ) from e

            self.alias = alias
            self._cfg = dict(model_config)  # copia del config

            path = self._cfg.get("path")
            if not path:
                raise BackendConfigError(f"Modelo '{alias}' sin 'path' en config")

            # Guard anti-fallback silencioso a CPU: si el config pide GPU
            # (n_gpu_layers != 0) pero el build de llama-cpp-python es CPU-only,
            # fallar con un mensaje claro. El modo CPU intencional se pide con
            # n_gpu_layers: 0.
            n_gpu_layers = self._cfg.get("n_gpu_layers", -1)
            if n_gpu_layers != 0 and not llama_supports_gpu_offload():
                raise BackendConfigError(
                    f"Modelo '{alias}' pide GPU (n_gpu_layers={n_gpu_layers}) pero el "
                    "build instalado de llama-cpp-python es CPU-only "
                    "(llama_supports_gpu_offload()=False).\n"
                    "  • Para GPU: reinstalá con CUDA, p. ej.\n"
                    "      CMAKE_ARGS='-DGGML_CUDA=on' pip install -e '.[llamacpp]' "
                    "--no-binary llama-cpp-python\n"
                    f"  • Para correr en CPU a propósito: poné 'n_gpu_layers: 0' en "
                    f"el config del modelo '{alias}'."
                )

            # Defaults del modelo (overridable por llamada).
            self._default_max_tokens = self._cfg.get("max_tokens", _DEFAULT_MAX_TOKENS)
            self._default_temperature = self._cfg.get("temperature", _DEFAULT_TEMPERATURE)
            self._default_seed = self._cfg.get("seed", _DEFAULT_SEED)

            # Parámetros de sampling avanzados.
            self._top_p = self._cfg.get("top_p", 1.0)
            self._top_k = self._cfg.get("top_k", 40)
            self._min_p = self._cfg.get("min_p", 0.0)
            self._repeat_penalty = self._cfg.get("repeat_penalty", 1.0)
            self._no_think = bool(self._cfg.get("no_think", False))

            # Cache de gramáticas compiladas; se limpia al descargar backend.
            self._grammar_cache: dict[str, LlamaGrammar] = {}

            logger.info(f"[LlamaCpp:{alias}] Cargando modelo: {path}")

            # Seed en constructor para determinismo; reproducible entre runs.
            self._llm: Llama = Llama(
                model_path=path,
                n_gpu_layers=n_gpu_layers,
                n_ctx=self._cfg.get("context_length", 8192),
                n_batch=self._cfg.get("n_batch", 512),
                n_threads=self._cfg.get("n_threads", None),
                n_keep=self._cfg.get("n_keep", 0),
                seed=self._default_seed,
                flash_attn=self._cfg.get("flash_attn", False),
                verbose=verbose,
            )
            logger.info(
                f"[LlamaCpp:{alias}] Modelo cargado | n_ctx={self._cfg.get('context_length', 8192)}"
            )

    # ── Health check ─────────────────────────────────────────────────────────

    def healthcheck(self) -> bool:
        """Verifica el modelo con una llamada mínima."""
        try:
            self._llm.create_chat_completion(
                messages=[{"role": "user", "content": "ok"}],
                max_tokens=1,
                temperature=0.0,
            )
            return True
        except Exception as e:
            logger.warning(f"[LlamaCpp:{self.alias}] Healthcheck falló: {e}")
            return False

    # ── Generación principal ─────────────────────────────────────────────────

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
        max_items: int | None = None,
        images: list[str] | None = None,
    ) -> LLMResponse:
        if images:
            raise BackendError(
                f"El backend in-process '{self.alias}' no soporta imágenes. "
                "Usá un modelo multimodal vía backend llama_server "
                "(llama-server --mmproj ...)."
            )
        # Reset opcional del KV-cache antes de resolver parámetros y
        # construir prompts.
        if reset_before:
            self.reset_state()

        # Resolver parámetros con defaults del modelo.
        eff_max_tokens = max_tokens if max_tokens is not None else self._default_max_tokens
        eff_temp = temperature if temperature is not None else self._default_temperature
        eff_seed = seed if seed is not None else self._default_seed

        # Construir mensajes de chat; template se aplica desde GGUF.
        # Switch suave de Qwen3: saltea la fase de razonamiento para evitar problemas con GBNF.
        sys_content = system
        if self._no_think:
            sys_content = f"{sys_content}\n\n/no_think" if sys_content else "/no_think"

        messages: list[dict[str, str]] = []
        if sys_content:
            messages.append({"role": "system", "content": sys_content})
        messages.append({"role": "user", "content": user})

        # Resolver gramática (si hay schema). `max_items` acota el array
        # top-level de los schemas de batch al tamaño real del batch.
        grammar = (
            self._get_grammar(schema, max_items) if schema is not None else None
        )

        kwargs: dict[str, Any] = {
            "messages": messages,
            "max_tokens": eff_max_tokens,
            "temperature": eff_temp,
            "top_p": self._top_p,
            "top_k": self._top_k,
            "min_p": self._min_p,
            "repeat_penalty": self._repeat_penalty,
            "seed": eff_seed,
        }
        if grammar is not None:
            kwargs["grammar"] = grammar
        if stop:
            kwargs["stop"] = stop

        # Inferencia.
        t_start = time.perf_counter()
        try:
            output = self._llm.create_chat_completion(**kwargs)
        except Exception as e:
            # Errores de contexto llegan como ValueError con mensaje específico.
            msg = str(e).lower()
            if "context" in msg and ("exceed" in msg or "too" in msg or "length" in msg):
                raise ContextLengthExceededError(
                    context_length=self._cfg.get("context_length"),
                    max_tokens=eff_max_tokens,
                ) from e
            raise BackendError(f"llama.cpp inference error: {e}") from e
        latency_ms = (time.perf_counter() - t_start) * 1000.0

        # Extraer contenido.
        choice = output["choices"][0]
        raw = choice["message"]["content"]
        finish_raw = choice.get("finish_reason", "stop")

        # Mapear finish_reason: "stop", "length" o None.
        finish: FinishReason
        if finish_raw == "length":
            finish = "length"
        elif finish_raw is None or finish_raw == "stop":
            finish = "stop"
        else:
            finish = "error"

        # Con schema y truncado: prompt demasiado largo o max_tokens
        # insuficiente; no recuperable.
        if schema is not None and finish == "length":
            # Log para diagnosticar errores de longitud de distintos modelos (dejar si se
            # prueban GGUFs nuevos o se ajustan context_length/max_tokens).
            logger.error("[{}] finish=length | tail(raw)={!r}", self.alias, raw[-400:])
            raise ContextLengthExceededError(
                context_length=self._cfg.get("context_length"),
                max_tokens=eff_max_tokens,
            )

        # Token usage. llama.cpp expone esto en `usage`.
        usage_dict = output.get("usage", {})
        usage = TokenUsage(
            prompt_tokens=usage_dict.get("prompt_tokens", 0),
            completion_tokens=usage_dict.get("completion_tokens", 0),
        )

        # Parseo Pydantic; con GBNF no debería fallar.
        parsed: BaseModel | None = None
        if schema is not None:
            try:
                parsed = schema.model_validate_json(raw)
            except ValidationError as e:
                # Bug del converter Pydantic→GBNF; no recuperable.
                raise SchemaViolationError(
                    f"GBNF produjo JSON que no valida contra {schema.__name__}: {e}\n"
                    f"raw={raw[:300]!r}"
                ) from e

        return LLMResponse(
            parsed=parsed,
            raw=raw,
            usage=usage,
            latency_ms=latency_ms,
            model_alias=self.alias,
            cache_hit=False,
            finish_reason=finish,
        )

    # ── Cache de gramáticas compiladas ───────────────────────────────────────

    def _get_grammar(
        self,
        schema: type[BaseModel],
        max_items: int | None = None,
    ) -> LlamaGrammar:
        """Devuelve (o compila) la gramática GBNF para `schema`.

        `max_items` (tamaño del batch) forma parte de la clave de caché: cada
        tamaño produce una gramática con el array top-level acotado a ese número.
        """
        from llama_cpp import LlamaGrammar

        key = f"{schema.__module__}.{schema.__qualname__}|n={max_items}"
        cached = self._grammar_cache.get(key)
        if cached is not None:
            return cached
        try:
            gbnf = schema_to_gbnf(schema, max_items=max_items)
        except GrammarError as e:
            raise SchemaViolationError(
                f"Schema {schema.__name__} no se puede traducir a GBNF: {e}"
            ) from e
        try:
            grammar = LlamaGrammar.from_string(gbnf, verbose=False)
        except Exception as e:
            raise SchemaViolationError(
                f"llama.cpp rechazó la gramática para {schema.__name__}: {e}\n"
                f"gbnf:\n{gbnf}"
            ) from e
        self._grammar_cache[key] = grammar
        logger.debug(f"[LlamaCpp:{self.alias}] Gramática compilada: {key}")
        return grammar

    # ── Reset de estado ──────────────────────────────────────────────────────

    def reset_state(self) -> None:
        """Vacía el KV-cache del modelo.

        Garantiza determinismo bit-a-bit con seed fija y temperatura 0.
        """
        if hasattr(self, "_llm") and self._llm is not None:
            try:
                self._llm.reset()
            except Exception as e:
                # Si reset falla, se loguea y se continúa; se pierde
                # determinismo pero no datos.
                logger.warning(
                    f"[LlamaCpp:{self.alias}] reset() falló: {e}. "
                    "La siguiente llamada podría no ser bit-a-bit reproducible."
                )

    # ── Liberación de recursos ───────────────────────────────────────────────

    def close(self) -> None:
        """Libera el modelo de VRAM."""
        if hasattr(self, "_llm") and self._llm is not None:
            try:
                # __del__ libera contexto C++; en Python no es determinista.
                # Se marca None y se fuerza GC.
                del self._llm
                self._llm = None  # type: ignore[assignment]
            except Exception as e:
                logger.warning(f"[LlamaCpp:{self.alias}] Error al liberar modelo: {e}")
        self._grammar_cache.clear()
        import gc
        gc.collect()
        logger.info(f"[LlamaCpp:{self.alias}] Modelo descargado de memoria")
