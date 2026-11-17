"""data/kb.db: per-guide status, chunks and their vectors (sqlite-vec).

Statuses: pending -> processing -> indexed | failed | needs_ocr.
A guide's chunks + vectors are always replaced or deleted in one
transaction, so the index never holds duplicates or half a document.
"""
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone

from kb import config

PENDING, PROCESSING, INDEXED, FAILED, NEEDS_OCR = "pending", "processing", "indexed", "failed", "needs_ocr"
STATUSES = (PENDING, PROCESSING, INDEXED, FAILED, NEEDS_OCR)

SCHEMA = """
CREATE TABLE IF NOT EXISTS kb_documents (
    resource_id INTEGER PRIMARY KEY,
    status TEXT NOT NULL,
    error TEXT,
    pdf_sha256 TEXT,
    md_path TEXT,
    md_edited INTEGER NOT NULL DEFAULT 0,
    pages INTEGER,
    chars_per_page INTEGER,
    chunks INTEGER,
    embed_model TEXT,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS kb_chunks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    resource_id INTEGER NOT NULL REFERENCES kb_documents(resource_id) ON DELETE CASCADE,
    ord INTEGER NOT NULL,
    title TEXT NOT NULL,
    section TEXT NOT NULL,
    text TEXT NOT NULL,
    words INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS kb_chunks_resource ON kb_chunks(resource_id);
CREATE TABLE IF NOT EXISTS kb_meta (key TEXT PRIMARY KEY, value TEXT);
"""


class IndexMismatch(RuntimeError):
    """kb.db was built with a different embedding model/dimension."""


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@contextmanager
def connect():
    import sqlite_vec

    os.makedirs(os.path.dirname(config.KB_DB), exist_ok=True)
    conn = sqlite3.connect(config.KB_DB, timeout=15)
    conn.row_factory = sqlite3.Row
    try:
        conn.enable_load_extension(True)
        sqlite_vec.load(conn)
        conn.enable_load_extension(False)
        conn.execute("PRAGMA journal_mode = WAL")  # web reads while the worker writes
        conn.execute("PRAGMA foreign_keys = ON")
        conn.executescript(SCHEMA)
        yield conn
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    finally:
        conn.close()


# ----------------------------------------------------------------- status


def enqueue(resource_id, pdf_sha256=None, *, keep_edits=True):
    """Mark a guide pending (insert or reset). keep_edits=False forgets an
    edited Markdown (used when the PDF itself is replaced)."""
    with connect() as c:
        c.execute(
            """INSERT INTO kb_documents (resource_id, status, pdf_sha256, updated_at)
               VALUES (?, 'pending', ?, ?)
               ON CONFLICT(resource_id) DO UPDATE SET
                 status = 'pending', error = NULL,
                 pdf_sha256 = COALESCE(excluded.pdf_sha256, kb_documents.pdf_sha256),
                 md_edited = CASE WHEN ? THEN kb_documents.md_edited ELSE 0 END,
                 updated_at = excluded.updated_at""",
            (resource_id, pdf_sha256, _now(), 1 if keep_edits else 0),
        )


def set_status(resource_id, status, error=None, **fields):
    assert status in STATUSES
    cols = {"status": status, "error": error, "updated_at": _now(), **fields}
    with connect() as c:
        c.execute(
            f"UPDATE kb_documents SET {', '.join(f'{k} = ?' for k in cols)} WHERE resource_id = ?",
            (*cols.values(), resource_id),
        )


def save_edited_markdown(resource_id, text, pdf_sha256=None):
    """Store admin-edited Markdown and queue it. The file is written first and
    the row flips to pending + md_edited in one statement, so a running
    worker can never pick the guide up half-way and re-convert the PDF."""
    path = write_markdown(resource_id, text)
    with connect() as c:
        c.execute(
            """INSERT INTO kb_documents (resource_id, status, pdf_sha256, md_path, md_edited, updated_at)
               VALUES (?, 'pending', ?, ?, 1, ?)
               ON CONFLICT(resource_id) DO UPDATE SET
                 status = 'pending', error = NULL, md_path = excluded.md_path,
                 md_edited = 1, updated_at = excluded.updated_at""",
            (resource_id, pdf_sha256, path, _now()),
        )


def get(resource_id):
    with connect() as c:
        row = c.execute("SELECT * FROM kb_documents WHERE resource_id = ?", (resource_id,)).fetchone()
    return dict(row) if row else None


def all_documents():
    """{resource_id: row dict} for the admin page."""
    with connect() as c:
        return {r["resource_id"]: dict(r) for r in c.execute("SELECT * FROM kb_documents")}


def ids_with_status(*statuses):
    with connect() as c:
        q = f"SELECT resource_id FROM kb_documents WHERE status IN ({','.join('?' * len(statuses))}) ORDER BY updated_at, resource_id"
        return [r[0] for r in c.execute(q, statuses)]


def requeue_stuck():
    """processing rows left behind by a crash/restart go back to pending."""
    with connect() as c:
        return c.execute(
            "UPDATE kb_documents SET status = 'pending', updated_at = ? WHERE status = 'processing'", (_now(),)
        ).rowcount


# --------------------------------------------------------- chunks/vectors


def _meta(c, key):
    row = c.execute("SELECT value FROM kb_meta WHERE key = ?", (key,)).fetchone()
    return row[0] if row else None


def _ensure_vec(c, model, dim):
    have_model, have_dim = _meta(c, "embed_model"), _meta(c, "dim")
    if have_model is None:
        c.execute(
            f"CREATE VIRTUAL TABLE IF NOT EXISTS kb_vec USING vec0("
            f"chunk_id INTEGER PRIMARY KEY, embedding float[{int(dim)}] distance_metric=cosine)"
        )
        c.executemany("INSERT OR REPLACE INTO kb_meta VALUES (?, ?)", [("embed_model", model), ("dim", str(dim))])
    elif have_model != model or int(have_dim) != dim:
        raise IndexMismatch(
            f"The knowledge base was built with {have_model} ({have_dim} dims) but EMBED_MODEL is "
            f"{model} ({dim} dims). Rebuild it: python -m kb reindex-all --force"
        )


def index_info():
    with connect() as c:
        return {"embed_model": _meta(c, "embed_model"), "dim": _meta(c, "dim")}


def reset_index():
    """Drop every chunk and vector (EMBED_MODEL changed)."""
    with connect() as c:
        c.execute("DROP TABLE IF EXISTS kb_vec")
        c.execute("DELETE FROM kb_chunks")
        c.execute("DELETE FROM kb_meta")
        c.execute("UPDATE kb_documents SET chunks = 0")


def _delete_chunks(c, resource_id):
    if c.execute("SELECT 1 FROM sqlite_master WHERE name = 'kb_vec'").fetchone():
        c.execute(
            "DELETE FROM kb_vec WHERE chunk_id IN (SELECT id FROM kb_chunks WHERE resource_id = ?)",
            (resource_id,),
        )
    c.execute("DELETE FROM kb_chunks WHERE resource_id = ?", (resource_id,))


def replace_chunks(resource_id, title, chunks, vectors, *, model, **doc_fields):
    """Swap a guide's chunks/vectors for new ones and mark it indexed - all
    in one transaction."""
    import sqlite_vec

    if len(chunks) != len(vectors):
        raise ValueError("one vector per chunk")
    with connect() as c:
        if vectors:
            _ensure_vec(c, model, len(vectors[0]))
        _delete_chunks(c, resource_id)
        for ch, vec in zip(chunks, vectors):
            cur = c.execute(
                "INSERT INTO kb_chunks (resource_id, ord, title, section, text, words) VALUES (?, ?, ?, ?, ?, ?)",
                (resource_id, ch["ord"], title, ch["section"], ch["text"], ch["words"]),
            )
            c.execute(
                "INSERT INTO kb_vec (chunk_id, embedding) VALUES (?, ?)",
                (cur.lastrowid, sqlite_vec.serialize_float32(vec)),
            )
        cols = {"status": INDEXED, "error": None, "chunks": len(chunks), "embed_model": model,
                "updated_at": _now(), **doc_fields}
        c.execute(
            f"UPDATE kb_documents SET {', '.join(f'{k} = ?' for k in cols)} WHERE resource_id = ?",
            (*cols.values(), resource_id),
        )


def delete_document(resource_id):
    """Remove a guide's status row, chunks, vectors and Markdown file."""
    with connect() as c:
        _delete_chunks(c, resource_id)
        c.execute("DELETE FROM kb_documents WHERE resource_id = ?", (resource_id,))
    try:
        os.remove(config.md_path(resource_id))
    except FileNotFoundError:
        pass


def chunks_for(resource_id):
    with connect() as c:
        return [dict(r) for r in c.execute(
            "SELECT * FROM kb_chunks WHERE resource_id = ? ORDER BY ord", (resource_id,))]


def search(query_vector, k=4):
    """Nearest chunks to an embedded question: [{resource_id, title, section,
    text, words, distance}] best first. Only indexed guides are returned."""
    import sqlite_vec

    with connect() as c:
        if not c.execute("SELECT 1 FROM sqlite_master WHERE name = 'kb_vec'").fetchone():
            return []
        dim = int(_meta(c, "dim"))
        if len(query_vector) != dim:
            raise IndexMismatch(f"Query vector has {len(query_vector)} dims, index has {dim}.")
        rows = c.execute(
            """SELECT ch.resource_id, ch.title, ch.section, ch.text, ch.words, ch.ord, v.distance
               FROM (SELECT chunk_id, distance FROM kb_vec
                     WHERE embedding MATCH ? AND k = ? ORDER BY distance) v
               JOIN kb_chunks ch ON ch.id = v.chunk_id
               JOIN kb_documents d ON d.resource_id = ch.resource_id AND d.status = 'indexed'
               ORDER BY v.distance""",
            (sqlite_vec.serialize_float32(query_vector), int(k)),
        ).fetchall()
    return [dict(r) for r in rows]


# --------------------------------------------------------------- markdown


def read_markdown(resource_id):
    try:
        with open(config.md_path(resource_id), encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        return None


def write_markdown(resource_id, text):
    os.makedirs(config.MD_DIR, exist_ok=True)
    path = config.md_path(resource_id)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(text)
    os.replace(tmp, path)
    return path
