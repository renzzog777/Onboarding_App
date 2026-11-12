"""Tutorials assistant (chatbot.py). Gemini is replaced by fakes - these
tests never call Google."""
import io
import json
import os
from types import SimpleNamespace as NS

import pytest

import app as app_module
import chatbot
import database as db


@pytest.fixture
def client():
    app_module.app.config["TESTING"] = True
    return app_module.app.test_client()


@pytest.fixture(autouse=True)
def clean_state(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    for f in (chatbot.STORE_FILE, chatbot.RATE_DB):
        if os.path.exists(f):
            os.remove(f)
    for r in db.list_resources():
        db.delete_resource(r["id"])
    yield


def enable(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")


def add_tutorial(title="Wi-Fi setup"):
    path = os.path.join(app_module.TUTORIALS_DIR, "abc_wifi.pdf")
    with open(path, "wb") as f:
        f.write(b"%PDF-1.4 fake")
    return db.add_resource(title, "pdf", "abc_wifi.pdf", "wifi.pdf")


def index_as(rid, title="Wi-Fi setup"):
    chatbot._save_state(
        {"store": "fileSearchStores/s1", "docs": {str(rid): {"doc": "doc/1", "title": title}}}
    )


def fake_response(text, titles):
    chunks = [NS(retrieved_context=NS(title=t)) for t in titles]
    return NS(text=text, candidates=[NS(grounding_metadata=NS(grounding_chunks=chunks))])


def ask(client, question):
    return client.post("/tutorials/assistant", json={"question": question})


# ------------------------------------------------------------------ page


def test_panel_hidden_without_api_key(client):
    html = client.get("/tutorials").get_data(as_text=True)
    assert "Ask the assistant" not in html
    assert ask(client, "hi").status_code == 404


def test_panel_waits_for_index(client, monkeypatch):
    enable(monkeypatch)
    html = client.get("/tutorials").get_data(as_text=True)
    assert "Ask the assistant" in html
    assert 'id="assistantForm"' not in html


def test_panel_ready_when_indexed(client, monkeypatch):
    enable(monkeypatch)
    index_as(add_tutorial())
    html = client.get("/tutorials").get_data(as_text=True)
    assert 'id="assistantForm"' in html


# ------------------------------------------------------------------ endpoint


def test_answer_with_linked_source(client, monkeypatch):
    enable(monkeypatch)
    rid = add_tutorial()
    index_as(rid)
    monkeypatch.setattr(
        chatbot, "_ask_gemini", lambda q, s: fake_response("1. Open Settings.", ["Wi-Fi setup"])
    )
    data = ask(client, "How do I join Wi-Fi?").get_json()
    assert data["answer"] == "1. Open Settings."
    assert data["sources"] == [
        {"title": "Wi-Fi setup", "url": f"/tutorials/{rid}/download"}
    ]


def test_answer_without_citation_is_refused(client, monkeypatch):
    enable(monkeypatch)
    index_as(add_tutorial())
    monkeypatch.setattr(chatbot, "_ask_gemini", lambda q, s: fake_response("Made up.", []))
    assert ask(client, "What is the capital of France?").get_json()["answer"] == chatbot.REFUSAL


def test_non_english_question_short_circuits(client, monkeypatch):
    enable(monkeypatch)
    index_as(add_tutorial())

    def boom(*a):
        raise AssertionError("Gemini must not be called")

    monkeypatch.setattr(chatbot, "_ask_gemini", boom)
    assert ask(client, "¿Cómo configuro el Wi-Fi?").get_json()["answer"] == chatbot.LANG_NOTICE


def test_validation(client, monkeypatch):
    enable(monkeypatch)
    assert ask(client, "   ").status_code == 400
    assert ask(client, "x" * 501).status_code == 400
    assert client.post("/tutorials/assistant", data="question=hi").status_code == 400


def test_all_models_busy(client, monkeypatch):
    enable(monkeypatch)
    index_as(add_tutorial())
    monkeypatch.setattr(chatbot, "_ask_gemini", lambda q, s: None)
    assert ask(client, "Wi-Fi?").status_code == 503


def test_internal_errors_are_not_leaked(client, monkeypatch):
    enable(monkeypatch)
    index_as(add_tutorial())

    def fail(*a):
        raise RuntimeError("secret internal detail")

    monkeypatch.setattr(chatbot, "_ask_gemini", fail)
    res = ask(client, "Wi-Fi?")
    assert res.status_code == 500
    assert "secret" not in res.get_data(as_text=True)


def test_rate_limit_per_ip(client, monkeypatch):
    enable(monkeypatch)
    index_as(add_tutorial())
    monkeypatch.setattr(chatbot, "_ask_gemini", lambda q, s: fake_response("ok", ["Wi-Fi setup"]))
    codes = [
        client.post(
            "/tutorials/assistant", json={"question": "q"}, headers={"CF-Connecting-IP": "1.2.3.4"}
        ).status_code
        for _ in range(chatbot.RATE_LIMIT + 1)
    ]
    assert codes[:-1] == [200] * chatbot.RATE_LIMIT and codes[-1] == 429
    other = client.post(
        "/tutorials/assistant", json={"question": "q"}, headers={"CF-Connecting-IP": "5.6.7.8"}
    )
    assert other.status_code == 200


# ------------------------------------------------------------------ sync


class FakeClient:
    def __init__(self):
        self.uploaded, self.deleted = [], []
        fake = self

        class Docs:
            def delete(self, name, config=None):
                fake.deleted.append(name)

        class Stores:
            documents = Docs()

            def create(self, config=None):
                return NS(name="fileSearchStores/new")

            def upload_to_file_search_store(self, file, file_search_store_name, config):
                fake.uploaded.append(config["display_name"])
                return NS(done=True, error=None, response=NS(document_name=f"doc/{len(fake.uploaded)}"))

        self.file_search_stores = Stores()


def test_sync_uploads_new_and_deletes_removed(monkeypatch):
    enable(monkeypatch)
    fake = FakeClient()
    monkeypatch.setattr(chatbot, "client", lambda: fake)
    rid = add_tutorial("Café Wi-Fi guide")

    chatbot.sync_knowledge_base(app_module.TUTORIALS_DIR, log=lambda m: None)
    state = chatbot.load_state()
    assert state["store"] == "fileSearchStores/new"
    assert state["docs"] == {str(rid): {"doc": "doc/1", "title": "Caf Wi-Fi guide"}}
    assert fake.uploaded == ["Caf Wi-Fi guide"]  # non-ASCII stripped for the HTTP header

    chatbot.sync_knowledge_base(app_module.TUTORIALS_DIR, log=lambda m: None)
    assert len(fake.uploaded) == 1  # already indexed: nothing to do

    db.delete_resource(rid)
    chatbot.sync_knowledge_base(app_module.TUTORIALS_DIR, log=lambda m: None)
    assert fake.deleted == ["doc/1"]
    assert chatbot.load_state()["docs"] == {}


def test_admin_page_shows_index_status(client, monkeypatch):
    enable(monkeypatch)
    index_as(add_tutorial())
    with client.session_transaction() as s:
        s["is_admin"] = True
    html = client.get("/admin/resources").get_data(as_text=True)
    assert "Indexed" in html
