"""Knowledge base (kb/): PDF -> Markdown -> chunks -> vectors, the upload /
replace / delete / edit flows, and the CLI. Embeddings are faked with a
bag-of-words hash so retrieval is meaningful without Ollama; PDFs are
generated with PyMuPDF."""
import io
import os
import re

import pymupdf
import pytest

import app as app_module
import database as db
from ai import llm
from kb import chunk, config, convert, store, worker
from kb_fakes import fake_embed


@pytest.fixture(autouse=True)
def clean(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("EMBED_MODEL", raising=False)
    monkeypatch.setattr(llm, "embed", fake_embed)
    for r in db.list_resources():
        db.delete_resource(r["id"])
    if os.path.exists(config.KB_DB):
        store.reset_index()
        with store.connect() as c:
            c.execute("DELETE FROM kb_documents")
    yield


@pytest.fixture
def admin():
    app_module.app.config["TESTING"] = True
    c = app_module.app.test_client()
    with c.session_transaction() as s:
        s["is_admin"] = True
    return c


def make_pdf(sections, title="Guide", scanned=False):
    """sections: [(heading, paragraph)] -> PDF bytes with real text (or,
    scanned=True, the same pages as images only)."""
    doc = pymupdf.open()
    html = f"<h1>{title}</h1>" + "".join(f"<h2>{h}</h2><p>{p}</p>" for h, p in sections)
    page = doc.new_page()
    page.insert_htmlbox(page.rect + (40, 40, -40, -40), html)
    if scanned:
        img = pymupdf.open()
        for p in doc:
            new = img.new_page(width=p.rect.width, height=p.rect.height)
            new.insert_image(new.rect, pixmap=p.get_pixmap(dpi=72))
        doc = img
    return doc.tobytes()


SAFE_MODE = [
    ("Turn off your Mac", "Click the Apple menu and choose Shut Down. Wait until the screen is black."),
    ("Hold Shift", "Hold the Shift key and click Continue in Safe Mode."),
]
SAFARI = [
    ("Show the Develop menu", "Open Safari Settings, Advanced, and check Show Develop menu."),
    ("Preserve Log", "In the Network tab of the Web Inspector enable Preserve Log and reload the website."),
]


def upload(client, filename, data, title=""):
    return client.post(
        "/admin/resources/upload",
        data={"title": title, "file": (io.BytesIO(data), filename)},
        content_type="multipart/form-data",
    )


def rid_of(title):
    return [r["id"] for r in db.list_resources() if r["title"] == title][0]


# ----------------------------------------------------------- convert


def test_clean_markdown_drops_labels_and_rejoins_urls():
    raw = (
        "```\n1 / 4\n```\n\n```\nMACOS · SAFE MODE\n```\n\n# Title\n\n"
        "```\n3SAFE MODE\n```\n\n## Paste the address\n\n"
        "```\nhttps://transcomger.identit\ny.secureauth.com\n```\n\n"
        "Click **Start** . Done\n\n\n\n"
    )
    md = convert.clean_markdown(raw)
    assert "1 / 4" not in md and "MACOS" not in md and "3SAFE" not in md
    assert "https://transcomger.identity.secureauth.com" in md
    assert "**Start**." in md
    assert "\n\n\n" not in md and "```" not in md


def test_pdf_to_markdown_keeps_headings(tmp_path):
    path = tmp_path / "g.pdf"
    path.write_bytes(make_pdf(SAFE_MODE, "Safe Mode"))
    conv = convert.pdf_to_markdown(str(path))
    assert conv.pages == 1 and conv.chars_per_page > 50
    assert re.search(r"^#+ .*Hold Shift", conv.markdown, re.M)
    assert "Continue in Safe Mode" in conv.markdown


def test_scanned_pdf_needs_ocr(tmp_path):
    path = tmp_path / "scan.pdf"
    path.write_bytes(make_pdf(SAFE_MODE, scanned=True))
    with pytest.raises(convert.NeedsOCR, match="scanned"):
        convert.pdf_to_markdown(str(path))


# ------------------------------------------------------------- chunk


def test_chunks_have_heading_paths_and_sizes():
    body = " ".join(f"word{i}" for i in range(250))
    md = "# My Guide\n\nIntro text.\n\n## Part 1\n\n### Step A\n\n" + body + "\n\n### Step B\n\n" + body + "\n\n## Part 2\n\n" + body
    chunks = chunk.chunk_markdown(md, "My Guide")
    assert [c["ord"] for c in chunks] == list(range(len(chunks)))
    assert all(c["words"] <= chunk.HARD_MAX for c in chunks)
    assert chunks[1]["section"] == "Part 1 › Step B"  # the H1 title is not repeated
    # ~40 words of overlap between consecutive chunks
    assert chunks[1]["text"].split()[0] in chunks[0]["text"]


def test_label_headings_are_not_section_names():
    md = "# MACOS · ADVISOR'S EDITION\n\n## Erase the Mac\n\nOpen Settings.\n"
    assert chunk.sections(md, "Quick Wipe")[1][0] == "Erase the Mac"
    assert chunk.sections("# MACOS LABEL\n\ntext\n", "Quick Wipe")[0][0] == "Quick Wipe"


def test_section_path_keeps_last_two_levels():
    md = "## Part one\n\n### Set up\n\n#### Enter password\n\ntext\n"
    assert chunk.sections(md, "T")[-1][0] == "Set up › Enter password"


def test_long_section_is_windowed():
    md = "## Big\n\n" + " ".join(f"w{i}" for i in range(1000))
    chunks = chunk.chunk_markdown(md, "T")
    assert len(chunks) >= 3 and all(c["words"] <= chunk.HARD_MAX for c in chunks)


def test_small_guide_is_one_chunk_with_line_breaks():
    chunks = chunk.chunk_markdown("## Step 1\n\nOpen Safari.\n\n## Step 2\n\n1. Click\n2. Done\n", "T")
    assert len(chunks) == 1
    assert "## Step 2\n\n1. Click\n2. Done" in chunks[0]["text"]


# ------------------------------------------------- upload -> indexed


def test_upload_is_pending_then_indexed(admin):
    res = upload(admin, "Safe_Mode.pdf", make_pdf(SAFE_MODE, "Safe Mode"))
    assert res.status_code == 302
    rid = rid_of("Safe Mode")
    assert store.get(rid)["status"] == "pending"
    page = admin.get("/admin/resources").get_data(as_text=True)
    assert "Pending" in page

    assert worker.run_pending(log=lambda m: None) == {rid: "indexed"}
    doc = store.get(rid)
    assert doc["status"] == "indexed" and doc["chunks"] >= 1 and doc["pages"] == 1
    assert "Hold Shift" in store.read_markdown(rid)
    assert os.path.exists(config.md_path(rid))
    # the PDF itself is untouched and still downloadable
    r = db.get_resource(rid)
    assert os.path.exists(os.path.join(app_module.TUTORIALS_DIR, r["filename"]))
    assert admin.get(f"/tutorials/{rid}/download").status_code == 200
    assert admin.get("/admin/resources/kb-status").get_json()[str(rid)]["status"] == "indexed"


def test_retrieval_returns_relevant_chunks(admin):
    upload(admin, "Safe_Mode.pdf", make_pdf(SAFE_MODE, "Safe Mode"))
    upload(admin, "Safari.pdf", make_pdf(SAFARI, "Safari Logs"))
    worker.run_pending(log=lambda m: None)
    hits = store.search(fake_embed(["How do I enable Preserve Log in the Web Inspector?"])[0], k=2)
    assert hits[0]["title"] == "Safari"  # titles come from the file name
    assert "Preserve Log" in hits[0]["text"] and hits[0]["distance"] < hits[1]["distance"]
    hits = store.search(fake_embed(["Shift key Safe Mode"])[0], k=2)
    assert hits[0]["title"] == "Safe Mode"


def test_duplicate_upload_is_skipped(admin):
    data = make_pdf(SAFE_MODE, "Safe Mode")
    upload(admin, "Safe_Mode.pdf", data)
    res = upload(admin, "Copy_of_Safe_Mode.pdf", data)
    assert "uploaded=0" in res.headers["Location"]
    assert len(db.list_resources()) == 1
    page = admin.get(res.headers["Location"]).get_data(as_text=True)
    assert "already uploaded as" in page and "Safe Mode" in page


def test_scanned_upload_shows_needs_ocr(admin):
    upload(admin, "Scan.pdf", make_pdf(SAFE_MODE, scanned=True))
    rid = rid_of("Scan")
    assert worker.run_pending(log=lambda m: None) == {rid: "needs_ocr"}
    page = admin.get("/admin/resources").get_data(as_text=True)
    assert "Needs OCR" in page and "Retry" in page


def test_embedding_failure_is_failed_with_message_and_retry(admin, monkeypatch):
    def down(texts, query=False):
        raise llm.LLMUnavailable("Cannot reach Ollama at http://127.0.0.1:11434/v1.")

    monkeypatch.setattr(llm, "embed", down)
    upload(admin, "Safe_Mode.pdf", make_pdf(SAFE_MODE, "Safe Mode"))
    rid = rid_of("Safe Mode")
    worker.run_pending(log=lambda m: None)
    assert store.get(rid)["status"] == "failed"
    assert "Cannot reach Ollama" in store.get(rid)["error"]
    assert "Retry" in admin.get("/admin/resources").get_data(as_text=True)

    monkeypatch.setattr(llm, "embed", fake_embed)
    admin.post(f"/admin/resources/{rid}/reindex")
    worker.run_pending(log=lambda m: None)
    assert store.get(rid)["status"] == "indexed"


# ---------------------------------------------- replace / delete / edit


def test_replace_swaps_pdf_and_chunks_without_duplicates(admin):
    upload(admin, "Guide.pdf", make_pdf(SAFE_MODE, "Safe Mode"))
    rid = rid_of("Guide")
    worker.run_pending(log=lambda m: None)
    old = db.get_resource(rid)
    old_ids = {c["id"] for c in store.chunks_for(rid)}

    res = admin.post(
        f"/admin/resources/{rid}/replace",
        data={"file": (io.BytesIO(make_pdf(SAFARI, "Safari Logs")), "Guide_v2.pdf")},
        content_type="multipart/form-data",
    )
    assert res.status_code == 302
    new = db.get_resource(rid)
    assert new["id"] == rid and new["title"] == "Guide"  # same id, title kept
    assert new["filename"] != old["filename"]
    assert not os.path.exists(os.path.join(app_module.TUTORIALS_DIR, old["filename"]))
    assert store.get(rid)["status"] == "pending"

    worker.run_pending(log=lambda m: None)
    chunks = store.chunks_for(rid)
    assert chunks and not ({c["id"] for c in chunks} & old_ids)
    assert "Preserve Log" in store.read_markdown(rid)
    assert not any("Shift" in c["text"] for c in chunks)
    with store.connect() as c:
        assert c.execute("SELECT COUNT(*) FROM kb_vec").fetchone()[0] == len(chunks)


def test_replace_with_same_or_other_existing_pdf(admin):
    a, b = make_pdf(SAFE_MODE, "A"), make_pdf(SAFARI, "B")
    upload(admin, "A.pdf", a)
    upload(admin, "B.pdf", b)
    rid = rid_of("A")
    same = admin.post(f"/admin/resources/{rid}/replace",
                      data={"file": (io.BytesIO(a), "A.pdf")}, content_type="multipart/form-data")
    assert same.status_code == 302
    assert "nothing to replace" in admin.get("/admin/resources").get_data(as_text=True)
    other = admin.post(f"/admin/resources/{rid}/replace",
                       data={"file": (io.BytesIO(b), "B.pdf")}, content_type="multipart/form-data")
    assert other.status_code == 200 and "already uploaded as" in other.get_data(as_text=True)


def test_delete_removes_pdf_markdown_chunks_and_vectors(admin):
    upload(admin, "Safe_Mode.pdf", make_pdf(SAFE_MODE, "Safe Mode"))
    upload(admin, "Safari.pdf", make_pdf(SAFARI, "Safari Logs"))
    worker.run_pending(log=lambda m: None)
    rid = rid_of("Safe Mode")
    pdf = os.path.join(app_module.TUTORIALS_DIR, db.get_resource(rid)["filename"])

    admin.post(f"/admin/resources/{rid}/delete")
    assert not os.path.exists(pdf)
    assert not os.path.exists(config.md_path(rid))
    assert store.get(rid) is None and store.chunks_for(rid) == []
    with store.connect() as c:
        remaining = c.execute("SELECT COUNT(*) FROM kb_chunks").fetchone()[0]
        assert c.execute("SELECT COUNT(*) FROM kb_vec").fetchone()[0] == remaining > 0
    assert all(h["title"] != "Safe Mode" for h in store.search(fake_embed(["Shift Safe Mode"])[0], k=5))


def test_markdown_edit_reindexes_and_survives_retry_until_reconvert(admin):
    upload(admin, "Safe_Mode.pdf", make_pdf(SAFE_MODE, "Safe Mode"))
    rid = rid_of("Safe Mode")
    worker.run_pending(log=lambda m: None)
    page = admin.get(f"/admin/resources/{rid}/markdown").get_data(as_text=True)
    assert "Hold Shift" in page and "Indexed chunks" in page

    res = admin.post(f"/admin/resources/{rid}/markdown",
                     data={"markdown": "## Fixed step\n\nUse the Option key, not Shift.\n"})
    assert res.status_code == 302
    assert store.get(rid)["status"] == "pending" and store.get(rid)["md_edited"] == 1
    worker.run_pending(log=lambda m: None)
    assert "Option key" in store.chunks_for(rid)[0]["text"]

    # Retry / reindex keeps the edit...
    admin.post(f"/admin/resources/{rid}/reindex")
    worker.run_pending(log=lambda m: None)
    assert "Option key" in store.read_markdown(rid)
    # ...Re-convert from PDF discards it.
    admin.post(f"/admin/resources/{rid}/reindex", data={"from_pdf": "1"})
    worker.run_pending(log=lambda m: None)
    assert "Hold Shift" in store.read_markdown(rid) and store.get(rid)["md_edited"] == 0


def test_markdown_editor_rejects_empty(admin):
    upload(admin, "Safe_Mode.pdf", make_pdf(SAFE_MODE, "Safe Mode"))
    rid = rid_of("Safe Mode")
    res = admin.post(f"/admin/resources/{rid}/markdown", data={"markdown": "   "})
    assert res.status_code == 200 and "The Markdown is empty" in res.get_data(as_text=True)


def test_admin_routes_require_login():
    c = app_module.app.test_client()
    for path in ("/admin/resources/1/markdown", "/admin/resources/kb-status"):
        assert c.get(path).status_code == 302
    assert c.post("/admin/resources/1/reindex").status_code == 302


# ----------------------------------------------------- robustness


def test_interrupted_job_is_requeued_on_startup(admin, monkeypatch):
    upload(admin, "Safe_Mode.pdf", make_pdf(SAFE_MODE, "Safe Mode"))
    rid = rid_of("Safe Mode")
    store.set_status(rid, store.PROCESSING)  # as if the worker died mid-job
    spawned = []
    monkeypatch.setattr(worker, "spawn", lambda: spawned.append(1))
    worker.startup()
    assert store.get(rid)["status"] == "pending" and spawned


def test_changed_embedding_model_is_reported(admin, monkeypatch):
    upload(admin, "Safe_Mode.pdf", make_pdf(SAFE_MODE, "Safe Mode"))
    worker.run_pending(log=lambda m: None)
    monkeypatch.setenv("EMBED_MODEL", "other-embed")
    upload(admin, "Safari.pdf", make_pdf(SAFARI, "Safari Logs"))
    rid = rid_of("Safari")
    worker.run_pending(log=lambda m: None)
    assert store.get(rid)["status"] == "failed"
    assert "reindex-all --force" in store.get(rid)["error"]


def test_cli_reindex_all_and_force(admin, monkeypatch, capsys):
    from kb.__main__ import main

    upload(admin, "Safe_Mode.pdf", make_pdf(SAFE_MODE, "Safe Mode"))
    upload(admin, "Safari.pdf", make_pdf(SAFARI, "Safari Logs"))
    main(["reindex-all"])
    out = capsys.readouterr().out
    assert "Queued 2 guide(s)" in out and "2 indexed" in out

    main(["reindex-all", "--only-missing"])
    assert "Queued 0 guide(s)" in capsys.readouterr().out

    monkeypatch.setenv("EMBED_MODEL", "other-embed")
    with pytest.raises(SystemExit, match="--force"):
        main(["reindex-all"])
    main(["reindex-all", "--force"])
    assert "2 indexed" in capsys.readouterr().out
    assert store.index_info()["embed_model"] == "other-embed"

    main(["status"])
    assert "indexed" in capsys.readouterr().out
