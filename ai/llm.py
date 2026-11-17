"""
ai/llm.py
One small interface for the tutorials assistant's language models:

    chat(messages, stream=True)  -> iterator of text pieces (or one string)
    embed(texts)                 -> list of vectors

messages use the OpenAI shape: [{"role": "system"|"user"|"assistant",
"content": "..."}]. A system message, if any, must come first.

Chat provider is chosen by LLM_PROVIDER:
  - "ollama": the local Ollama server through its OpenAI-compatible API
    (openai client, LLM_BASE_URL + LLM_MODEL). Qwen 3.5 "thinking" is turned
    off with reasoning_effort="none" (LLM_REASONING_EFFORT), otherwise a
    one-line answer costs hundreds of hidden tokens on this CPU.
  - "gemini" (default, so production is unchanged until switched): Google
    Gemini through google-genai (GEMINI_API_KEY, GEMINI_MODEL), with the same
    fallback models chatbot.py already uses.

Embeddings always come from Ollama's native /api/embed (EMBED_MODEL),
whatever LLM_PROVIDER says: the knowledge base index must not change when
the chat provider is switched, and the PDFs' text never leaves the server.

All failures surface as LLMError (LLMUnavailable when the service can't be
reached or times out) with a message that is safe to log and specific
enough to act on. Callers decide what to show end users.

Configuration is read from the environment on every call, so tests and a
changed .env (after a restart) need no special handling.
"""
import json
import os

import httpx

DEFAULTS = {
    "LLM_PROVIDER": "gemini",
    "LLM_BASE_URL": "http://127.0.0.1:11434/v1",
    "LLM_MODEL": "qwen3.5:2b",
    "LLM_REASONING_EFFORT": "none",
    "LLM_TIMEOUT": "90",  # seconds to first token / between streamed tokens
    "LLM_MAX_TOKENS": "600",
    "LLM_TEMPERATURE": "0.2",
    "EMBED_MODEL": "qwen3-embedding:0.6b",
    "EMBED_TIMEOUT": "120",
    "GEMINI_MODEL": "gemini-3.5-flash",
}
PROVIDERS = ("ollama", "gemini")
GEMINI_FALLBACKS = ("gemini-3.6-flash", "gemini-3.1-flash-lite", "gemini-3.5-flash-lite")
CONNECT_TIMEOUT = 5  # seconds; a local service either answers fast or is down
EMBED_BATCH = 16

# Instruction prefix recommended for qwen3-embedding *queries* (documents are
# embedded as-is). Other embedding models get the plain query.
QWEN3_EMBED_QUERY_PREFIX = (
    "Instruct: Given an IT support question, retrieve guide passages that answer it\nQuery: "
)


class LLMError(RuntimeError):
    """Any failure talking to a model. str(exc) is safe to log."""


class LLMUnavailable(LLMError):
    """The model service could not be reached or did not answer in time."""


def setting(name):
    value = os.environ.get(name, "").strip()
    return value or DEFAULTS.get(name, "")


def provider():
    name = setting("LLM_PROVIDER").lower()
    if name not in PROVIDERS:
        raise LLMError(f"LLM_PROVIDER must be one of {', '.join(PROVIDERS)} (got {name!r}).")
    return name


def model_name():
    """The chat model the current provider will use (for logs and UI)."""
    return setting("LLM_MODEL") if provider() == "ollama" else setting("GEMINI_MODEL")


def ollama_root():
    """LLM_BASE_URL without the OpenAI-compatible /v1 suffix."""
    base = setting("LLM_BASE_URL").rstrip("/")
    return base[: -len("/v1")] if base.endswith("/v1") else base


# ------------------------------------------------------------------- chat


def chat(messages, stream=True, *, max_tokens=None, temperature=None):
    """Send a conversation; return an iterator of text pieces (stream=True)
    or the whole answer as one string (stream=False).

    With stream=True, connection errors are raised when the iterator is
    first advanced, not by this call - consume it inside your try block."""
    _check_messages(messages)
    max_tokens = int(max_tokens or setting("LLM_MAX_TOKENS"))
    temperature = float(setting("LLM_TEMPERATURE") if temperature is None else temperature)
    if provider() == "ollama":
        pieces = _ollama_chat(messages, max_tokens, temperature)
    else:
        pieces = _gemini_chat(messages, max_tokens, temperature)
    return pieces if stream else "".join(pieces).strip()


def _check_messages(messages):
    if not isinstance(messages, list) or not messages:
        raise ValueError("messages must be a non-empty list")
    for i, m in enumerate(messages):
        if m.get("role") not in ("system", "user", "assistant") or not isinstance(m.get("content"), str):
            raise ValueError(f"messages[{i}] needs role system/user/assistant and string content")
        if m["role"] == "system" and i != 0:
            raise ValueError("only the first message may be a system message")


def _ollama_client():
    from openai import OpenAI

    return OpenAI(
        base_url=setting("LLM_BASE_URL"),
        api_key="ollama",  # required by the client, ignored by Ollama
        timeout=httpx.Timeout(float(setting("LLM_TIMEOUT")), connect=CONNECT_TIMEOUT),
        max_retries=0,
    )


def _ollama_chat(messages, max_tokens, temperature):
    import openai

    model = setting("LLM_MODEL")
    where = setting("LLM_BASE_URL")
    kwargs = {}
    effort = setting("LLM_REASONING_EFFORT").lower()
    if effort and effort != "default":
        kwargs["reasoning_effort"] = effort
    try:
        response = _ollama_client().chat.completions.create(
            model=model,
            messages=messages,
            stream=True,
            max_tokens=max_tokens,
            temperature=temperature,
            **kwargs,
        )
        for chunk in response:
            if chunk.choices and chunk.choices[0].delta.content:
                yield chunk.choices[0].delta.content
    except openai.APITimeoutError as exc:
        raise LLMUnavailable(
            f"Ollama at {where} did not answer within {setting('LLM_TIMEOUT')} s "
            f"(model {model}). It may be overloaded or still loading the model."
        ) from exc
    except openai.APIConnectionError as exc:
        raise LLMUnavailable(
            f"Cannot reach Ollama at {where}. Is the ollama service running? "
            "(systemctl status ollama)"
        ) from exc
    except openai.NotFoundError as exc:
        raise LLMError(
            f"Ollama has no model {model!r}. Install it with: ollama pull {model}"
        ) from exc
    except openai.APIStatusError as exc:
        raise LLMError(f"Ollama returned HTTP {exc.status_code}: {_short(exc.message)}") from exc


def _gemini_client():
    from google import genai

    if not os.environ.get("GEMINI_API_KEY"):
        raise LLMError("LLM_PROVIDER=gemini but GEMINI_API_KEY is not set.")
    return genai.Client(
        http_options={
            "timeout": int(float(setting("LLM_TIMEOUT")) * 1000),
            "retry_options": {"attempts": 1},
        }
    )


def _gemini_chat(messages, max_tokens, temperature):
    from google.genai import errors as genai_errors

    system = messages[0]["content"] if messages[0]["role"] == "system" else None
    contents = [
        {"role": "model" if m["role"] == "assistant" else "user", "parts": [{"text": m["content"]}]}
        for m in messages
        if m["role"] != "system"
    ]
    config = {"max_output_tokens": max_tokens, "temperature": temperature}
    if system:
        config["system_instruction"] = system
    primary = setting("GEMINI_MODEL")
    models = [primary] + [m for m in GEMINI_FALLBACKS if m != primary]
    client = _gemini_client()
    last = None
    for model in models:
        started = False
        try:
            for chunk in client.models.generate_content_stream(
                model=model, contents=contents, config=config
            ):
                text = chunk.text or ""
                if text:
                    started = True
                    yield text
            return
        except genai_errors.APIError as exc:
            # Busy / retired model before any output: try the next one.
            if not started and exc.code in (404, 429, 500, 503, 504):
                last = exc
                continue
            raise LLMError(f"Gemini model {model} failed (HTTP {exc.code}).") from exc
        except Exception as exc:
            if not started and any(
                k in type(exc).__name__ for k in ("Timeout", "ReadError", "ConnectError")
            ):
                last = exc
                continue
            if started:
                raise LLMUnavailable(f"Gemini stream from {model} broke off: {type(exc).__name__}") from exc
            raise
    raise LLMUnavailable(
        f"All Gemini models are busy or unreachable ({', '.join(models)}); last error: "
        f"{type(last).__name__}"
    )


# ------------------------------------------------------------------ embed


def embed(texts, *, query=False):
    """Embed a list of strings with EMBED_MODEL on Ollama; returns one vector
    per text, in order. query=True marks short search questions (adds the
    model's recommended query instruction)."""
    if isinstance(texts, str):
        raise ValueError("embed() takes a list of strings")
    texts = list(texts)
    if not texts:
        return []
    model = setting("EMBED_MODEL")
    if query and model.startswith("qwen3-embedding"):
        texts = [QWEN3_EMBED_QUERY_PREFIX + t for t in texts]
    url = ollama_root() + "/api/embed"
    timeout = httpx.Timeout(float(setting("EMBED_TIMEOUT")), connect=CONNECT_TIMEOUT)
    vectors = []
    with _http_client(timeout) as http:
        for i in range(0, len(texts), EMBED_BATCH):
            batch = texts[i : i + EMBED_BATCH]
            try:
                r = http.post(url, json={"model": model, "input": batch, "truncate": True})
            except httpx.TimeoutException as exc:
                raise LLMUnavailable(
                    f"Ollama at {ollama_root()} did not finish embedding within "
                    f"{setting('EMBED_TIMEOUT')} s (model {model})."
                ) from exc
            except httpx.TransportError as exc:
                raise LLMUnavailable(
                    f"Cannot reach Ollama at {ollama_root()}. Is the ollama service running? "
                    "(systemctl status ollama)"
                ) from exc
            if r.status_code == 404:
                raise LLMError(f"Ollama has no model {model!r}. Install it with: ollama pull {model}")
            if r.status_code != 200:
                raise LLMError(f"Ollama embed returned HTTP {r.status_code}: {_short(r.text)}")
            got = r.json().get("embeddings") or []
            if len(got) != len(batch):
                raise LLMError(f"Ollama returned {len(got)} embeddings for {len(batch)} texts.")
            vectors.extend(got)
    return vectors


def _http_client(timeout):
    return httpx.Client(timeout=timeout)


# ----------------------------------------------------------------- health


def health():
    """Quick status for logs/admin: is Ollama up, and are the models pulled?
    Never raises."""
    info = {"provider": None, "chat_model": None, "embed_model": setting("EMBED_MODEL"),
            "ollama": "unknown", "missing_models": []}
    try:
        info["provider"] = provider()
        info["chat_model"] = model_name()
    except LLMError as exc:
        info["error"] = str(exc)
        return info
    try:
        with _http_client(httpx.Timeout(5.0)) as http:
            r = http.get(ollama_root() + "/api/tags")
        r.raise_for_status()
        have = {m.get("name") for m in r.json().get("models", [])}
        have |= {n.removesuffix(":latest") for n in have if n}
        wanted = [setting("EMBED_MODEL")]
        if info["provider"] == "ollama":
            wanted.append(setting("LLM_MODEL"))
        info["missing_models"] = [m for m in wanted if m not in have]
        info["ollama"] = "up"
    except Exception as exc:
        info["ollama"] = f"down ({type(exc).__name__})"
    return info


def _short(text, limit=200):
    text = " ".join(str(text).split())
    return text if len(text) <= limit else text[:limit] + "..."


# --------------------------------------------------------------- smoke test

if __name__ == "__main__":
    # python -m ai.llm "question"   (uses the current environment)
    import sys
    import time

    print(json.dumps(health(), indent=2))
    question = " ".join(sys.argv[1:]) or "Reply with the single word: ready"
    t0 = time.time()
    first = None
    for piece in chat([{"role": "user", "content": question}], stream=True):
        first = first or time.time() - t0
        print(piece, end="", flush=True)
    print(f"\n[{provider()} {model_name()}] first token {first or 0:.1f}s, total {time.time() - t0:.1f}s")
    v = embed(["Safe Mode"], query=True)
    print(f"[embed {setting('EMBED_MODEL')}] dim {len(v[0])}")
