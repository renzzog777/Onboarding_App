"""ai/llm.py: provider switch, Ollama (OpenAI-compatible) chat + /api/embed,
Gemini path, and clear errors when Ollama is down. No real model needed:
HTTP is faked with httpx.MockTransport (one test uses a closed local port)."""
import json
import os

import httpx
import pytest
from openai import OpenAI

from ai import llm

LLM_VARS = [k for k in llm.DEFAULTS] + ["GEMINI_API_KEY"]


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for k in LLM_VARS:
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("LLM_PROVIDER", "ollama")


def fake_openai(monkeypatch, handler):
    seen = []

    def wrapped(request):
        seen.append(request)
        return handler(request)

    def make():
        return OpenAI(
            base_url=llm.setting("LLM_BASE_URL"),
            api_key="ollama",
            max_retries=0,
            http_client=httpx.Client(transport=httpx.MockTransport(wrapped)),
        )

    monkeypatch.setattr(llm, "_ollama_client", make)
    return seen


def sse(pieces):
    lines = []
    for p in pieces:
        chunk = {
            "id": "c1", "object": "chat.completion.chunk", "created": 0, "model": "m",
            "choices": [{"index": 0, "delta": {"role": "assistant", "content": p}, "finish_reason": None}],
        }
        lines.append(f"data: {json.dumps(chunk)}\n\n")
    lines.append("data: [DONE]\n\n")
    return httpx.Response(200, text="".join(lines), headers={"content-type": "text/event-stream"})


MSGS = [{"role": "system", "content": "Be brief."}, {"role": "user", "content": "Hi"}]


# ------------------------------------------------------------ provider


def test_default_provider_is_gemini_so_production_is_unchanged(monkeypatch):
    monkeypatch.delenv("LLM_PROVIDER")
    assert llm.provider() == "gemini"


def test_invalid_provider_is_a_clear_error(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    with pytest.raises(llm.LLMError, match="ollama, gemini"):
        llm.chat(MSGS)


def test_ollama_root_strips_v1(monkeypatch):
    monkeypatch.setenv("LLM_BASE_URL", "http://ollama-host:11434/v1/")
    assert llm.ollama_root() == "http://ollama-host:11434"


def test_message_validation():
    with pytest.raises(ValueError):
        llm.chat([])
    with pytest.raises(ValueError, match="first message"):
        llm.chat([{"role": "user", "content": "a"}, {"role": "system", "content": "b"}])


# --------------------------------------------------------- ollama chat


def test_ollama_streams_pieces_and_sends_model_and_no_thinking(monkeypatch):
    monkeypatch.setenv("LLM_MODEL", "qwen3.5:2b")
    seen = fake_openai(monkeypatch, lambda req: sse(["Hel", "lo", "!"]))
    pieces = list(llm.chat(MSGS, stream=True))
    assert pieces == ["Hel", "lo", "!"]
    body = json.loads(seen[0].content)
    assert seen[0].url.path == "/v1/chat/completions"
    assert body["model"] == "qwen3.5:2b"
    assert body["messages"] == MSGS
    assert body["reasoning_effort"] == "none"
    assert body["stream"] is True


def test_ollama_non_stream_returns_whole_text(monkeypatch):
    fake_openai(monkeypatch, lambda req: sse(["Step 1. ", "Open Safari. "]))
    assert llm.chat(MSGS, stream=False) == "Step 1. Open Safari."


def test_reasoning_effort_can_be_left_to_the_model(monkeypatch):
    monkeypatch.setenv("LLM_REASONING_EFFORT", "default")
    seen = fake_openai(monkeypatch, lambda req: sse(["ok"]))
    llm.chat(MSGS, stream=False)
    assert "reasoning_effort" not in json.loads(seen[0].content)


def test_ollama_down_gives_clear_unavailable_error(monkeypatch):
    # Real client, closed port: connection refused immediately.
    monkeypatch.setenv("LLM_BASE_URL", "http://127.0.0.1:9/v1")
    with pytest.raises(llm.LLMUnavailable, match=r"Cannot reach Ollama at http://127.0.0.1:9/v1.*systemctl status ollama"):
        llm.chat(MSGS, stream=False)


def test_ollama_timeout_is_reported(monkeypatch):
    def slow(req):
        raise httpx.ReadTimeout("slow", request=req)

    fake_openai(monkeypatch, slow)
    with pytest.raises(llm.LLMUnavailable, match="did not answer within 150 s"):
        llm.chat(MSGS, stream=False)


def test_missing_model_says_how_to_pull_it(monkeypatch):
    monkeypatch.setenv("LLM_MODEL", "nope:1b")
    fake_openai(monkeypatch, lambda req: httpx.Response(404, json={"error": {"message": "model not found"}}))
    with pytest.raises(llm.LLMError, match="ollama pull nope:1b"):
        llm.chat(MSGS, stream=False)


def test_other_http_errors_are_wrapped(monkeypatch):
    fake_openai(monkeypatch, lambda req: httpx.Response(500, json={"error": {"message": "boom"}}))
    with pytest.raises(llm.LLMError, match="HTTP 500"):
        llm.chat(MSGS, stream=False)


# --------------------------------------------------------------- embed


def fake_http(monkeypatch, handler):
    seen = []

    def wrapped(request):
        seen.append(request)
        return handler(request)

    monkeypatch.setattr(
        llm, "_http_client",
        lambda timeout: httpx.Client(transport=httpx.MockTransport(wrapped), timeout=timeout),
    )
    return seen


def echo_vectors(req):
    inputs = json.loads(req.content)["input"]
    return httpx.Response(200, json={"embeddings": [[float(len(t)), 1.0] for t in inputs]})


def test_embed_batches_in_order_via_native_api(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "gemini")  # embeddings are always Ollama
    seen = fake_http(monkeypatch, echo_vectors)
    texts = [f"chunk {i:02d}" for i in range(20)]
    vectors = llm.embed(texts)
    assert len(vectors) == 20 and vectors[0] == [8.0, 1.0]
    assert len(seen) == 2  # 16 + 4
    assert str(seen[0].url) == "http://127.0.0.1:11434/api/embed"
    assert json.loads(seen[0].content)["model"] == "qwen3-embedding:0.6b"


def test_embed_query_prefix_only_for_queries(monkeypatch):
    seen = fake_http(monkeypatch, echo_vectors)
    llm.embed(["How do I boot in Safe Mode?"], query=True)
    llm.embed(["Safe Mode guide text"])
    q, d = (json.loads(r.content)["input"][0] for r in seen)
    assert q.startswith("Instruct:") and q.endswith("Safe Mode?")
    assert d == "Safe Mode guide text"


def test_embed_empty_and_wrong_type():
    assert llm.embed([]) == []
    with pytest.raises(ValueError):
        llm.embed("not a list")


def test_embed_down_and_missing_model(monkeypatch):
    monkeypatch.setenv("LLM_BASE_URL", "http://127.0.0.1:9/v1")
    with pytest.raises(llm.LLMUnavailable, match="Cannot reach Ollama"):
        llm.embed(["x"])
    fake_http(monkeypatch, lambda req: httpx.Response(404, json={"error": "not found"}))
    with pytest.raises(llm.LLMError, match="ollama pull qwen3-embedding:0.6b"):
        llm.embed(["x"])


def test_embed_count_mismatch_is_an_error(monkeypatch):
    fake_http(monkeypatch, lambda req: httpx.Response(200, json={"embeddings": []}))
    with pytest.raises(llm.LLMError, match="0 embeddings for 1"):
        llm.embed(["x"])


# -------------------------------------------------------------- gemini


class FakeGemini:
    def __init__(self, behaviour):
        self.behaviour = behaviour  # model -> list of texts, or an exception
        self.calls = []
        self.models = self

    def generate_content_stream(self, model, contents, config):
        self.calls.append((model, contents, config))
        result = self.behaviour.get(model, ["?"])
        if isinstance(result, Exception):
            raise result
        for text in result:
            yield type("Chunk", (), {"text": text})()


def test_gemini_path_converts_messages_and_streams(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "gemini")
    fake = FakeGemini({"gemini-3.5-flash": ["An", "swer"]})
    monkeypatch.setattr(llm, "_gemini_client", lambda: fake)
    convo = MSGS + [{"role": "assistant", "content": "Hello"}, {"role": "user", "content": "More"}]
    assert llm.chat(convo, stream=False) == "Answer"
    model, contents, config = fake.calls[0]
    assert config["system_instruction"] == "Be brief."
    assert [c["role"] for c in contents] == ["user", "model", "user"]


def test_gemini_falls_back_when_busy(monkeypatch):
    from google.genai import errors

    monkeypatch.setenv("LLM_PROVIDER", "gemini")
    busy = errors.ServerError(503, {"error": {"message": "busy", "status": "UNAVAILABLE"}})
    fake = FakeGemini({"gemini-3.5-flash": busy, "gemini-3.6-flash": ["ok"]})
    monkeypatch.setattr(llm, "_gemini_client", lambda: fake)
    assert llm.chat(MSGS, stream=False) == "ok"
    assert [c[0] for c in fake.calls] == ["gemini-3.5-flash", "gemini-3.6-flash"]


def test_gemini_all_busy(monkeypatch):
    from google.genai import errors

    monkeypatch.setenv("LLM_PROVIDER", "gemini")
    busy = errors.ServerError(503, {"error": {"message": "busy", "status": "UNAVAILABLE"}})
    fake = FakeGemini({m: busy for m in ["gemini-3.5-flash", *llm.GEMINI_FALLBACKS]})
    monkeypatch.setattr(llm, "_gemini_client", lambda: fake)
    with pytest.raises(llm.LLMUnavailable, match="All Gemini models are busy"):
        llm.chat(MSGS, stream=False)


def test_gemini_without_key_is_clear(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "gemini")
    with pytest.raises(llm.LLMError, match="GEMINI_API_KEY is not set"):
        llm.chat(MSGS, stream=False)


# -------------------------------------------------------------- health


def test_health_reports_down_without_raising(monkeypatch):
    monkeypatch.setenv("LLM_BASE_URL", "http://127.0.0.1:9/v1")
    info = llm.health()
    assert info["provider"] == "ollama" and info["ollama"].startswith("down")


def test_health_lists_missing_models(monkeypatch):
    fake_http(monkeypatch, lambda req: httpx.Response(200, json={"models": [{"name": "qwen3.5:2b"}]}))
    info = llm.health()
    assert info["ollama"] == "up"
    assert info["missing_models"] == ["qwen3-embedding:0.6b"]


# ------------------------------------------------- optional live check

live = pytest.mark.skipif(os.environ.get("OLLAMA_LIVE") != "1", reason="set OLLAMA_LIVE=1 to hit the real Ollama")


@live
def test_live_ollama_chat_and_embed(monkeypatch):
    answer = llm.chat([{"role": "user", "content": "Reply with the single word: ready"}], stream=False)
    assert "ready" in answer.lower()
    vec = llm.embed(["Safe Mode"], query=True)[0]
    assert len(vec) == 1024
