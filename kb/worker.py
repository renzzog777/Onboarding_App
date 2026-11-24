"""Background indexing job.

The web app never converts or embeds inside a request. It marks the guide
pending (store.enqueue) and calls spawn(), which starts a short-lived
`python -m kb worker` process. That process takes an exclusive file lock
(one worker at a time - one model job on the CPU), indexes every pending
guide, checks again, and exits, so the ~400 MB PDF conversion is freed
afterwards and a Gunicorn worker restart can't interrupt it.

A spawn that arrives while a worker runs simply waits for the lock and then
finds what is left - nothing queued is ever missed.
"""
import fcntl
import hashlib
import os
import subprocess
import sys
import threading
import time
from contextlib import contextmanager

from kb import config, store
from kb.chunk import chunk_markdown
from kb.convert import NeedsOCR, pdf_to_markdown


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


@contextmanager
def worker_lock(blocking=True):
    """Yields True if the lock is held, False (non-blocking) if another
    worker has it."""
    os.makedirs(config.KB_DIR, exist_ok=True)
    with open(config.LOCK_FILE, "w") as f:
        try:
            fcntl.flock(f, fcntl.LOCK_EX | (0 if blocking else fcntl.LOCK_NB))
        except BlockingIOError:
            yield False
            return
        try:
            yield True
        finally:
            fcntl.flock(f, fcntl.LOCK_UN)


# -------------------------------------------------------------- one guide


def _resource(resource_id):
    import database as db

    return db.get_resource(resource_id)


def embed_texts(chunks, title):
    """Vectors for chunks; the heading path is embedded with the text."""
    from ai import llm

    return llm.embed([f"{title} › {c['section']}\n\n{c['text']}" for c in chunks])


def process(resource_id, log=print):
    """Convert (or reuse edited Markdown), chunk, embed, store. Always leaves
    the guide in a final status; never raises for a per-guide problem."""
    from ai import llm

    resource = _resource(resource_id)
    if resource is None:  # deleted meanwhile
        store.delete_document(resource_id)
        return None
    title = resource["title"]
    doc = store.get(resource_id) or {}
    store.set_status(resource_id, store.PROCESSING)
    started = time.time()
    try:
        fields = {}
        markdown = store.read_markdown(resource_id) if doc.get("md_edited") else None
        if markdown is None:
            pdf = os.path.join(config.TUTORIALS_DIR, resource["filename"])
            if not os.path.exists(pdf):
                raise FileNotFoundError(f"PDF missing on disk: {resource['filename']}")
            conv = pdf_to_markdown(pdf)
            markdown = conv.markdown
            fields = {"pages": conv.pages, "chars_per_page": conv.chars_per_page, "md_edited": 0}
        md_file = store.write_markdown(resource_id, markdown)
        chunks = chunk_markdown(markdown, title)
        if not chunks:
            raise ValueError("The Markdown has no text to index.")
        vectors = embed_texts(chunks, title)
        store.replace_chunks(
            resource_id, title, chunks, vectors,
            model=llm.setting("EMBED_MODEL"), md_path=md_file, **fields,
        )
        log(f"kb: indexed {resource_id} ({title}): {len(chunks)} chunks in {time.time() - started:.1f}s")
        return store.INDEXED
    except NeedsOCR as exc:
        store.set_status(resource_id, store.NEEDS_OCR, str(exc))
        log(f"kb: {resource_id} ({title}) needs OCR")
        return store.NEEDS_OCR
    except Exception as exc:  # one bad guide must not stop the queue
        msg = str(exc) or type(exc).__name__
        store.set_status(resource_id, store.FAILED, msg[:500])
        log(f"kb: FAILED {resource_id} ({title}): {msg}")
        return store.FAILED


def run_pending(log=print):
    """Index every pending guide, re-checking until none is left."""
    results = {}
    with worker_lock():
        while True:
            ids = [i for i in store.ids_with_status(store.PENDING) if i not in results]
            if not ids:
                break
            for rid in ids:
                results[rid] = process(rid, log=log)
    return results


# ---------------------------------------------------------- from the app


def spawn():
    """Start a detached worker process for the pending queue."""
    import database as db

    os.makedirs(config.KB_DIR, exist_ok=True)
    env = dict(os.environ)
    env.update(KB_DATA_DIR=config.DATA_DIR, KB_TUTORIALS_DIR=config.TUTORIALS_DIR, APP_DB_PATH=db.DB_PATH)
    log = open(config.LOG_FILE, "a")
    try:
        proc = subprocess.Popen(
            [sys.executable, "-m", "kb", "worker"],
            cwd=config.BASE_DIR, env=env, stdin=subprocess.DEVNULL,
            stdout=log, stderr=subprocess.STDOUT, start_new_session=True,
        )
    finally:
        log.close()
    # Reap it when it exits so no zombie is left in the web worker.
    threading.Thread(target=proc.wait, daemon=True).start()
    return proc


def enqueue_and_spawn(resource_id, pdf_sha256=None, *, keep_edits=True):
    store.enqueue(resource_id, pdf_sha256, keep_edits=keep_edits)
    spawn()


def startup():
    """On app start: if no worker is running, put interrupted jobs back in
    the queue, and start a worker if anything is waiting."""
    try:
        with worker_lock(blocking=False) as free:
            if free:
                store.requeue_stuck()
        if store.ids_with_status(store.PENDING):
            spawn()
    except Exception as exc:  # never block the web app from starting
        print(f"kb: startup check failed: {exc}")
