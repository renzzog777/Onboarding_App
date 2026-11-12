"""Manage Tutorials upload: the title defaults to the file name."""
import io

import pytest

import app as app_module
import database as db


@pytest.fixture
def admin(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    for r in db.list_resources():
        db.delete_resource(r["id"])
    app_module.app.config["TESTING"] = True
    c = app_module.app.test_client()
    with c.session_transaction() as s:
        s["is_admin"] = True
    return c


def upload(client, filename, title=""):
    return client.post(
        "/admin/resources/upload",
        data={"title": title, "file": (io.BytesIO(b"%PDF-1.4 fake"), filename)},
        content_type="multipart/form-data",
    )


def titles():
    return [r["title"] for r in db.list_resources()]


@pytest.mark.parametrize(
    "filename, expected",
    [
        ("Office_WiFi_Setup.pdf", "Office WiFi Setup"),
        ("How to set up Avaya.PDF", "How to set up Avaya"),
        ("SAP  login - v2.pdf", "SAP login - v2"),
    ],
)
def test_blank_title_uses_file_name(admin, filename, expected):
    assert upload(admin, filename).status_code == 302
    assert titles() == [expected]


def test_typed_title_wins(admin):
    upload(admin, "file_123.pdf", title="Custom title")
    assert titles() == ["Custom title"]


def test_file_still_required(admin):
    res = admin.post("/admin/resources/upload", data={"title": "x"}, content_type="multipart/form-data")
    assert "Choose a PDF file" in res.get_data(as_text=True)
    assert titles() == []
