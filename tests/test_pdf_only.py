import io
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from reportlab.pdfgen import canvas

import app as app_module
import database as db


@pytest.fixture
def admin():
    app_module.app.config["TESTING"] = True
    c = app_module.app.test_client()
    with c.session_transaction() as s:
        s["is_admin"] = True
    return c


def _pdf_bytes():
    buf = io.BytesIO()
    cv = canvas.Canvas(buf)
    cv.drawString(100, 750, "hello")
    cv.save()
    return buf.getvalue()


def test_config():
    assert app_module.ALLOWED_EXTENSIONS == {"pdf": {"pdf"}}
    assert app_module.app.config["MAX_CONTENT_LENGTH"] == 100 * 1024 * 1024


def test_legacy_video_hidden_publicly_but_listed_for_admin(admin):
    rid = db.add_resource("LegacyVideoXYZ", "video", "x.mp4", "x.mp4")
    try:
        public = app_module.app.test_client().get("/tutorials")
        assert public.status_code == 200
        assert b"LegacyVideoXYZ" not in public.data
        assert b"VIDEO" not in public.data
        page = admin.get("/admin/resources")
        assert page.status_code == 200
        assert b"LegacyVideoXYZ" in page.data  # admin can still delete it
        assert b'value="video"' not in page.data
        assert b'accept=".pdf,application/pdf"' in page.data
    finally:
        db.delete_resource(rid)


def test_non_pdf_rejected(admin):
    r = admin.post(
        "/admin/resources/upload",
        data={"title": "V", "file": (io.BytesIO(b"x"), "v.mp4")},
        content_type="multipart/form-data",
    )
    assert r.status_code == 200
    assert b"Allowed: pdf" in r.data


def test_missing_file_error(admin):
    r = admin.post(
        "/admin/resources/upload",
        data={"title": "Some title"},
        content_type="multipart/form-data",
    )
    assert b"Choose a PDF file to upload." in r.data


def test_pdf_upload_ignores_form_type_and_makes_thumbnail(admin):
    r = admin.post(
        "/admin/resources/upload",
        data={"title": "GoodPDF", "resource_type": "video",
              "file": (io.BytesIO(_pdf_bytes()), "guide.pdf")},
        content_type="multipart/form-data",
    )
    assert r.status_code == 302
    row = [x for x in db.list_resources() if x["title"] == "GoodPDF"][0]
    try:
        assert row["resource_type"] == "pdf"
        assert row["thumbnail"]
        assert b"GoodPDF" in app_module.app.test_client().get("/tutorials").data
    finally:
        admin.post(f"/admin/resources/{row['id']}/delete")
