"""Model-independent language-model interface (stabilization, item 9).

The core never talks to a provider. It talks to ``LanguageModel`` — a
small protocol with one method, ``complete(prompt)``. Any model that
can implement that method (Meta's Muse Spark, Qwen, Llama, a local
FLAN-T5, a test mock) attaches behind the same interface, and the
core never learns which one it is.

* ``LanguageModel`` — the protocol. ``complete`` returns a
  ``ModelResponse`` (text + model id + optional token count).
* ``ModelConfig`` — what a model needs to be built (id, endpoint,
  key env var, generation settings). No secrets are stored here;
  the key is read from the environment at build time.
* ``CallableModel`` — wraps any ``callable(prompt) -> str`` (a local
  pipeline, a test double) as a LanguageModel.
* ``MetaModelAdapter`` — Muse Spark 1.3 via the registered
  ``custom.meta-model-api`` connection (``eval/live_model.py``):
  surrogate auth, ``https://api.meta.ai/v1/chat/completions``,
  ``max_tokens=2048``, 180 s timeout, retries on 5xx/timeout,
  HTTP 429 as a hard stop. VALIDATED Oct 27, 2026 (Phase 4 smoke
  test, EVAL_RESULTS.md §14). The vendored raw client
  (``nova/adapter/meta.py``) is no longer the default path — it
  stays as the untouched v0.3 artifact.
* ``OpenAICompatibleAdapter`` — a generic OpenAI-compatible
  chat-completions client: any provider that speaks the schema
  attaches with a base URL + model + key env var — or with a
  ``transport`` callable, in which case no key is read at all
  (that is how connector-backed providers attach; see
  ``BasetenAdapter``). Transport validated against a loopback
  stub in tests.
* ``BasetenAdapter`` — Muse Spark Open
  (``meta-models/muse-spark-open-1026``) on Baseten's inference
  gateway, via the registered ``custom.baseten`` connection:
  surrogate auth, ``https://inference.baseten.co/v1/
  chat/completions``, ``max_tokens=2048``, 180 s timeout, retries
  on 5xx/timeout, HTTP 429 as a hard stop. VALIDATED Oct 27, 2026
  (Baseten smoke test, EVAL_RESULTS.md §15). Only that model is
  served: anything else is a configuration error.
* ``MockModel`` — a deterministic canned model for tests and the
  harness's MOCK arm. It never pretends to be a real model.
* Registry — ``register_model`` / ``get_model``. Built-ins:
  ``meta`` and ``muse-spark`` (connector-backed Muse Spark),
  ``baseten`` (connector-backed Muse Spark Open),
  ``mock``, ``openai-compatible`` (generic, needs endpoint
  config). Qwen, Llama, and anything else attach by registering
  an adapter that implements ``complete`` — there are no fake
  provider implementations here.

A model's words are always advisory: the pipeline labels them
``unverified_model_output`` and never substitutes them for a proven
answer.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Protocol, runtime_checkable


@dataclass
class ModelResponse:
    """One completion: the text, who produced it, and (when the
    provider reports it) how many tokens it cost."""
    text: str
    model_id: str
    tokens_used: int | None = None
    raw: dict | None = None


@dataclass
class ModelConfig:
    """How to build a model. The API key is never stored here — it is
    read from ``api_key_env`` at build time."""
    model_id: str
    endpoint: str | None = None
    api_key_env: str = "NOVA_MODEL_API_KEY"
    max_tokens: int = 128
    temperature: float = 0.0


@runtime_checkable
class LanguageModel(Protocol):
    """Any language model NOVA can use. One method, no provider
    knowledge in the core."""

    model_id: str

    def complete(self, prompt: str, *, max_tokens: int = 128,
                 temperature: float = 0.0) -> ModelResponse:
        """Complete ``prompt`` and return the response."""
        ...


class CallableModel:
    """A plain ``callable(prompt) -> str`` (or -> ModelResponse) as a
    LanguageModel. This is how a local HF pipeline, a test double, or
    any ad-hoc function attaches."""

    def __init__(self, fn: Callable, model_id: str = "callable"):
        if not callable(fn):
            raise TypeError("CallableModel needs a callable")
        self._fn = fn
        self.model_id = model_id

    def complete(self, prompt: str, *, max_tokens: int = 128,
                 temperature: float = 0.0) -> ModelResponse:
        out = self._fn(prompt)
        if isinstance(out, ModelResponse):
            return out
        return ModelResponse(text=str(out), model_id=self.model_id)


class RateLimitedError(RuntimeError):
    """The provider returned HTTP 429. The run must stop, not retry."""


class MetaModelAdapter:
    """Muse Spark 1.3 via the registered Meta Model API connection.

    Delegates to ``eval.live_model.LiveModel`` — the connector-
    validated transport: surrogate auth against ``api.meta.ai``,
    POST ``/v1/chat/completions``, ``max_tokens=2048``, 180 s
    timeout, retries on 5xx/timeout, HTTP 429 as a hard stop.
    VALIDATED Oct 27, 2026 (Phase 4 smoke test, EVAL_RESULTS.md
    §14). The lazy import of ``eval.live_model`` avoids a circular
    import (that module imports ``ModelResponse`` from here).

    The vendored raw client (``nova/adapter/meta.py``) is NOT used
    here: it is the untouched v0.3 artifact and its endpoint/schema
    were never validated against Meta's native API.

    Only ``muse-spark-1.3`` is served: the connection is registered
    for that model, and anything else is a configuration error.
    """

    def __init__(self, config: ModelConfig | None = None, **overrides):
        import os
        cfg = config or ModelConfig(model_id="muse-spark-1.3")
        if overrides:
            import dataclasses
            cfg = dataclasses.replace(
                cfg, **{k: v for k, v in overrides.items()
                        if k in ModelConfig.__dataclass_fields__})
        model_id = cfg.model_id or "muse-spark-1.3"
        if model_id not in ("muse-spark-1.3", "meta", "muse-spark"):
            raise ValueError(
                f"MetaModelAdapter serves muse-spark-1.3 only, "
                f"got model_id={model_id!r}")
        self.config = cfg
        self.model_id = "muse-spark-1.3"
        # The protocol default max_tokens=128 truncates this reasoning
        # model to an empty answer (see eval/live_model.py); 2048 is
        # the validated cap unless the caller passes another value
        # explicitly.
        max_tokens = overrides.get("max_tokens")
        if max_tokens is None:
            max_tokens = (cfg.max_tokens if cfg.max_tokens != 128
                          else 2048)
        self._max_tokens = max_tokens
        self._temperature = cfg.temperature
        from eval.live_model import LiveModel
        self._live = LiveModel(max_tokens=self._max_tokens)

    def complete(self, prompt: str, *, max_tokens: int = 2048,
                 temperature: float = 0.0) -> ModelResponse:
        return self._live.complete(prompt, max_tokens=max_tokens,
                                   temperature=temperature)


class OpenAICompatibleAdapter:
    """A generic OpenAI-compatible chat-completions client.

    Any provider that speaks the OpenAI chat-completions schema
    attaches here: base URL + model + key env var, nothing
    provider-specific. HTTPS is enforced except for loopback
    (tests). HTTP 429 is a hard stop (no retry); 5xx/timeout retry
    twice. The API key is read from the environment at build time
    and never stored in a file or a log.

    ``transport`` (optional): a callable ``(base_url, body) ->
    payload dict`` that performs the HTTP POST. When given, the
    env-key path is not used at all — no key is read, no
    Authorization header is built. That is how connector-backed
    providers attach (see ``BasetenAdapter``, whose transport is
    the surrogate-based Baseten helper): the credential lives in
    the registered connection, never in an env var.

    Transport validated against a loopback stub in
    ``tests/test_model_backends.py``. The Baseten transport is
    live-validated (EVAL_RESULTS.md §15).

    ``last_usage`` / ``last_finish_reason`` record the most recent
    successful call's token counts and finish reason, so a caller
    can attribute cost per item without a second call.
    """

    def __init__(self, config: ModelConfig | None = None,
                 transport=None, **overrides):
        import os
        cfg = config or ModelConfig(model_id="")
        if overrides:
            import dataclasses
            cfg = dataclasses.replace(
                cfg, **{k: v for k, v in overrides.items()
                        if k in ModelConfig.__dataclass_fields__})
        self.config = cfg
        base_url = cfg.endpoint or os.getenv("NOVA_MODEL_ENDPOINT")
        model = cfg.model_id or os.getenv("NOVA_MODEL_ID")
        if not base_url or not model:
            raise ValueError(
                "OpenAICompatibleAdapter needs an endpoint and a "
                "model: set NOVA_MODEL_ENDPOINT and NOVA_MODEL_ID, "
                "or pass endpoint=/model_id= in ModelConfig")
        if (not base_url.startswith("https://")
                and not base_url.startswith("http://127.0.0.1:")
                and not base_url.startswith("http://localhost:")):
            raise ValueError(
                "model endpoint must use HTTPS (except local loopback)")
        self._base_url = base_url.rstrip("/")
        self._model = model
        self.model_id = model
        self._transport = transport
        # With a transport the credential lives in the registered
        # connection, not in the environment: read nothing.
        self._api_key = (None if transport is not None else
                         (os.getenv(cfg.api_key_env)
                          if cfg.api_key_env else None))
        self._max_tokens = (cfg.max_tokens if cfg.max_tokens != 128
                            else 2048)
        self._temperature = cfg.temperature
        self.last_usage: dict | None = None
        self.last_finish_reason: str | None = None

    def _post(self, body: dict) -> dict:
        """One POST of ``body`` to the chat-completions endpoint.

        With a transport, the transport performs the request (it
        owns auth — e.g. the connector surrogate). Without one,
        the env-var key is sent as a Bearer token.
        """
        import json
        import urllib.request

        if self._transport is not None:
            return self._transport(self._base_url, body)
        headers = {"Content-Type": "application/json"}
        if self._api_key:
            headers["Authorization"] = "Bearer " + self._api_key
        request = urllib.request.Request(
            self._base_url + "/chat/completions",
            data=json.dumps(body).encode(), headers=headers,
            method="POST")

        class _NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, *args):
                raise RuntimeError("redirect refused, verify the endpoint")

        with urllib.request.build_opener(_NoRedirect()).open(
                request, timeout=25) as resp:
            return json.load(resp)

    def complete(self, prompt: str, *, max_tokens: int = 2048,
                 temperature: float = 0.0) -> ModelResponse:
        import time
        import urllib.error

        body = {"model": self._model,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": temperature,
                "max_tokens": max_tokens}

        last_exc: Exception | None = None
        payload: dict | None = None
        for attempt in range(3):
            try:
                payload = self._post(body)
                break
            except urllib.error.HTTPError as e:
                if e.code == 429:
                    raise RateLimitedError(
                        "provider rate limit (HTTP 429)") from e
                if e.code in (401, 403):
                    raise RuntimeError(
                        f"provider auth rejected (HTTP {e.code})") from e
                if e.code in (500, 502, 503) and attempt < 2:
                    last_exc = e
                    time.sleep(2.0 * (attempt + 1))
                    continue
                raise RuntimeError(
                    f"provider HTTP {e.code}: "
                    f"{e.read().decode(errors='replace')[:300]}") from e
            except (TimeoutError, urllib.error.URLError,
                    ConnectionError) as e:
                last_exc = e
                if attempt < 2:
                    time.sleep(2.0 * (attempt + 1))
                    continue
                raise RuntimeError(
                    f"provider request failed after 3 attempts: {e}"
                    ) from e
        if payload is None:
            raise RuntimeError(f"provider request failed: {last_exc}")
        choice = (payload.get("choices") or [{}])[0]
        text = choice.get("message", {}).get("content")
        usage = payload.get("usage") or {}
        tokens_in = int(usage.get("prompt_tokens") or 0)
        tokens_out = int(usage.get("completion_tokens") or 0)
        self.last_usage = {"tokens_in": tokens_in,
                           "tokens_out": tokens_out}
        self.last_finish_reason = choice.get("finish_reason")
        return ModelResponse(
            text=text if isinstance(text, str) else "",
            model_id=self.model_id,
            tokens_used=(tokens_in + tokens_out) or None,
            raw={"tokens_in": tokens_in, "tokens_out": tokens_out,
                 "finish_reason": choice.get("finish_reason")})


class BasetenAdapter(OpenAICompatibleAdapter):
    """Muse Spark Open on Baseten's inference gateway.

    The second live backend (EVAL_RESULTS.md §15). Serves only
    ``meta-models/muse-spark-open-1026`` ([HACKATHON] Muse Spark
    Open) at ``https://inference.baseten.co/v1``. The credential
    lives in the registered ``custom.baseten`` connection: the
    transport is the surrogate-based ``baseten_post_chat`` from
    ``eval/live_baseten.py`` — no key is ever read from the
    environment, and no Authorization header is built here.

    Construction needs no env vars and makes no network call.
    Any other model id or endpoint is a configuration error.
    ``openai/gpt-oss-120b`` is 403-gated for this workspace; do
    not register it as if it worked.
    """

    MODEL_ID = "meta-models/muse-spark-open-1026"
    BASE_URL = "https://inference.baseten.co/v1"

    def __init__(self, config: ModelConfig | None = None, **overrides):
        if overrides:
            import dataclasses
            cfg = config or ModelConfig(model_id=self.MODEL_ID)
            cfg = dataclasses.replace(
                cfg, **{k: v for k, v in overrides.items()
                        if k in ModelConfig.__dataclass_fields__})
            config = cfg
        cfg = config or ModelConfig(model_id=self.MODEL_ID)
        if cfg.model_id not in (self.MODEL_ID, "baseten"):
            raise ValueError(
                f"BasetenAdapter serves {self.MODEL_ID} only, "
                f"got model_id={cfg.model_id!r}")
        if cfg.endpoint and cfg.endpoint.rstrip("/") != self.BASE_URL:
            raise ValueError(
                f"BasetenAdapter endpoint is fixed to {self.BASE_URL}, "
                f"got endpoint={cfg.endpoint!r}")
        from eval.live_baseten import baseten_post_chat
        super().__init__(
            ModelConfig(model_id=self.MODEL_ID,
                        endpoint=self.BASE_URL,
                        max_tokens=cfg.max_tokens,
                        temperature=cfg.temperature),
            transport=baseten_post_chat)


class MockModel:
    """A deterministic canned model for tests and the harness MOCK arm.

    ``response`` is returned for every prompt (or, if callable, called
    with the prompt). It is labeled mock everywhere it appears and
    must never be presented as a real model's output.
    """

    def __init__(self, response: str | Callable[[str], str] = "mock",
                 model_id: str = "mock"):
        self._response = response
        self.model_id = model_id

    def complete(self, prompt: str, *, max_tokens: int = 128,
                 temperature: float = 0.0) -> ModelResponse:
        text = (self._response(prompt) if callable(self._response)
                else self._response)
        return ModelResponse(text=text, model_id=self.model_id)


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

_REGISTRY: dict[str, Callable[[ModelConfig], LanguageModel]] = {}


def register_model(name: str,
                   factory: Callable[[ModelConfig], LanguageModel]
                   ) -> None:
    """Register a model factory under ``name``.

    To attach Qwen, Llama, or any other model, write an adapter class
    implementing ``complete`` and register it here — e.g.
    ``register_model("qwen", lambda cfg: QwenAdapter(cfg))``. The core
    never imports provider SDKs itself.
    """
    if not callable(factory):
        raise TypeError("model factory must be callable")
    _REGISTRY[name.lower()] = factory


def get_model(name: str, config: ModelConfig | None = None
              ) -> LanguageModel:
    """Build the registered model ``name`` with ``config``."""
    factory = _REGISTRY.get(name.lower())
    if factory is None:
        known = ", ".join(sorted(_REGISTRY)) or "(none)"
        raise ValueError(f"unknown model '{name}' (registered: {known})")
    if config is None:
        config = ModelConfig(model_id=name)
    return factory(config)


def list_models() -> list[str]:
    """Names of registered models."""
    return sorted(_REGISTRY)


def coerce_model(model) -> LanguageModel | None:
    """Normalize whatever the caller passed as a model.

    ``None`` stays None (deterministic path, no model). A
    ``LanguageModel`` passes through. A plain callable becomes a
    ``CallableModel``. Anything else raises TypeError — a model that
    cannot complete a prompt is a configuration error, not something
    to silently ignore.
    """
    if model is None:
        return None
    if isinstance(model, LanguageModel):
        return model
    if callable(model):
        return CallableModel(model)
    raise TypeError(
        f"model must be a LanguageModel or a callable, got "
        f"{type(model).__name__}")


register_model("meta",
                 lambda cfg: MetaModelAdapter(cfg,
                                              model_id="muse-spark-1.3"))
register_model("muse-spark",
                 lambda cfg: MetaModelAdapter(cfg,
                                              model_id="muse-spark-1.3"))
register_model("baseten", lambda cfg: BasetenAdapter(cfg))
register_model("mock", lambda cfg: MockModel(model_id=cfg.model_id))
register_model("openai-compatible",
                 lambda cfg: OpenAICompatibleAdapter(cfg))
