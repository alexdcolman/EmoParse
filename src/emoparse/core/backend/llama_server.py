# ══════════════════════════════════════════════════════════════════════════════
#  emoparse.core.backend.llama_server
#
#  Backend para llama-server (llama.cpp en modo servidor HTTP).
#
#  Habilita las optimizaciones que el modo in-process no puede dar:
#  - Continuous batching: varias requests en vuelo (`--parallel N` en el
#    server + `pipeline.parallel` en el config) comparten la GPU.
#  - Reuso de KV-cache por prefijo: los system prompts largos y fijos de
#    EmoParse (ontologías + heurísticas) se procesan una vez por slot
#    (`--cache-reuse 256` recomendado en el server).
#  - Speculative decoding: `--model-draft <gguf-chico>` del lado del server,
#    transparente para este cliente. Con gramáticas GBNF la tasa de
#    aceptación del draft puede caer: medir con `emoparse metrics` antes de
#    adoptarlo.
#  - Multimodal: con el server lanzado con `--mmproj`, este backend acepta
#    imágenes (`images=[...]`) en el mensaje de usuario.
#
#  Lanzamiento típico del server:
#      llama-server -m modelo.gguf -ngl 99 -c 16384 --parallel 4 \
#          --cont-batching --cache-reuse 256 --port 8080
#
#  La generación estructurada usa la MISMA gramática GBNF que el backend
#  in-process (`schema_to_gbnf`, con `max_items`), enviada en el campo
#  `grammar` de /v1/chat/completions: salida válida por construcción y
#  paridad de comportamiento entre backends.
# ══════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

import base64
import mimetypes
import time
from pathlib import Path
from typing import Any, TypeVar

import httpx
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
    BackendTimeoutError,
    BackendUnavailableError,
    ContextLengthExceededError,
    SchemaViolationError,
)
from emoparse.core.grammar import GrammarError, schema_to_gbnf

T = TypeVar("T", bound=BaseModel)

#: Defaults; el config puede override.
_DEFAULT_TEMPERATURE = 0.0
_DEFAULT_MAX_TOKENS = 2048
_DEFAULT_SEED = 42
_DEFAULT_TIMEOUT = 120.0


class LlamaServerBackend(LLMBackend):
    """Backend HTTP contra llama-server (OpenAI-compatible + extensiones).

    Config (además de los campos comunes de ModelConfig):
        base_url:  URL del server (default http://127.0.0.1:8080).
        api_key:   opcional, si el server corre con --api-key.
        timeout:   segundos por request (default 120).
        no_think:  como en llama_cpp, agrega /no_think al system (Qwen3).
    """

    def __init__(
        self,
        alias: str,
        model_config: dict[str, Any],
    ) -> None:
        self.alias = alias
        self._cfg = dict(model_config)

        self._base_url = str(
            self._cfg.get("base_url") or "http://127.0.0.1:8080"
        ).rstrip("/")
        self._default_max_tokens = self._cfg.get("max_tokens", _DEFAULT_MAX_TOKENS)
        self._default_temperature = self._cfg.get("temperature", _DEFAULT_TEMPERATURE)
        self._default_seed = self._cfg.get("seed", _DEFAULT_SEED)
        self._top_p = self._cfg.get("top_p", 1.0)
        self._top_k = self._cfg.get("top_k", 40)
        self._min_p = self._cfg.get("min_p", 0.0)
        self._repeat_penalty = self._cfg.get("repeat_penalty", 1.0)
        self._no_think = bool(self._cfg.get("no_think", False))
        self._timeout = float(self._cfg.get("timeout", _DEFAULT_TIMEOUT))

        headers = {}
        api_key = self._cfg.get("api_key")
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        # Un cliente por backend; httpx.Client es thread-safe, apto para
        # despachar requests concurrentes con pipeline.parallel > 1.
        self._http = httpx.Client(
            base_url=self._base_url,
            headers=headers,
            timeout=self._timeout,
        )
        #: Cache de gramáticas GBNF (texto) por schema+max_items.
        self._grammar_cache: dict[str, str] = {}
        logger.info(f"[LlamaServer:{alias}] Cliente contra {self._base_url}")

    # ── Health check ─────────────────────────────────────────────────────────

    def healthcheck(self) -> bool:
        """Consulta /health del server (o una completion mínima si no existe)."""
        try:
            resp = self._http.get("/health")
            if resp.status_code == 200:
                return True
        except httpx.HTTPError:
            return False
        try:
            self._post_chat({"messages": [{"role": "user", "content": "ok"}],
                             "max_tokens": 1})
            return True
        except BackendError:
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
        # reset_before no aplica: cada request es independiente y el server
        # gestiona sus slots de KV-cache.
        eff_max_tokens = max_tokens if max_tokens is not None else self._default_max_tokens
        eff_temp = temperature if temperature is not None else self._default_temperature
        eff_seed = seed if seed is not None else self._default_seed

        sys_content = system
        if self._no_think:
            sys_content = f"{sys_content}\n\n/no_think" if sys_content else "/no_think"

        messages: list[dict[str, Any]] = []
        if sys_content:
            messages.append({"role": "system", "content": sys_content})
        messages.append({"role": "user", "content": _user_content(user, images)})

        payload: dict[str, Any] = {
            "messages": messages,
            "max_tokens": eff_max_tokens,
            "temperature": eff_temp,
            "top_p": self._top_p,
            "top_k": self._top_k,
            "min_p": self._min_p,
            "repeat_penalty": self._repeat_penalty,
            "seed": eff_seed,
        }
        if schema is not None:
            payload["grammar"] = self._get_grammar(schema, max_items)
        if stop:
            payload["stop"] = stop

        t_start = time.perf_counter()
        output = self._post_chat(payload)
        latency_ms = (time.perf_counter() - t_start) * 1000.0

        choice = output["choices"][0]
        raw = str(choice["message"].get("content") or "")
        finish_raw = choice.get("finish_reason", "stop")

        finish: FinishReason
        if finish_raw == "length":
            finish = "length"
        elif finish_raw is None or finish_raw == "stop":
            finish = "stop"
        else:
            finish = "error"

        if schema is not None and finish == "length":
            logger.error("[{}] finish=length | tail(raw)={!r}", self.alias, raw[-400:])
            raise ContextLengthExceededError(
                context_length=self._cfg.get("context_length"),
                max_tokens=eff_max_tokens,
            )

        usage_dict = output.get("usage", {}) or {}
        usage = TokenUsage(
            prompt_tokens=usage_dict.get("prompt_tokens", 0),
            completion_tokens=usage_dict.get("completion_tokens", 0),
        )

        parsed: BaseModel | None = None
        if schema is not None:
            try:
                parsed = schema.model_validate_json(raw)
            except ValidationError as e:
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
            extra={"timings": output.get("timings", {})},
        )

    # ── HTTP ─────────────────────────────────────────────────────────────────

    def _post_chat(self, payload: dict[str, Any]) -> dict[str, Any]:
        """POST /v1/chat/completions con errores tipados."""
        try:
            resp = self._http.post("/v1/chat/completions", json=payload)
        except httpx.TimeoutException as e:
            raise BackendTimeoutError(
                f"llama-server timeout tras {self._timeout}s: {e}"
            ) from e
        except httpx.HTTPError as e:
            raise BackendUnavailableError(
                f"llama-server inaccesible en {self._base_url}: {e}"
            ) from e
        if resp.status_code >= 400:
            texto = resp.text[:400]
            lowered = texto.lower()
            if "context" in lowered and (
                "exceed" in lowered or "too" in lowered or "length" in lowered
            ):
                raise ContextLengthExceededError(
                    context_length=self._cfg.get("context_length"),
                    max_tokens=payload.get("max_tokens"),
                )
            raise BackendError(
                f"llama-server HTTP {resp.status_code}: {texto}"
            )
        try:
            return resp.json()
        except ValueError as e:
            raise BackendError(f"llama-server devolvió no-JSON: {e}") from e

    # ── Cache de gramáticas ──────────────────────────────────────────────────

    def _get_grammar(
        self,
        schema: type[BaseModel],
        max_items: int | None = None,
    ) -> str:
        """Devuelve (o genera) el texto GBNF para `schema`."""
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
        self._grammar_cache[key] = gbnf
        logger.debug(f"[LlamaServer:{self.alias}] Gramática generada: {key}")
        return gbnf

    # ── Liberación de recursos ───────────────────────────────────────────────

    def close(self) -> None:
        """Cierra el cliente HTTP (el server queda corriendo)."""
        self._http.close()
        self._grammar_cache.clear()


# ══════════════════════════════════════════════════════════════════════════════
#  Contenido multimodal
# ══════════════════════════════════════════════════════════════════════════════

def _user_content(user: str, images: list[str] | None) -> str | list[dict[str, Any]]:
    """Construye el contenido del mensaje de usuario.

    Sin imágenes devuelve el string plano (formato clásico). Con imágenes,
    la lista multiparte OpenAI-compatible: cada imagen es una URL http(s) o
    un path local que se embebe como data URI base64.
    """
    if not images:
        return user
    parts: list[dict[str, Any]] = [{"type": "text", "text": user}]
    for ref in images:
        parts.append({"type": "image_url", "image_url": {"url": _image_url(ref)}})
    return parts


def _image_url(ref: str) -> str:
    """URL http(s) tal cual; path local → data URI base64."""
    if ref.startswith(("http://", "https://", "data:")):
        return ref
    path = Path(ref).expanduser()
    if not path.is_file():
        raise BackendConfigError(f"Imagen no encontrada: {path}")
    mime = mimetypes.guess_type(path.name)[0] or "image/jpeg"
    data = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{mime};base64,{data}"
